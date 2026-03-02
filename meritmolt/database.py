"""SQLAlchemy async engine, session factory, and ORM models for MeritMolt.

init_db() imports TextLakeBase from textlake.models to create all TextLake tables
(mb_*, user_vsids, subscribe, etc.) in the same DB. Both packages live in the same
wheel; this cross-package dependency is intentional.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import UUID, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from meritmolt.config import Settings
from meritmolt.schema.ddl import (
    EXTENSION_SQL,
    PGMER_HELPERS_SQL,
    TRIGGER_FUNCTIONS_SQL,
    TRIGGERS_SQL,
    TYPES_SQL,
    WRAPPER_FUNCTIONS_SQL,
)

# Set by init_db(); used by get_db_session
engine: AsyncEngine | None = None
async_session_factory: async_sessionmaker[AsyncSession] | None = None

# meritrank_init retry: MeritRank service may not be ready at startup
_MERITRANK_INIT_MAX_RETRIES = 5
_MERITRANK_INIT_INITIAL_DELAY_SEC = 1.0
_MERITRANK_INIT_MAX_DELAY_SEC = 30.0
_MERITRANK_INIT_RETRYABLE_MESSAGE = "Try again"

_logger = logging.getLogger(__name__)


def _split_sql_statements(sql: str) -> list[str]:
    """Split SQL into individual statements, respecting quotes/comments/$-quotes.

    asyncpg rejects sending multiple commands in a single prepared statement, so we
    must execute DDL one statement at a time. This splitter is intentionally small
    and dependency-free but handles common PostgreSQL constructs like $$...$$.
    """

    statements: list[str] = []
    buf: list[str] = []

    in_single = False
    in_double = False
    in_line_comment = False
    in_block_comment = False
    dollar_tag: str | None = None

    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""

        if in_line_comment:
            buf.append(ch)
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue

        if in_block_comment:
            buf.append(ch)
            if ch == "*" and nxt == "/":
                buf.append(nxt)
                in_block_comment = False
                i += 2
            else:
                i += 1
            continue

        # Dollar-quoted blocks: $tag$ ... $tag$
        if dollar_tag is not None:
            if ch == "$":
                end = i + len(dollar_tag)
                if sql.startswith(dollar_tag, i):
                    buf.append(dollar_tag)
                    dollar_tag = None
                    i = end
                    continue
            buf.append(ch)
            i += 1
            continue

        if in_single:
            buf.append(ch)
            if ch == "'":
                # SQL escapes quotes by doubling: ''
                if nxt == "'":
                    buf.append(nxt)
                    i += 2
                else:
                    in_single = False
                    i += 1
            else:
                i += 1
            continue

        if in_double:
            buf.append(ch)
            if ch == '"':
                if nxt == '"':
                    buf.append(nxt)
                    i += 2
                else:
                    in_double = False
                    i += 1
            else:
                i += 1
            continue

        # Start of comments (only when not inside any quote)
        if ch == "-" and nxt == "-":
            buf.append(ch)
            buf.append(nxt)
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            buf.append(ch)
            buf.append(nxt)
            in_block_comment = True
            i += 2
            continue

        # Start of quotes
        if ch == "'":
            buf.append(ch)
            in_single = True
            i += 1
            continue
        if ch == '"':
            buf.append(ch)
            in_double = True
            i += 1
            continue

        # Start of dollar-quote tag
        if ch == "$":
            j = i + 1
            while j < n and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            if j < n and sql[j] == "$":
                dollar_tag = sql[i : j + 1]
                buf.append(dollar_tag)
                i = j + 1
                continue

        # Statement boundary
        if ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
            i += 1
            continue

        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)

    return statements


async def _exec_sql_batch(conn: AsyncConnection, sql: str) -> None:
    for stmt in _split_sql_statements(sql):
        await conn.exec_driver_sql(stmt)


def _is_sqlite(url: str) -> bool:
    """Return True if database_url is SQLite."""
    return "sqlite" in url


async def init_db(settings: Settings) -> None:
    """Create engine, session factory, TextLake tables, MR triggers, and MM tables."""
    global engine, async_session_factory
    engine = create_async_engine(
        settings.database_url,
        echo=False,
    )
    async_session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    url = settings.database_url
    if _is_sqlite(url):
        await _init_db_lite(engine)
    else:
        await _init_db_postgres(engine, settings)


async def _init_db_lite(eng: AsyncEngine) -> None:
    """Create only mm_agents and mm_refresh_tokens for SQLite (unit tests)."""
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _is_meritrank_retryable(exc: BaseException) -> bool:
    """True if meritrank_init failed with a transient 'Try again' error."""
    msg = str(exc)
    if _MERITRANK_INIT_RETRYABLE_MESSAGE in msg:
        return True
    cause = getattr(exc, "__cause__", None)
    if cause is not None:
        return _MERITRANK_INIT_RETRYABLE_MESSAGE in str(cause)
    return False


async def _meritrank_init_with_retry(conn: AsyncConnection) -> None:
    """Run meritrank_init() with retries; MeritRank may not be ready at startup."""
    delay = _MERITRANK_INIT_INITIAL_DELAY_SEC
    for attempt in range(_MERITRANK_INIT_MAX_RETRIES):
        try:
            await conn.execute(text("SELECT meritrank_init()"))
            return
        except DBAPIError as e:
            if (
                not _is_meritrank_retryable(e)
                or attempt == _MERITRANK_INIT_MAX_RETRIES - 1
            ):
                raise
            _logger.warning(
                "meritrank_init attempt %d/%d failed (MeritRank not ready): %s. "
                "Retrying in %.1fs.",
                attempt + 1,
                _MERITRANK_INIT_MAX_RETRIES,
                e,
                delay,
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, _MERITRANK_INIT_MAX_DELAY_SEC)


async def _init_db_postgres(eng: AsyncEngine, settings: Settings) -> None:
    """Full Postgres init with TextLake, pgmer2, triggers."""
    async with eng.begin() as conn:
        import textlake.models as _  # noqa: F401 - load all models so metadata is complete
        from textlake.models.base import TextLakeBase

        await _exec_sql_batch(conn, EXTENSION_SQL)
        await conn.run_sync(TextLakeBase.metadata.create_all)
        await _exec_sql_batch(conn, PGMER_HELPERS_SQL)
        await _exec_sql_batch(conn, TYPES_SQL)
        await _exec_sql_batch(conn, TRIGGER_FUNCTIONS_SQL)
        await _exec_sql_batch(conn, TRIGGERS_SQL)
        await _exec_sql_batch(conn, WRAPPER_FUNCTIONS_SQL)
        await conn.run_sync(Base.metadata.create_all)
        if settings.mm_meritrank_init_on_startup:
            await _meritrank_init_with_retry(conn)


class Base(DeclarativeBase):
    """Declarative base for MM tables."""

    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MmAgent(Base):
    """MoltBook agent registered in MeritMolt."""

    __tablename__ = "mm_agents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    mb_agent_id: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    mb_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        onupdate=_utc_now,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    refresh_tokens: Mapped[list["MmRefreshToken"]] = relationship(
        "MmRefreshToken",
        back_populates="agent",
        cascade="all, delete-orphan",
        foreign_keys="MmRefreshToken.agent_id",
    )


class MmRefreshToken(Base):
    """Refresh token (opaque, argon2 hash stored)."""

    __tablename__ = "mm_refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mm_agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rotated_from_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mm_refresh_tokens.id", ondelete="SET NULL"),
        nullable=True,
    )
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)

    agent: Mapped["MmAgent"] = relationship(
        "MmAgent",
        back_populates="refresh_tokens",
        foreign_keys=[agent_id],
    )
    rotated_from: Mapped["MmRefreshToken | None"] = relationship(
        "MmRefreshToken",
        remote_side="MmRefreshToken.id",
        foreign_keys=[rotated_from_id],
    )

    __table_args__ = (
        Index(
            "ix_mm_refresh_tokens_agent_id_active",
            "agent_id",
            postgresql_where=text("revoked_at IS NULL"),
            sqlite_where=text("revoked_at IS NULL"),
        ),
    )
