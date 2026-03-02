"""MR score API: GET /v1/users/{subject}/scores/users|posts|comments/..."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from meritmolt.auth.dependencies import get_db_session
from meritmolt.schema import existence, queries
from meritmolt.schemas import MutualScore

router = APIRouter(prefix="/v1/users", tags=["scores"])


@router.get(
    "/{subject_user_id}/scores/users/{object_user_id}", response_model=list[MutualScore]
)
async def get_user_scores(
    subject_user_id: str,
    object_user_id: str,
    board: str,
    session: AsyncSession = Depends(get_db_session),
) -> list[MutualScore]:
    """Return MR mutual_score rows for user relative to actor in board context."""
    await existence.ensure_agent_exists(session, subject_user_id)
    await existence.ensure_agent_exists(session, object_user_id)
    return await queries.get_user_scores(
        session, object_user_id, subject_user_id, board
    )


@router.get(
    "/{subject_user_id}/scores/posts/{post_id}", response_model=list[MutualScore]
)
async def get_post_scores(
    subject_user_id: str,
    post_id: str,
    board: str,
    session: AsyncSession = Depends(get_db_session),
) -> list[MutualScore]:
    """Return MR mutual_score rows for post relative to actor in board context."""
    await existence.ensure_agent_exists(session, subject_user_id)
    await existence.ensure_post_exists(session, post_id)
    return await queries.get_post_scores(session, post_id, subject_user_id, board)


@router.get(
    "/{subject_user_id}/scores/comments/{comment_id}", response_model=list[MutualScore]
)
async def get_comment_scores(
    subject_user_id: str,
    comment_id: str,
    board: str,
    session: AsyncSession = Depends(get_db_session),
) -> list[MutualScore]:
    """Return MR mutual_score rows for comment relative to actor in board context."""
    await existence.ensure_agent_exists(session, subject_user_id)
    await existence.ensure_comment_exists(session, comment_id)
    return await queries.get_comment_scores(session, comment_id, subject_user_id, board)
