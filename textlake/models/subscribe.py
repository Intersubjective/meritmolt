"""user_vsids (ticker per agent), subscribe (MB user subscription)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from textlake.models.base import TextLakeBase


class UserVsids(TextLakeBase):
    """Per-agent ticker for MR edges. Bumped by triggers on each user action."""

    __tablename__ = "user_vsids"

    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("mb_agent.id", ondelete="CASCADE"),
        primary_key=True,
    )
    counter: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Subscribe(TextLakeBase):
    """MoltBook subscription of one user to another (subject subscribes to object)."""

    __tablename__ = "subscribe"
    __table_args__ = (
        CheckConstraint("amount >= -1 AND amount <= 1", name="subscribe_amount_check"),
    )

    subject: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("mb_agent.id", ondelete="CASCADE"),
        primary_key=True,
    )
    object: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("mb_agent.id", ondelete="CASCADE"),
        primary_key=True,
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    ticker: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
