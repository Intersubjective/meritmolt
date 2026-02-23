"""Entrypoint for the TextLake crawler (python -m textlake)."""

from __future__ import annotations

import asyncio
import signal

from textlake.client import MoltbookClient
from textlake.config import get_settings
from textlake.database import ensure_database, init_engine, run_migrations
from textlake.log import configure_logging
from textlake.queue.scheduler import scheduler_loop
from textlake.queue.worker import worker_loop


def main() -> None:
    """Run the crawler: ensure DB, migrations, scheduler + workers."""
    asyncio.run(_run())


async def _run() -> None:
    configure_logging()
    settings = get_settings()
    await ensure_database(settings)
    await run_migrations(settings)
    engine, session_factory = init_engine(settings)

    shutdown = asyncio.Event()
    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, shutdown.set)
            except ValueError, OSError:
                pass
    except Exception:
        pass

    try:
        async with MoltbookClient(settings) as client:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(scheduler_loop(session_factory, shutdown))
                for i in range(settings.mb_concurrency):
                    tg.create_task(
                        worker_loop(session_factory, client, f"w-{i}", shutdown)
                    )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    main()
