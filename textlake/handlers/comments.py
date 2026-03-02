"""Handler for fetch_post_comments."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from textlake.client import MoltbookClient
from textlake.handlers.registry import register
from textlake.ids import synthetic_agent_id
from textlake.models.entities import MbComment, MbPost
from textlake.models.timeseries import MbCommentStatsTs
from textlake.upsert import upsert_agent, upsert_comment


def _parse_ts(raw: object) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(float(raw), tz=timezone.utc)
    if isinstance(raw, str):
        try:
            if "T" in raw or "Z" in raw or "+" in raw:
                return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(
                    timezone.utc
                )
            return None
        except ValueError:
            return None
    return None


def _agent_stub(data: dict) -> dict | None:
    name = (data.get("name") or data.get("username") or "").strip()
    if not name:
        return None
    aid = data.get("id") or data.get("agent_id") or synthetic_agent_id(name)
    if isinstance(aid, dict):
        aid = aid.get("id") or synthetic_agent_id(name)
    return {
        "id": str(aid),
        "name": name,
        "description": data.get("description"),
        "created_at_src": _parse_ts(data.get("created_at")),
        "karma": data.get("karma"),
        "is_claimed": data.get("is_claimed"),
        "is_human": data.get("is_human"),
        "raw_json": data,
    }


def _comment_row(data: dict, post_id: str) -> dict | None:
    cid = data.get("id")
    if not cid:
        return None
    author = data.get("author") or data
    agent_stub = _agent_stub(author) if isinstance(author, dict) else None
    parent_id = data.get("parent_id")
    return {
        "id": str(cid),
        "post_id": post_id,
        "parent_id": str(parent_id) if parent_id is not None else None,
        "author_name": agent_stub["name"] if agent_stub else None,
        "author_id": agent_stub["id"] if agent_stub else None,
        "content": data.get("content") or data.get("body") or "",
        "created_at_src": _parse_ts(data.get("created_at")),
        "upvotes": data.get("upvotes"),
        "downvotes": data.get("downvotes"),
        "raw_json": data,
    }


def _topological_sort_comment_rows(rows: list[dict], batch_ids: set[str]) -> list[dict]:
    """Order rows: parents before children (Kahn). parent_id not in batch_ids = root."""
    rows_by_id = {r["id"]: r for r in rows}
    children_by_parent: dict[str, list[str]] = {}
    in_degree: dict[str, int] = {}
    for r in rows:
        cid = r["id"]
        pid = r.get("parent_id")
        if pid is not None and pid in batch_ids:
            children_by_parent.setdefault(pid, []).append(cid)
            in_degree[cid] = 1
        else:
            in_degree[cid] = 0
    ready = deque(cid for cid in rows_by_id if in_degree[cid] == 0)
    sorted_rows: list[dict] = []
    while ready:
        cid = ready.popleft()
        sorted_rows.append(rows_by_id[cid])
        for child_id in children_by_parent.get(cid, []):
            in_degree[child_id] -= 1
            if in_degree[child_id] == 0:
                ready.append(child_id)
    # Any remaining (cycles): append as roots and null parent_id so FK holds
    output_ids = {r["id"] for r in sorted_rows}
    for r in rows:
        if r["id"] not in output_ids:
            r = dict(r)
            r["parent_id"] = None
            sorted_rows.append(r)
    return sorted_rows


@register("fetch_post_comments")
async def handle_fetch_post_comments(
    session: AsyncSession,
    client: MoltbookClient,
    params: dict,
) -> None:
    """GET /posts/:id/comments?sort=...; upsert comments, set comments_fetched."""
    post_id = params.get("post_id")
    if not post_id:
        return
    sort = params.get("sort", "top")
    data = await client.get(f"/posts/{post_id}/comments", params={"sort": sort})
    items = (
        data.get("items") or data.get("data") or data
        if isinstance(data, list)
        else (data.get("comments") or [])
    )
    if not isinstance(items, list):
        items = [data]
    # Build comment rows and upsert agents first; dedupe by id (keep first).
    rows: list[dict] = []
    seen_ids: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        author = item.get("author")
        if isinstance(author, dict):
            stub = _agent_stub(author)
            if stub:
                await upsert_agent(session, stub, is_authoritative=False)
        row = _comment_row(item, post_id)
        if not row or row["id"] in seen_ids:
            continue
        seen_ids.add(row["id"])
        rows.append(row)
    # Resolve parents outside the batch: query DB, then null parent_id when missing.
    batch_ids = {r["id"] for r in rows}
    missing_parent_ids = list(
        {
            r["parent_id"]
            for r in rows
            if r.get("parent_id") and r["parent_id"] not in batch_ids
        }
    )
    existing_parent_ids: set[str] = set()
    if missing_parent_ids:
        result = await session.execute(
            select(MbComment.id).where(MbComment.id.in_(missing_parent_ids))
        )
        existing_parent_ids = {row[0] for row in result.all()}
    for row in rows:
        pid = row.get("parent_id")
        if pid and pid not in batch_ids and pid not in existing_parent_ids:
            row["parent_id"] = None
    # Topological sort so parents are inserted before children.
    sorted_rows = _topological_sort_comment_rows(rows, batch_ids)
    # Upsert comments in sorted order.
    for row in sorted_rows:
        await upsert_comment(session, row, is_authoritative=False)
    fetched = len(sorted_rows)
    now = datetime.now(timezone.utc)
    for item in items:
        if not isinstance(item, dict):
            continue
        cid = item.get("id")
        if not cid:
            continue
        session.add(
            MbCommentStatsTs(
                ts=now,
                comment_id=str(cid),
                upvotes=item.get("upvotes"),
                downvotes=item.get("downvotes"),
                raw_json=item,
            )
        )
    result = await session.execute(select(MbPost).where(MbPost.id == post_id))
    post = result.scalars().first()
    expected = None
    if isinstance(data, dict):
        expected = (
            data.get("total")
            or data.get("comment_count")
            or (len(items) if items else 0)
        )
    if post is not None:
        new_fetched = (post.comments_fetched or 0) + fetched
        truncated = expected is not None and new_fetched < expected
        await session.execute(
            update(MbPost)
            .where(MbPost.id == post_id)
            .values(
                comments_fetched=new_fetched,
                comments_truncated=post.comments_truncated or truncated,
                last_comments_fetch_at=now,
            )
        )
    await session.commit()
