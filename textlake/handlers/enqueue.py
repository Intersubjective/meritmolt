"""Enqueue a crawl task (dedupe by kind+params)."""

from __future__ import annotations

import hashlib
from typing import Any

import orjson
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from textlake.models.crawl import CrawlTask


def dedupe_key(kind: str, params: dict[str, Any]) -> str:
    """Stable key for deduplication."""
    canonical = orjson.dumps(params or {}, option=orjson.OPT_SORT_KEYS)
    return hashlib.sha256(f"{kind}:{canonical.decode()}".encode()).hexdigest()


async def enqueue(
    session: AsyncSession,
    kind: str,
    params: dict[str, Any],
    *,
    priority: int = 0,
) -> None:
    """Insert a task with ON CONFLICT DO NOTHING on dedupe_key."""
    key = dedupe_key(kind, params)
    stmt = pg_insert(CrawlTask).values(
        kind=kind,
        params=params,
        dedupe_key=key,
        priority=priority,
    )
    stmt = stmt.on_conflict_do_nothing(index_elements=["dedupe_key"])
    await session.execute(stmt)
