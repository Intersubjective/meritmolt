"""Handlers for post endpoints: poll_posts_feed, fetch_post."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from textlake.client import MoltbookClient
from textlake.handlers.enqueue import enqueue
from textlake.handlers.registry import register
from textlake.ids import synthetic_agent_id, synthetic_submolt_id
from textlake.models.timeseries import MbPostStatsTs
from textlake.upsert import upsert_agent, upsert_post, upsert_submolt


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
    """Build mb_agent stub from embedded author."""
    name = (
        data.get("name") or data.get("username") or data.get("author_name") or ""
    ).strip()
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


def _submolt_stub(data: dict) -> dict | None:
    """Build mb_submolt stub from embedded submolt."""
    name = (data.get("name") or data.get("slug") or "").strip()
    if not name:
        return None
    sid = data.get("id") or synthetic_submolt_id(name)
    if isinstance(sid, dict):
        sid = sid.get("id") or synthetic_submolt_id(name)
    return {
        "id": str(sid),
        "name": name,
        "display_name": data.get("display_name") or name,
        "description": data.get("description"),
        "created_at_src": _parse_ts(data.get("created_at")),
        "raw_json": data,
    }


def _post_row(data: dict, is_authoritative: bool = False) -> dict | None:
    """Build mb_post row from API-like dict."""
    pid = data.get("id")
    if not pid:
        return None
    author = data.get("author") or data
    submolt = data.get("submolt") or data
    agent_stub = _agent_stub(author) if isinstance(author, dict) else None
    submolt_stub = _submolt_stub(submolt) if isinstance(submolt, dict) else None
    submolt_name = (
        submolt.get("name") or submolt.get("slug")
        if isinstance(submolt, dict)
        else None
    )
    return {
        "id": str(pid),
        "submolt_name": submolt_name,
        "submolt_id": submolt_stub["id"] if submolt_stub else None,
        "author_name": agent_stub["name"] if agent_stub else None,
        "author_id": agent_stub["id"] if agent_stub else None,
        "title": data.get("title"),
        "content": data.get("content") or data.get("body"),
        "url": data.get("url"),
        "created_at_src": _parse_ts(data.get("created_at")),
        "updated_at_src": _parse_ts(data.get("updated_at")),
        "upvotes": data.get("upvotes"),
        "downvotes": data.get("downvotes"),
        "comment_count": data.get("comment_count") or data.get("comments_count"),
        "raw_json": data,
    }


@register("poll_posts_feed")
async def handle_poll_posts_feed(
    session: AsyncSession,
    client: MoltbookClient,
    params: dict,
) -> None:
    """Poll /posts; upsert stubs, enqueue fetch_post and fetch_post_comments."""
    sort = params.get("sort", "hot")
    limit = params.get("limit", 25)
    data = await client.get("/posts", params={"sort": sort, "limit": limit})
    items = (
        data.get("items") or data.get("data") or data
        if isinstance(data, list)
        else (data.get("posts") or [])
    )
    if not isinstance(items, list):
        items = [data]
    for item in items:
        if not isinstance(item, dict):
            continue
        author = item.get("author")
        submolt = item.get("submolt")
        if isinstance(author, dict):
            stub = _agent_stub(author)
            if stub:
                await upsert_agent(session, stub, is_authoritative=False)
        if isinstance(submolt, dict):
            stub = _submolt_stub(submolt)
            if stub:
                await upsert_submolt(session, stub, is_authoritative=False)
        row = _post_row(item, is_authoritative=False)
        if not row:
            continue
        await upsert_post(session, row, is_authoritative=False)
        await enqueue(session, "fetch_post", {"post_id": row["id"]}, priority=6)
        await enqueue(
            session,
            "fetch_post_comments",
            {"post_id": row["id"], "sort": "top"},
            priority=4,
        )
    now = datetime.now(timezone.utc)
    for item in items:
        if not isinstance(item, dict):
            continue
        pid = item.get("id")
        if not pid:
            continue
        session.add(
            MbPostStatsTs(
                ts=now,
                post_id=str(pid),
                upvotes=item.get("upvotes"),
                downvotes=item.get("downvotes"),
                comment_count=item.get("comment_count") or item.get("comments_count"),
                raw_json=item,
            )
        )
    await session.commit()


@register("fetch_post")
async def handle_fetch_post(
    session: AsyncSession,
    client: MoltbookClient,
    params: dict,
) -> None:
    """Enrich mb_post from /posts/:id; optionally enqueue fetch_post_comments."""
    post_id = params.get("post_id")
    if not post_id:
        return
    data = await client.get(f"/posts/{post_id}")
    if not isinstance(data, dict):
        return
    author = data.get("author")
    submolt = data.get("submolt")
    if isinstance(author, dict):
        stub = _agent_stub(author)
        if stub:
            await upsert_agent(session, stub, is_authoritative=False)
    if isinstance(submolt, dict):
        stub = _submolt_stub(submolt)
        if stub:
            await upsert_submolt(session, stub, is_authoritative=False)
    row = _post_row(data, is_authoritative=True)
    if not row:
        return
    await upsert_post(session, row, is_authoritative=True)
    now = datetime.now(timezone.utc)
    session.add(
        MbPostStatsTs(
            ts=now,
            post_id=str(data.get("id", post_id)),
            upvotes=data.get("upvotes"),
            downvotes=data.get("downvotes"),
            comment_count=data.get("comment_count") or data.get("comments_count"),
            raw_json=data,
        )
    )
    api_comment_count = data.get("comment_count") or data.get("comments_count")
    if api_comment_count is not None:
        from sqlalchemy import select

        from textlake.models.entities import MbPost

        res = await session.execute(select(MbPost).where(MbPost.id == post_id))
        post = res.scalars().first()
        if post and (post.comments_fetched or 0) < api_comment_count:
            from textlake.handlers.enqueue import enqueue

            await enqueue(
                session,
                "fetch_post_comments",
                {"post_id": post_id, "sort": "top"},
                priority=5,
            )
    await session.commit()
