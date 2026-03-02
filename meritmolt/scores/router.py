"""MR score API: GET /v1/users/{subject}/scores/users|posts|comments/..."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from meritmolt.auth.dependencies import get_db_session
from meritmolt.schema import queries
from meritmolt.schema.queries import MutualScoreRow
from meritmolt.schemas import MutualScore

router = APIRouter(prefix="/v1/users", tags=["scores"])


def _to_mutual_scores(rows: list[MutualScoreRow]) -> list[MutualScore]:
    return [MutualScore(**r) for r in rows]


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
    rows = await queries.get_user_scores(
        session, object_user_id, subject_user_id, board
    )
    return _to_mutual_scores(rows)


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
    rows = await queries.get_post_scores(session, post_id, subject_user_id, board)
    return _to_mutual_scores(rows)


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
    rows = await queries.get_comment_scores(session, comment_id, subject_user_id, board)
    return _to_mutual_scores(rows)
