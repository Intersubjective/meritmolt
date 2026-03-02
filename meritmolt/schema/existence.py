"""Entity existence checks for scores/rank API. Raise 404 if missing."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from textlake.models.entities import MbAgent, MbComment, MbPost


async def _ensure_exists(
    session: AsyncSession,
    model: type[Any],
    entity_id: str,
    detail: str,
) -> None:
    result = await session.execute(select(model).where(model.id == entity_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail=detail)


async def ensure_agent_exists(session: AsyncSession, user_id: str) -> None:
    """Raise HTTPException 404 if user (mb_agent) does not exist."""
    await _ensure_exists(session, MbAgent, user_id, "User not found")


async def ensure_post_exists(session: AsyncSession, post_id: str) -> None:
    """Raise HTTPException 404 if post does not exist."""
    await _ensure_exists(session, MbPost, post_id, "Post not found")


async def ensure_comment_exists(session: AsyncSession, comment_id: str) -> None:
    """Raise HTTPException 404 if comment does not exist."""
    await _ensure_exists(session, MbComment, comment_id, "Comment not found")
