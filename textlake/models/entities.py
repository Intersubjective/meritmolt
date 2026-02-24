"""Entity tables: mb_agent, mb_submolt, mb_post, mb_comment."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from textlake.models.base import TextLakeBase


class MbAgent(TextLakeBase):
    """Moltbook agent (canonical id or synthetic from name)."""

    __tablename__ = "mb_agent"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(CITEXT(), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at_src: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    karma: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_claimed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_human: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    raw_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MbSubmolt(TextLakeBase):
    """Moltbook submolt (community)."""

    __tablename__ = "mb_submolt"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(CITEXT(), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at_src: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    raw_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MbPost(TextLakeBase):
    """Moltbook post."""

    __tablename__ = "mb_post"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    submolt_name: Mapped[str | None] = mapped_column(CITEXT(), nullable=True)
    submolt_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("mb_submolt.id", ondelete="SET NULL"),
        nullable=True,
    )
    author_name: Mapped[str | None] = mapped_column(CITEXT(), nullable=True)
    author_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("mb_agent.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at_src: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at_src: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    upvotes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    downvotes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    comments_fetched: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    comments_truncated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    last_comments_fetch_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ticker: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    submolt: Mapped["MbSubmolt | None"] = relationship("MbSubmolt")
    author: Mapped["MbAgent"] = relationship("MbAgent")
    comments: Mapped[list["MbComment"]] = relationship(
        "MbComment",
        back_populates="post",
        foreign_keys="MbComment.post_id",
    )


class MbComment(TextLakeBase):
    """Moltbook comment on a post."""

    __tablename__ = "mb_comment"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    post_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("mb_post.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("mb_comment.id", ondelete="SET NULL"),
        nullable=True,
    )
    author_name: Mapped[str | None] = mapped_column(CITEXT(), nullable=True)
    author_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("mb_agent.id", ondelete="CASCADE"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at_src: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    upvotes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    downvotes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ticker: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    post: Mapped["MbPost"] = relationship(
        "MbPost",
        back_populates="comments",
        foreign_keys=[post_id],
    )
    parent: Mapped["MbComment | None"] = relationship(
        "MbComment",
        remote_side="MbComment.id",
        foreign_keys=[parent_id],
    )
