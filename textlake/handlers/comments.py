"""Handler for fetch_post_comments."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from textlake.client import MoltbookClient
from textlake.handlers.registry import register
from textlake.ids import synthetic_agent_id
from textlake.models.entities import MbPost
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
    return {
        "id": str(cid),
        "post_id": post_id,
        "parent_id": data.get("parent_id"),
        "author_name": agent_stub["name"] if agent_stub else None,
        "author_id": agent_stub["id"] if agent_stub else None,
        "content": data.get("content") or data.get("body") or "",
        "created_at_src": _parse_ts(data.get("created_at")),
        "upvotes": data.get("upvotes"),
        "downvotes": data.get("downvotes"),
        "raw_json": data,
    }


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
    fetched = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        author = item.get("author")
        if isinstance(author, dict):
            stub = _agent_stub(author)
            if stub:
                await upsert_agent(session, stub, is_authoritative=False)
        row = _comment_row(item, post_id)
        if not row:
            continue
        await upsert_comment(session, row, is_authoritative=False)
        fetched += 1
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
