"""Initial schema: CITEXT, mb_*, stats_ts, crawl_task, crawl_state, raw_capture.

Revision ID: 001_initial
Revises:
Create Date: 2025-02-23

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.create_table(
        "mb_agent",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", postgresql.CITEXT(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at_src", sa.DateTime(timezone=True), nullable=True),
        sa.Column("karma", sa.Integer(), nullable=True),
        sa.Column("is_claimed", sa.Boolean(), nullable=True),
        sa.Column("is_human", sa.Boolean(), nullable=True),
        sa.Column("raw_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_mb_agent_name", "mb_agent", ["name"], unique=True)
    op.create_table(
        "mb_submolt",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", postgresql.CITEXT(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at_src", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_mb_submolt_name", "mb_submolt", ["name"], unique=True)
    op.create_table(
        "mb_post",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("submolt_name", postgresql.CITEXT(), nullable=True),
        sa.Column(
            "submolt_id",
            sa.String(64),
            sa.ForeignKey("mb_submolt.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("author_name", postgresql.CITEXT(), nullable=True),
        sa.Column(
            "author_id",
            sa.String(64),
            sa.ForeignKey("mb_agent.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("created_at_src", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at_src", sa.DateTime(timezone=True), nullable=True),
        sa.Column("upvotes", sa.Integer(), nullable=True),
        sa.Column("downvotes", sa.Integer(), nullable=True),
        sa.Column("comment_count", sa.Integer(), nullable=True),
        sa.Column("raw_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("comments_fetched", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "comments_truncated", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column("last_comments_fetch_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_mb_post_submolt_id", "mb_post", ["submolt_id"])
    op.create_index("ix_mb_post_author_id", "mb_post", ["author_id"])
    op.create_table(
        "mb_comment",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "post_id",
            sa.String(64),
            sa.ForeignKey("mb_post.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_id",
            sa.String(64),
            sa.ForeignKey("mb_comment.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("author_name", postgresql.CITEXT(), nullable=True),
        sa.Column(
            "author_id",
            sa.String(64),
            sa.ForeignKey("mb_agent.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at_src", sa.DateTime(timezone=True), nullable=True),
        sa.Column("upvotes", sa.Integer(), nullable=True),
        sa.Column("downvotes", sa.Integer(), nullable=True),
        sa.Column("raw_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_mb_comment_post_id", "mb_comment", ["post_id"])
    op.create_table(
        "mb_agent_stats_ts",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("karma", sa.Integer(), nullable=True),
        sa.Column("follower_count", sa.Integer(), nullable=True),
        sa.Column("following_count", sa.Integer(), nullable=True),
        sa.Column("raw_json", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("ts", "agent_id"),
    )
    op.create_table(
        "mb_submolt_stats_ts",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submolt_id", sa.String(64), nullable=False),
        sa.Column("subscriber_count", sa.Integer(), nullable=True),
        sa.Column("post_count", sa.Integer(), nullable=True),
        sa.Column("raw_json", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("ts", "submolt_id"),
    )
    op.create_table(
        "mb_post_stats_ts",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("post_id", sa.String(64), nullable=False),
        sa.Column("upvotes", sa.Integer(), nullable=True),
        sa.Column("downvotes", sa.Integer(), nullable=True),
        sa.Column("comment_count", sa.Integer(), nullable=True),
        sa.Column("raw_json", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("ts", "post_id"),
    )
    op.create_table(
        "mb_comment_stats_ts",
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("comment_id", sa.String(64), nullable=False),
        sa.Column("upvotes", sa.Integer(), nullable=True),
        sa.Column("downvotes", sa.Integer(), nullable=True),
        sa.Column("raw_json", postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint("ts", "comment_id"),
    )
    op.create_table(
        "crawl_task",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=True),
        sa.Column("dedupe_key", sa.String(64), nullable=True),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("not_before", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="5", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("locked_by", sa.String(64), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_crawl_task_dedupe_key", "crawl_task", ["dedupe_key"], unique=True
    )
    op.create_index(
        "ix_crawl_task_not_before_priority", "crawl_task", ["not_before", "priority"]
    )
    op.create_table(
        "crawl_state",
        sa.Column("key", sa.String(255), primary_key=True),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "raw_capture",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("method", sa.String(16), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_ms", sa.Integer(), nullable=True),
        sa.Column("request_json", postgresql.JSONB(), nullable=True),
        sa.Column("response_json", postgresql.JSONB(), nullable=True),
        sa.Column("headers_json", postgresql.JSONB(), nullable=True),
    )
    op.create_index("ix_raw_capture_fetched_at", "raw_capture", ["fetched_at"])


def downgrade() -> None:
    op.drop_index("ix_raw_capture_fetched_at", "raw_capture")
    op.drop_table("raw_capture")
    op.drop_table("crawl_state")
    op.drop_index("ix_crawl_task_not_before_priority", "crawl_task")
    op.drop_index("ix_crawl_task_dedupe_key", "crawl_task")
    op.drop_table("crawl_task")
    op.drop_table("mb_comment_stats_ts")
    op.drop_table("mb_post_stats_ts")
    op.drop_table("mb_submolt_stats_ts")
    op.drop_table("mb_agent_stats_ts")
    op.drop_index("ix_mb_comment_post_id", "mb_comment")
    op.drop_table("mb_comment")
    op.drop_index("ix_mb_post_author_id", "mb_post")
    op.drop_index("ix_mb_post_submolt_id", "mb_post")
    op.drop_table("mb_post")
    op.drop_index("ix_mb_submolt_name", "mb_submolt")
    op.drop_table("mb_submolt")
    op.drop_index("ix_mb_agent_name", "mb_agent")
    op.drop_table("mb_agent")
    op.execute("DROP EXTENSION IF EXISTS citext")
