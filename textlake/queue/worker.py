"""Worker: claim tasks with SELECT FOR UPDATE SKIP LOCKED, run handler, finalize."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from textlake.client import RateLimitResetError, TransientAuthError
from textlake.models.crawl import CrawlTask

LEASE_SECONDS = 300
POLL_INTERVAL_MIN = 0.5
POLL_INTERVAL_MAX = 5.0
PARK_DAYS = 30


def _backoff_seconds(attempts: int) -> int:
    """Exponential backoff with cap (e.g. 2^attempts, max 3600)."""
    return min(2**attempts, 3600)


async def worker_loop(
    session_factory: async_sessionmaker[AsyncSession],
    client: Any,
    worker_id: str,
    shutdown: asyncio.Event,
) -> None:
    """Run a single worker: claim task, dispatch, finalize. Respects shutdown event."""
    from textlake.handlers.registry import get_handler

    logger = __import__("textlake.log", fromlist=["get_logger"]).get_logger("worker")
    poll_interval = POLL_INTERVAL_MIN
    while not shutdown.is_set():
        task_row: CrawlTask | None = None
        try:
            async with session_factory() as session:
                now = datetime.now(timezone.utc)
                stmt = (
                    select(CrawlTask)
                    .where(
                        and_(
                            CrawlTask.attempts < CrawlTask.max_attempts,
                            (CrawlTask.not_before.is_(None))
                            | (CrawlTask.not_before <= now),
                            (CrawlTask.locked_until.is_(None))
                            | (CrawlTask.locked_until < now),
                        )
                    )
                    .order_by(CrawlTask.priority.desc(), CrawlTask.created_at.asc())
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                result = await session.execute(stmt)
                task_row = result.scalars().first()
                if task_row is None:
                    await session.commit()
                    poll_interval = min(poll_interval * 1.2, POLL_INTERVAL_MAX)
                    await asyncio.sleep(poll_interval)
                    continue
                poll_interval = POLL_INTERVAL_MIN
                task_id = task_row.id
                kind = task_row.kind
                params = task_row.params or {}
                locked_until = now + timedelta(seconds=LEASE_SECONDS)
                await session.execute(
                    update(CrawlTask)
                    .where(CrawlTask.id == task_id)
                    .values(locked_by=worker_id, locked_until=locked_until)
                )
                await session.commit()
            handler = get_handler(kind)
            if handler is None:
                async with session_factory() as session:
                    await session.execute(
                        delete(CrawlTask).where(CrawlTask.id == task_id)
                    )
                    await session.commit()
                continue
            try:
                async with session_factory() as session:
                    await handler(session, client, params)
                    await session.commit()
                async with session_factory() as session:
                    await session.execute(
                        delete(CrawlTask).where(CrawlTask.id == task_id)
                    )
                    await session.commit()
            except (TransientAuthError, RateLimitResetError) as e:
                async with session_factory() as session:
                    reset_at = getattr(e, "reset_at", None)
                    not_before = reset_at if reset_at else now + timedelta(minutes=5)
                    await session.execute(
                        update(CrawlTask)
                        .where(CrawlTask.id == task_id)
                        .values(
                            attempts=CrawlTask.attempts + 1,
                            not_before=not_before,
                            last_error=str(e),
                            locked_by=None,
                            locked_until=None,
                            updated_at=now,
                        )
                    )
                    await session.commit()
            except Exception as e:
                async with session_factory() as session:
                    row = await session.get(CrawlTask, task_id)
                    if row is None:
                        continue
                    new_attempts = row.attempts + 1
                    not_before = now + timedelta(seconds=_backoff_seconds(new_attempts))
                    if new_attempts >= row.max_attempts:
                        not_before = now + timedelta(days=PARK_DAYS)
                    await session.execute(
                        update(CrawlTask)
                        .where(CrawlTask.id == task_id)
                        .values(
                            attempts=new_attempts,
                            not_before=not_before,
                            last_error=str(e)[:4096],
                            locked_by=None,
                            locked_until=None,
                            updated_at=now,
                        )
                    )
                    await session.commit()
                logger.exception(
                    "task_failed", kind=kind, task_id=str(task_id), error=str(e)
                )
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.exception("worker_loop_error", worker_id=worker_id, error=str(e))
            await asyncio.sleep(1)
