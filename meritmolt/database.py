"""SQLAlchemy async engine, session factory, and ORM models for MeritMolt."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from meritmolt.config import Settings
from meritmolt.tentura.ddl import (
    EXTENSION_SQL,
    TRIGGER_FUNCTIONS_SQL,
    TRIGGERS_SQL,
    VIEWS_SQL,
    WRAPPER_FUNCTIONS_SQL,
)
from meritmolt.tentura.models import TenturaBase

# Set by init_db(); used by get_db_session
engine: AsyncEngine | None = None
async_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_db(settings: Settings) -> None:
    """Create async engine, session factory, Tentura schema + triggers/functions,
    and MM tables.
    """
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
    async with engine.begin() as conn:
        await conn.execute(text(EXTENSION_SQL))
        await conn.run_sync(TenturaBase.metadata.create_all)
        await conn.execute(text(VIEWS_SQL))
        await conn.execute(text(TRIGGER_FUNCTIONS_SQL))
        await conn.execute(text(TRIGGERS_SQL))
        await conn.execute(text(WRAPPER_FUNCTIONS_SQL))
        await conn.run_sync(Base.metadata.create_all)


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
    cached_stats: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
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
        ),
    )
