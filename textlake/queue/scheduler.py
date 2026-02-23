"""Scheduler: enqueue recurring tasks, dedupe, parked recovery, raw_capture prune."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

import orjson
from sqlalchemy import delete, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from textlake.models.crawl import CrawlTask
from textlake.models.crawl import RawCapture as RawCaptureModel

SCHEDULER_INTERVAL = 30
LIST_SUBMOLTS_INTERVAL = 900
POLL_FEED_INTERVAL = 60
RAW_CAPTURE_PRUNE_INTERVAL = 3600
PARKED_RECOVERY_AFTER_SECONDS = 3600
RAW_CAPTURE_TTL_HOURS = 24


def _dedupe_key(kind: str, params: dict[str, Any]) -> str:
    """Stable key for deduplication: sha256(kind + canonical_json(params))."""
    canonical = orjson.dumps(params or {}, option=orjson.OPT_SORT_KEYS)
    return hashlib.sha256(f"{kind}:{canonical.decode()}".encode()).hexdigest()


async def scheduler_loop(
    session_factory: async_sessionmaker[AsyncSession],
    shutdown: asyncio.Event,
) -> None:
    """Enqueue recurring tasks; run parked task recovery and raw_capture prune."""
    from textlake.log import get_logger

    logger = get_logger("scheduler")
    last_list_submolts: datetime | None = None
    last_poll_feed: dict[str, datetime] = {}
    last_prune: datetime | None = None
    last_parked_recovery: datetime | None = None

    while not shutdown.is_set():
        try:
            now = datetime.now(timezone.utc)

            async with session_factory() as session:
                if (
                    last_list_submolts is None
                    or (now - last_list_submolts).total_seconds()
                    >= LIST_SUBMOLTS_INTERVAL
                ):
                    key = _dedupe_key("list_submolts", {})
                    stmt = pg_insert(CrawlTask).values(
                        kind="list_submolts",
                        params={},
                        dedupe_key=key,
                        priority=10,
                    )
                    stmt = stmt.on_conflict_do_nothing(index_elements=["dedupe_key"])
                    await session.execute(stmt)
                    last_list_submolts = now

                for sort in ("hot", "new", "rising", "top"):
                    last = last_poll_feed.get(sort)
                    if (
                        last is None
                        or (now - last).total_seconds() >= POLL_FEED_INTERVAL
                    ):
                        key = _dedupe_key("poll_posts_feed", {"sort": sort})
                        stmt = pg_insert(CrawlTask).values(
                            kind="poll_posts_feed",
                            params={"sort": sort, "limit": 25},
                            dedupe_key=key,
                            priority=8,
                        )
                        stmt = stmt.on_conflict_do_nothing(
                            index_elements=["dedupe_key"]
                        )
                        await session.execute(stmt)
                        last_poll_feed[sort] = now

                if (
                    last_parked_recovery is None
                    or (now - last_parked_recovery).total_seconds() >= 600
                ):
                    await session.execute(
                        update(CrawlTask)
                        .where(
                            (CrawlTask.attempts >= CrawlTask.max_attempts)
                            & (
                                CrawlTask.updated_at
                                < now - timedelta(seconds=PARKED_RECOVERY_AFTER_SECONDS)
                            )
                        )
                        .values(attempts=0, not_before=now, updated_at=now)
                    )
                    last_parked_recovery = now

                if (
                    last_prune is None
                    or (now - last_prune).total_seconds() >= RAW_CAPTURE_PRUNE_INTERVAL
                ):
                    await session.execute(
                        delete(RawCaptureModel).where(
                            RawCaptureModel.fetched_at
                            < now - timedelta(hours=RAW_CAPTURE_TTL_HOURS)
                        )
                    )
                    last_prune = now

                await session.commit()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("scheduler_error", error=str(e))
        await asyncio.sleep(SCHEDULER_INTERVAL)
