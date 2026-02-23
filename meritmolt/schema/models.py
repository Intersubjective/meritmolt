"""ORM models for MeritMolt schema (public.user, post, comment, vote_*, etc.)."""

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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class SchemaBase(DeclarativeBase):
    """Declarative base for MeritMolt schema (MeritRank-backed tables).
    Separate from MM Base.
    """

    pass


# ID defaults: concat('U'|'B'|'C', substring(gen_random_uuid()::text, '\w{12}'))
_USER_ID_DEFAULT = text("concat('U', substring(gen_random_uuid()::text, '\\w{12}'))")
_POST_ID_DEFAULT = text("concat('B', substring(gen_random_uuid()::text, '\\w{12}'))")
_COMMENT_ID_DEFAULT = text("concat('C', substring(gen_random_uuid()::text, '\\w{12}'))")


class User(SchemaBase):
    """public."user" - MeritMolt schema user (MB agent)."""

    __tablename__ = "user"

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

    posts: Mapped[list["Post"]] = relationship(
        "Post", back_populates="user", foreign_keys="Post.user_id"
    )


class Post(SchemaBase):
    """public.post - MeritMolt schema post."""

    __tablename__ = "post"
    __table_args__ = (
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
    user_id: Mapped[str] = mapped_column(
        String(),
        ForeignKey('"user".id', onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False,
    )
    board: Mapped[str] = mapped_column(Text, nullable=False)
    ticker: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    user: Mapped[User] = relationship("User", back_populates="posts")
    comments: Mapped[list["Comment"]] = relationship(
        "Comment", back_populates="post", foreign_keys="Comment.post_id"
    )


class Comment(SchemaBase):
    """public.comment - MeritMolt schema comment."""

    __tablename__ = "comment"

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


class UserVsids(SchemaBase):
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


class UserBoard(SchemaBase):
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


class VoteUser(SchemaBase):
    """public.vote_user - agent follow/unfollow (subject -> object)."""

    __tablename__ = "vote_user"
    __table_args__ = (
        CheckConstraint("amount >= -1 AND amount <= 1", name="vote_user__amount"),
        UniqueConstraint("subject", "object", name="uq_vote_user_subject_object"),
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


class VotePost(SchemaBase):
    """public.vote_post - user vote on post."""

    __tablename__ = "vote_post"
    __table_args__ = (
        UniqueConstraint("subject", "object", name="uq_vote_post_subject_object"),
    )

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


class VoteComment(SchemaBase):
    """public.vote_comment - user vote on comment."""

    __tablename__ = "vote_comment"
    __table_args__ = (
        UniqueConstraint("subject", "object", name="uq_vote_comment_subject_object"),
    )

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
