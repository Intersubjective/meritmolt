"""Async engine, session factory, and database bootstrap for textlake."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

if TYPE_CHECKING:
    from textlake.config import CrawlerSettings


async def ensure_database(settings: CrawlerSettings) -> None:
    """Create the textlake database if it does not exist. Uses raw asyncpg because
    CREATE DATABASE cannot run inside a transaction.
    """
    import asyncpg

    conn = await asyncpg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password or None,
        database="postgres",
    )
    try:
        row = await conn.fetchrow(
            "SELECT 1 FROM pg_database WHERE datname = $1", settings.postgres_db
        )
        if row is None:
            await conn.execute(f'CREATE DATABASE "{settings.postgres_db}"')
    finally:
        await conn.close()


def init_engine(
    settings: CrawlerSettings,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Create async engine and session factory for the textlake database."""
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_size=settings.mb_concurrency + 2,
        max_overflow=5,
    )
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    return engine, session_factory


async def create_schema(engine: AsyncEngine) -> None:
    """Create all TextLake tables (idempotent). After ensure_database + init_engine."""
    import textlake.models as _models  # noqa: F401
    from textlake.models.base import TextLakeBase

    # Ensure all models are loaded so metadata includes every table

    _models.__all__  # avoid unused import warning

    async with engine.begin() as conn:
        await conn.run_sync(TextLakeBase.metadata.create_all)
