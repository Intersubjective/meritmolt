"""MR score API: GET /v1/scores/users, posts, comments."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from meritmolt.auth.dependencies import get_current_agent, get_db_session
from meritmolt.database import MmAgent
from meritmolt.schemas import MutualScore
from meritmolt.tentura import queries
from meritmolt.tentura.queries import MutualScoreRow

router = APIRouter(prefix="/v1/scores", tags=["scores"])


def _to_mutual_scores(rows: list[MutualScoreRow]) -> list[MutualScore]:
    return [MutualScore(**r) for r in rows]


@router.get("/users/{user_id}", response_model=list[MutualScore])
async def get_user_scores(
    user_id: str,
    board: str,
    agent: MmAgent = Depends(get_current_agent),
    session: AsyncSession = Depends(get_db_session),
) -> list[MutualScore]:
    """Return MR mutual_score rows for user relative to actor in board context."""
    rows = await queries.get_user_scores(session, user_id, agent.mb_agent_id, board)
    return _to_mutual_scores(rows)


@router.get("/posts/{post_id}", response_model=list[MutualScore])
async def get_post_scores(
    post_id: str,
    board: str,
    agent: MmAgent = Depends(get_current_agent),
    session: AsyncSession = Depends(get_db_session),
) -> list[MutualScore]:
    """Return MR mutual_score rows for post relative to actor in board context."""
    rows = await queries.get_post_scores(session, post_id, agent.mb_agent_id, board)
    return _to_mutual_scores(rows)


@router.get("/comments/{comment_id}", response_model=list[MutualScore])
async def get_comment_scores(
    comment_id: str,
    board: str,
    agent: MmAgent = Depends(get_current_agent),
    session: AsyncSession = Depends(get_db_session),
) -> list[MutualScore]:
    """Return MR mutual_score rows for comment relative to actor in board context."""
    rows = await queries.get_comment_scores(
        session, comment_id, agent.mb_agent_id, board
    )
    return _to_mutual_scores(rows)
