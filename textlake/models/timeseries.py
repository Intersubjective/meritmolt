"""Time-series snapshot tables (append-only, partition-ready PK)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from textlake.models.base import TextLakeBase


class MbAgentStatsTs(TextLakeBase):
    """Append-only agent stats snapshot."""

    __tablename__ = "mb_agent_stats_ts"

    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    agent_id: Mapped[str] = mapped_column(String(64), primary_key=True, nullable=False)
    karma: Mapped[int | None] = mapped_column(Integer, nullable=True)
    follower_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    following_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class MbSubmoltStatsTs(TextLakeBase):
    """Append-only submolt stats snapshot."""

    __tablename__ = "mb_submolt_stats_ts"

    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    submolt_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, nullable=False
    )
    subscriber_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    post_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class MbPostStatsTs(TextLakeBase):
    """Append-only post stats snapshot."""

    __tablename__ = "mb_post_stats_ts"

    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    post_id: Mapped[str] = mapped_column(String(64), primary_key=True, nullable=False)
    upvotes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    downvotes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class MbCommentStatsTs(TextLakeBase):
    """Append-only comment stats snapshot."""

    __tablename__ = "mb_comment_stats_ts"

    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    comment_id: Mapped[str] = mapped_column(
        String(64), primary_key=True, nullable=False
    )
    upvotes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    downvotes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
