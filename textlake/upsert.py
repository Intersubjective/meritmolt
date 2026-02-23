"""Enrichment-only upserts: COALESCE for partial payloads, raw_json strategy."""

from __future__ import annotations

from typing import Any, TypeVar

from sqlalchemy import case, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from textlake.models.base import TextLakeBase
from textlake.models.entities import MbAgent, MbComment, MbPost, MbSubmolt

_T = TypeVar("_T", bound=TextLakeBase)


async def _enrichment_upsert(
    session: AsyncSession,
    table: type[_T],
    values: dict[str, Any],
    pk_columns: list[str],
    enrichment_columns: list[str],
    *,
    raw_json_column: str = "raw_json",
    is_authoritative: bool = False,
) -> None:
    """Execute INSERT ... ON CONFLICT DO UPDATE with enrichment-only semantics.
    Caller must await session.commit() or run in a transaction.
    """
    stmt = pg_insert(table).values(**values)
    excluded = stmt.excluded
    tbl = table.__table__
    set_map: dict[Any, Any] = {
        tbl.c["last_seen_at"]: func.now(),
        tbl.c["first_seen_at"]: func.coalesce(tbl.c["first_seen_at"], func.now()),
    }
    for col_name in enrichment_columns:
        if col_name in ("first_seen_at", "last_seen_at", raw_json_column):
            continue
        if col_name not in tbl.c:
            continue
        set_map[tbl.c[col_name]] = func.coalesce(excluded[col_name], tbl.c[col_name])
    if raw_json_column in tbl.c:
        if is_authoritative:
            set_map[tbl.c[raw_json_column]] = excluded[raw_json_column]
        else:
            set_map[tbl.c[raw_json_column]] = case(
                (tbl.c[raw_json_column].is_(None), excluded[raw_json_column]),
                else_=tbl.c[raw_json_column],
            )
    index_elements = [tbl.c[name] for name in pk_columns]
    stmt = stmt.on_conflict_do_update(
        index_elements=index_elements,
        set_=set_map,
    )
    await session.execute(stmt)


# Column sets for each entity (enrichment = never overwrite non-null with null)

MB_AGENT_ENRICHMENT = [
    "name",
    "description",
    "created_at_src",
    "karma",
    "is_claimed",
    "is_human",
    "raw_json",
    "first_seen_at",
    "last_seen_at",
]

MB_SUBMOLT_ENRICHMENT = [
    "name",
    "display_name",
    "description",
    "created_at_src",
    "raw_json",
    "first_seen_at",
    "last_seen_at",
]

MB_POST_ENRICHMENT = [
    "submolt_name",
    "submolt_id",
    "author_name",
    "author_id",
    "title",
    "content",
    "url",
    "created_at_src",
    "updated_at_src",
    "upvotes",
    "downvotes",
    "comment_count",
    "raw_json",
    "first_seen_at",
    "last_seen_at",
]

MB_COMMENT_ENRICHMENT = [
    "post_id",
    "parent_id",
    "author_name",
    "author_id",
    "content",
    "created_at_src",
    "upvotes",
    "downvotes",
    "raw_json",
    "first_seen_at",
    "last_seen_at",
]


async def upsert_agent(
    session: AsyncSession,
    values: dict[str, Any],
    *,
    is_authoritative: bool = False,
) -> None:
    """Upsert mb_agent with enrichment-only semantics."""
    await _enrichment_upsert(
        session,
        MbAgent,
        values,
        ["id"],
        MB_AGENT_ENRICHMENT,
        is_authoritative=is_authoritative,
    )


async def upsert_submolt(
    session: AsyncSession,
    values: dict[str, Any],
    *,
    is_authoritative: bool = False,
) -> None:
    """Upsert mb_submolt with enrichment-only semantics."""
    await _enrichment_upsert(
        session,
        MbSubmolt,
        values,
        ["id"],
        MB_SUBMOLT_ENRICHMENT,
        is_authoritative=is_authoritative,
    )


async def upsert_post(
    session: AsyncSession,
    values: dict[str, Any],
    *,
    is_authoritative: bool = False,
) -> None:
    """Upsert mb_post with enrichment-only semantics."""
    await _enrichment_upsert(
        session,
        MbPost,
        values,
        ["id"],
        MB_POST_ENRICHMENT,
        is_authoritative=is_authoritative,
    )


async def upsert_comment(
    session: AsyncSession,
    values: dict[str, Any],
    *,
    is_authoritative: bool = False,
) -> None:
    """Upsert mb_comment with enrichment-only semantics."""
    await _enrichment_upsert(
        session,
        MbComment,
        values,
        ["id"],
        MB_COMMENT_ENRICHMENT,
        is_authoritative=is_authoritative,
    )
