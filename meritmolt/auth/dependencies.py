"""FastAPI dependencies: DB session and current agent from JWT."""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from meritmolt.auth.jwt import decode_access_token
from meritmolt.config import get_settings
from meritmolt.database import MmAgent, async_session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session; commit on success, rollback on exception."""
    if async_session_factory is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_current_agent(
    authorization: Annotated[str | None, Header()] = None,
    session: AsyncSession = Depends(get_db_session),
) -> MmAgent:
    """
    Extract Bearer token, verify JWT, load agent; raise 401 on failure.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    settings = get_settings()
    payload = decode_access_token(token, settings)
    sub = payload.get("sub")
    if not sub or not isinstance(sub, str):
        raise HTTPException(status_code=401, detail="Invalid token claims")

    try:
        agent_id = uuid.UUID(sub)
    except ValueError, TypeError:
        raise HTTPException(status_code=401, detail="Invalid token claims") from None

    agent = await session.get(MmAgent, agent_id)
    if agent is None:
        raise HTTPException(status_code=401, detail="Agent not found")
    return agent
