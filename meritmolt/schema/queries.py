"""Async helpers wrapping raw SQL calls to MeritMolt schema score/ranking functions."""

from __future__ import annotations

from typing import TypedDict, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class MutualScoreRow(TypedDict):
    """Row from user/post/comment_get_scores, rating, my_field."""

    src: str
    dst: str
    src_score: float
    dst_score: float


async def get_user_scores(
    session: AsyncSession,
    user_id: str,
    actor_id: str,
    board: str,
) -> list[MutualScoreRow]:
    """Return mutual_score rows for a user relative to actor in board context."""
    result = await session.execute(
        text("""
            SELECT * FROM user_get_scores(
                (SELECT a FROM public.mb_agent a WHERE a.id = :user_id),
                :actor_id, :board)
        """),
        {"user_id": user_id, "actor_id": actor_id, "board": board},
    )
    return [cast(MutualScoreRow, dict(r._mapping)) for r in result]


async def get_post_scores(
    session: AsyncSession,
    post_id: str,
    actor_id: str,
    board: str,
) -> list[MutualScoreRow]:
    """Return mutual_score rows for a post relative to actor in board context."""
    result = await session.execute(
        text("""
            SELECT * FROM post_get_scores(
                (SELECT p FROM public.mb_post p WHERE p.id = :post_id),
                :actor_id, :board)
        """),
        {"post_id": post_id, "actor_id": actor_id, "board": board},
    )
    return [cast(MutualScoreRow, dict(r._mapping)) for r in result]


async def get_comment_scores(
    session: AsyncSession,
    comment_id: str,
    actor_id: str,
    board: str,
) -> list[MutualScoreRow]:
    """Return mutual_score rows for a comment relative to actor in board context."""
    result = await session.execute(
        text("""
            SELECT * FROM comment_get_scores(
                (SELECT c FROM public.mb_comment c WHERE c.id = :comment_id),
                :actor_id, :board)
        """),
        {"comment_id": comment_id, "actor_id": actor_id, "board": board},
    )
    return [cast(MutualScoreRow, dict(r._mapping)) for r in result]


async def get_user_ranking(
    session: AsyncSession,
    board: str,
    actor_id: str,
    limit: int,
    offset: int,
) -> list[MutualScoreRow]:
    """Return ranked users (mutual_score) for board, ordered by src_score DESC."""
    result = await session.execute(
        text("""
            SELECT * FROM rating(:board, :actor_id)
            ORDER BY src_score DESC
            LIMIT :limit OFFSET :offset
        """),
        {"board": board, "actor_id": actor_id, "limit": limit, "offset": offset},
    )
    return [cast(MutualScoreRow, dict(r._mapping)) for r in result]


async def get_post_ranking(
    session: AsyncSession,
    board: str,
    actor_id: str,
    limit: int,
    offset: int,
) -> list[MutualScoreRow]:
    """Return ranked posts (mutual_score) for board via my_field, src_score DESC."""
    result = await session.execute(
        text("""
            SELECT * FROM my_field(:board, :actor_id)
            ORDER BY src_score DESC
            LIMIT :limit OFFSET :offset
        """),
        {"board": board, "actor_id": actor_id, "limit": limit, "offset": offset},
    )
    return [cast(MutualScoreRow, dict(r._mapping)) for r in result]


class CommentRankRow(TypedDict):
    """Row from ranked comments for a post."""

    id: str
    src_score: float
    dst_score: float


async def get_comment_ranking(
    session: AsyncSession,
    post_id: str,
    board: str,
    actor_id: str,
    limit: int,
    offset: int,
) -> list[CommentRankRow]:
    """Return ranked comments for a post (id, scores), ordered by src_score DESC."""
    result = await session.execute(
        text("""
            SELECT c.id, ms.src_score, ms.dst_score
            FROM public.mb_comment c
            JOIN LATERAL comment_get_scores(c, :actor_id, :board) ms ON TRUE
            WHERE c.post_id = :post_id
            ORDER BY ms.src_score DESC
            LIMIT :limit OFFSET :offset
        """),
        {
            "post_id": post_id,
            "board": board,
            "actor_id": actor_id,
            "limit": limit,
            "offset": offset,
        },
    )
    return [cast(CommentRankRow, dict(r._mapping)) for r in result]
