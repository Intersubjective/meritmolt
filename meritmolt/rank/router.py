"""MR ranking API: GET /v1/rank/users, boards/{board}/posts, posts/{id}/comments."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from meritmolt.auth.dependencies import get_current_agent, get_db_session
from meritmolt.database import MmAgent
from meritmolt.schema import queries
from meritmolt.schema.queries import CommentRankRow, MutualScoreRow
from meritmolt.schemas import (
    PAGINATION_LIMIT_DEFAULT,
    PAGINATION_LIMIT_MAX,
    PAGINATION_OFFSET_DEFAULT,
    CommentRank,
    MutualScore,
)

router = APIRouter(prefix="/v1/rank", tags=["rank"])


def _to_mutual_scores(rows: list[MutualScoreRow]) -> list[MutualScore]:
    return [MutualScore(**r) for r in rows]


@router.get("/users", response_model=list[MutualScore])
async def get_ranked_users(
    board: str,
    limit: Annotated[
        int,
        Query(ge=1, le=PAGINATION_LIMIT_MAX, description="Max items to return"),
    ] = PAGINATION_LIMIT_DEFAULT,
    offset: Annotated[
        int,
        Query(ge=0, description="Number of items to skip"),
    ] = PAGINATION_OFFSET_DEFAULT,
    agent: MmAgent = Depends(get_current_agent),
    session: AsyncSession = Depends(get_db_session),
) -> list[MutualScore]:
    """Return ranked users (mutual_score) for board, ordered by src_score DESC."""
    rows = await queries.get_user_ranking(
        session, board, agent.mb_agent_id, limit, offset
    )
    return _to_mutual_scores(rows)


@router.get("/boards/{board}/posts", response_model=list[MutualScore])
async def get_ranked_posts(
    board: str,
    limit: Annotated[
        int,
        Query(ge=1, le=PAGINATION_LIMIT_MAX, description="Max items to return"),
    ] = PAGINATION_LIMIT_DEFAULT,
    offset: Annotated[
        int,
        Query(ge=0, description="Number of items to skip"),
    ] = PAGINATION_OFFSET_DEFAULT,
    agent: MmAgent = Depends(get_current_agent),
    session: AsyncSession = Depends(get_db_session),
) -> list[MutualScore]:
    """Return ranked posts (mutual_score) for board via my_field, src_score DESC."""
    rows = await queries.get_post_ranking(
        session, board, agent.mb_agent_id, limit, offset
    )
    return _to_mutual_scores(rows)


@router.get("/posts/{post_id}/comments", response_model=list[CommentRank])
async def get_ranked_comments(
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
    agent: MmAgent = Depends(get_current_agent),
    session: AsyncSession = Depends(get_db_session),
) -> list[CommentRank]:
    """Return ranked comments for a post (id, scores), ordered by src_score DESC."""
    rows: list[CommentRankRow] = await queries.get_comment_ranking(
        session, post_id, board, agent.mb_agent_id, limit, offset
    )
    return [CommentRank(**r) for r in rows]
