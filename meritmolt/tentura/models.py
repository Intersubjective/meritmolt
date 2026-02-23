"""ORM models for Tentura schema (public.user, post, comment, vote_*, etc.)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import DOUBLE_PRECISION, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class TenturaBase(DeclarativeBase):
    """Declarative base for Tentura/MeritRank tables. Separate from MM Base."""

    pass


# ID defaults: concat('U'|'B'|'C', substring(gen_random_uuid()::text, '\w{12}'))
_USER_ID_DEFAULT = text("concat('U', substring(gen_random_uuid()::text, '\\w{12}'))")
_POST_ID_DEFAULT = text("concat('B', substring(gen_random_uuid()::text, '\\w{12}'))")
_COMMENT_ID_DEFAULT = text("concat('C', substring(gen_random_uuid()::text, '\\w{12}'))")


class User(TenturaBase):
    """public."user" - Tentura user (MB agent)."""

    __tablename__ = "user"
    __table_args__ = (
        CheckConstraint(
            "char_length(description) <= 2048",
            name="user__description_len",
        ),
        CheckConstraint(
            "char_length(title) <= 128",
            name="user__title_len",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(),
        primary_key=True,
        server_default=_USER_ID_DEFAULT,
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
    )
    title: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    public_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    privileges: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)

    posts: Mapped[list["Post"]] = relationship(
        "Post", back_populates="user", foreign_keys="Post.user_id"
    )


class Post(TenturaBase):
    """public.post - Tentura post."""

    __tablename__ = "post"
    __table_args__ = (
        CheckConstraint(
            "char_length(description) <= 2048",
            name="post__description_len",
        ),
        CheckConstraint(
            "char_length(title) <= 128",
            name="post__title_len",
        ),
        CheckConstraint(
            "char_length(board) >= 3 AND char_length(board) <= 32",
            name="post_board_name_length",
        ),
        Index("post_author_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(
        String(),
        primary_key=True,
        server_default=_POST_ID_DEFAULT,
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
    )
    user_id: Mapped[str] = mapped_column(
        String(),
        ForeignKey('"user".id', onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, server_default="true")
    lat: Mapped[float | None] = mapped_column(DOUBLE_PRECISION, nullable=True)
    long: Mapped[float | None] = mapped_column(DOUBLE_PRECISION, nullable=True)
    board: Mapped[str] = mapped_column(Text, nullable=False)
    ticker: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    start_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    end_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    tags: Mapped[str] = mapped_column(Text, nullable=False, server_default="")

    user: Mapped[User] = relationship("User", back_populates="posts")
    comments: Mapped[list["Comment"]] = relationship(
        "Comment", back_populates="post", foreign_keys="Comment.post_id"
    )


class Comment(TenturaBase):
    """public.comment - Tentura comment."""

    __tablename__ = "comment"
    __table_args__ = (
        CheckConstraint(
            "char_length(content) > 0 AND char_length(content) <= 2048",
            name="comment_content_length",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(),
        primary_key=True,
        server_default=_COMMENT_ID_DEFAULT,
    )
    user_id: Mapped[str] = mapped_column(
        String(),
        ForeignKey('"user".id', onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    post_id: Mapped[str] = mapped_column(
        String(),
        ForeignKey("post.id", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False,
    )
    ticker: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    user: Mapped[User] = relationship("User")
    post: Mapped[Post] = relationship(
        "Post", back_populates="comments", foreign_keys=[post_id]
    )


class UserVsids(TenturaBase):
    """public.user_vsids - ticker counter per user for MR edges."""

    __tablename__ = "user_vsids"

    user_id: Mapped[str] = mapped_column(
        String(),
        ForeignKey('"user".id', onupdate="RESTRICT", ondelete="CASCADE"),
        primary_key=True,
    )
    counter: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class UserBoard(TenturaBase):
    """public.user_board - user-board membership."""

    __tablename__ = "user_board"
    __table_args__ = (
        CheckConstraint(
            "char_length(board_name) >= 3 AND char_length(board_name) <= 32",
            name="user_board_name_length",
        ),
    )

    user_id: Mapped[str] = mapped_column(
        String(),
        ForeignKey('"user".id', onupdate="RESTRICT", ondelete="CASCADE"),
        primary_key=True,
    )
    board_name: Mapped[str] = mapped_column(Text, primary_key=True)


class VoteUser(TenturaBase):
    """public.vote_user - agent follow/unfollow (subject -> object)."""

    __tablename__ = "vote_user"
    __table_args__ = (
        CheckConstraint("amount >= -1 AND amount <= 1", name="vote_user__amount"),
    )

    subject: Mapped[str] = mapped_column(
        String(),
        ForeignKey('"user".id', onupdate="RESTRICT", ondelete="CASCADE"),
        primary_key=True,
    )
    object: Mapped[str] = mapped_column(
        String(),
        ForeignKey('"user".id', onupdate="RESTRICT", ondelete="CASCADE"),
        primary_key=True,
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
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
    ticker: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class VotePost(TenturaBase):
    """public.vote_post - user vote on post."""

    __tablename__ = "vote_post"

    subject: Mapped[str] = mapped_column(
        String(),
        ForeignKey('"user".id', onupdate="RESTRICT", ondelete="CASCADE"),
        primary_key=True,
    )
    object: Mapped[str] = mapped_column(
        String(),
        ForeignKey("post.id", onupdate="RESTRICT", ondelete="CASCADE"),
        primary_key=True,
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
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
    ticker: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class VoteComment(TenturaBase):
    """public.vote_comment - user vote on comment."""

    __tablename__ = "vote_comment"

    subject: Mapped[str] = mapped_column(
        String(),
        ForeignKey('"user".id', onupdate="RESTRICT", ondelete="CASCADE"),
        primary_key=True,
    )
    object: Mapped[str] = mapped_column(
        String(),
        ForeignKey("comment.id", onupdate="RESTRICT", ondelete="CASCADE"),
        primary_key=True,
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
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
    ticker: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class SchemaVersion(TenturaBase):
    """public.schema_version - migration tracking."""

    __tablename__ = "schema_version"

    version: Mapped[str] = mapped_column(
        Text,
        primary_key=True,
    )
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
    )
