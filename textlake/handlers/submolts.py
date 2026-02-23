"""Handlers for submolt endpoints: list_submolts, fetch_submolt."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from textlake.client import MoltbookClient
from textlake.handlers.enqueue import enqueue
from textlake.handlers.registry import register
from textlake.ids import synthetic_submolt_id
from textlake.models.timeseries import MbSubmoltStatsTs
from textlake.upsert import upsert_submolt


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


def _submolt_row(data: dict, is_authoritative: bool) -> dict:
    """Build mb_submolt row from API-like dict."""
    name = (data.get("name") or data.get("slug") or "").strip() or None
    if not name:
        return {}
    sid = data.get("id") or synthetic_submolt_id(name)
    if isinstance(sid, dict):
        sid = sid.get("id") or synthetic_submolt_id(name)
    return {
        "id": str(sid),
        "name": name,
        "display_name": data.get("display_name") or data.get("display_name") or name,
        "description": data.get("description"),
        "created_at_src": _parse_ts(data.get("created_at")),
        "raw_json": data,
        "first_seen_at": datetime.now(timezone.utc),
        "last_seen_at": datetime.now(timezone.utc),
    }


@register("list_submolts")
async def handle_list_submolts(
    session: AsyncSession,
    client: MoltbookClient,
    params: dict,
) -> None:
    """GET /submolts; upsert stubs, enqueue fetch_submolt per name."""
    data = await client.get("/submolts", params=params or {})
    items = (
        data.get("items") or data.get("data") or data
        if isinstance(data, list)
        else (data.get("submolts") or [])
    )
    if not isinstance(items, list):
        items = [data]
    seen = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        row = _submolt_row(item, is_authoritative=False)
        if not row:
            continue
        await upsert_submolt(session, row, is_authoritative=False)
        await enqueue(session, "fetch_submolt", {"name": row["name"]}, priority=5)
        seen += 1
    await session.commit()


@register("fetch_submolt")
async def handle_fetch_submolt(
    session: AsyncSession,
    client: MoltbookClient,
    params: dict,
) -> None:
    """GET /submolts/:name; enrich mb_submolt + snapshot."""
    name = params.get("name")
    if not name:
        return
    data = await client.get(f"/submolts/{name}")
    if not isinstance(data, dict):
        return
    row = _submolt_row(data, is_authoritative=True)
    if not row:
        return
    await upsert_submolt(session, row, is_authoritative=True)
    now = datetime.now(timezone.utc)
    session.add(
        MbSubmoltStatsTs(
            ts=now,
            submolt_id=row["id"],
            subscriber_count=data.get("subscriber_count") or data.get("subscribers"),
            post_count=data.get("post_count") or data.get("posts_count"),
            raw_json=data,
        )
    )
    await session.commit()
