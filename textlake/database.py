"""Async engine, session factory, and database bootstrap for textlake."""

from __future__ import annotations

from pathlib import Path
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


async def run_migrations(settings: CrawlerSettings) -> None:
    """Run Alembic migrations to head. Config path is relative to this package."""
    from alembic import command
    from alembic.config import Config

    package_dir = Path(__file__).resolve().parent
    alembic_ini = package_dir / "alembic.ini"
    if not alembic_ini.exists():
        raise FileNotFoundError(f"Missing {alembic_ini}")
    cfg = Config(str(alembic_ini))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(cfg, "head")
