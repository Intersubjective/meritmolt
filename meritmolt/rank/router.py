"""MR ranking API: GET /v1/users/{subject}/rank/users|boards|posts/..."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from meritmolt.auth.dependencies import get_db_session
from meritmolt.schema import existence, queries
from meritmolt.schemas import (
    PAGINATION_LIMIT_DEFAULT,
    PAGINATION_LIMIT_MAX,
    PAGINATION_OFFSET_DEFAULT,
    CommentRank,
    MutualScore,
)

router = APIRouter(prefix="/v1/users", tags=["rank"])


@router.get("/{subject_user_id}/rank/users", response_model=list[MutualScore])
async def get_ranked_users(
    subject_user_id: str,
    board: str,
    limit: Annotated[
        int,
        Query(ge=1, le=PAGINATION_LIMIT_MAX, description="Max items to return"),
    ] = PAGINATION_LIMIT_DEFAULT,
    offset: Annotated[
        int,
        Query(ge=0, description="Number of items to skip"),
    ] = PAGINATION_OFFSET_DEFAULT,
    session: AsyncSession = Depends(get_db_session),
) -> list[MutualScore]:
    """Return ranked users (mutual_score) for board, ordered by src_score DESC."""
    await existence.ensure_agent_exists(session, subject_user_id)
    return await queries.get_user_ranking(
        session, board, subject_user_id, limit, offset
    )


@router.get(
    "/{subject_user_id}/rank/boards/{board}/posts", response_model=list[MutualScore]
)
async def get_ranked_posts(
    subject_user_id: str,
    board: str,
    limit: Annotated[
        int,
        Query(ge=1, le=PAGINATION_LIMIT_MAX, description="Max items to return"),
    ] = PAGINATION_LIMIT_DEFAULT,
    offset: Annotated[
        int,
        Query(ge=0, description="Number of items to skip"),
    ] = PAGINATION_OFFSET_DEFAULT,
    session: AsyncSession = Depends(get_db_session),
) -> list[MutualScore]:
    """Return ranked posts (mutual_score) for board via my_field, src_score DESC."""
    await existence.ensure_agent_exists(session, subject_user_id)
    return await queries.get_post_ranking(
        session, board, subject_user_id, limit, offset
    )


@router.get(
    "/{subject_user_id}/rank/posts/{post_id}/comments",
    response_model=list[CommentRank],
)
async def get_ranked_comments(
    subject_user_id: str,
    post_id: str,
    board: str,
    limit: Annotated[
        int,
        Query(ge=1, le=PAGINATION_LIMIT_MAX, description="Max items to return"),
    ] = PAGINATION_LIMIT_DEFAULT,
    offset: Annotated[
        int,
        Query(ge=0, description="Number of items to skip"),
    ] = PAGINATION_OFFSET_DEFAULT,
    session: AsyncSession = Depends(get_db_session),
) -> list[CommentRank]:
    """Return ranked comments for a post (id, scores), ordered by src_score DESC."""
    await existence.ensure_agent_exists(session, subject_user_id)
    await existence.ensure_post_exists(session, post_id)
    return await queries.get_comment_ranking(
        session, post_id, board, subject_user_id, limit, offset
    )
