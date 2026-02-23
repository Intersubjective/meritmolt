"""Auth API: login, refresh, logout, me."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from meritmolt.auth.dependencies import get_current_agent, get_db_session
from meritmolt.auth.jwt import create_access_token
from meritmolt.auth.moltbook import verify_identity
from meritmolt.auth.schemas import (
    AgentInfo,
    LoginResponse,
    LogoutRequest,
    RefreshRequest,
    RefreshResponse,
)
from meritmolt.auth.tokens import mint_refresh_token, revoke_token, rotate_refresh_token
from meritmolt.config import get_settings
from meritmolt.database import MmAgent

router = APIRouter(prefix="/v1/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")


def _require_identity_header(
    x_moltbook_identity: Annotated[
        str | None, Header(alias="X-Moltbook-Identity")
    ] = None,
) -> str:
    """Dependency: require X-Moltbook-Identity header; raise 401 before touching DB."""
    from fastapi import HTTPException

    if not x_moltbook_identity or not x_moltbook_identity.strip():
        raise HTTPException(status_code=401, detail="Missing X-Moltbook-Identity")
    return x_moltbook_identity.strip()


@router.post("/login", response_model=LoginResponse)
async def login(
    request: Request,
    identity_token: str = Depends(_require_identity_header),
    session: AsyncSession = Depends(get_db_session),
) -> LoginResponse:
    """
    Exchange MoltBook identity token for MM access + refresh tokens.
    Header: X-Moltbook-Identity: <mb_identity_token>
    """

    settings = get_settings()
    mb_info = await verify_identity(identity_token, settings)

    # Upsert mm_agents
    stmt = pg_insert(MmAgent).values(
        mb_agent_id=mb_info.agent_id,
        mb_name=mb_info.name,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["mb_agent_id"],
        set_={
            "mb_name": mb_info.name,
            "last_seen_at": func.now(),
        },
    )
    await session.execute(stmt)
    await session.flush()

    # Get the agent row (id) for minting tokens
    result = await session.execute(
        select(MmAgent).where(MmAgent.mb_agent_id == mb_info.agent_id)
    )
    agent = result.scalar_one()

    refresh_raw = await mint_refresh_token(
        session,
        agent.id,
        settings,
        user_agent=_user_agent(request),
        ip=_client_ip(request),
    )
    access = create_access_token(agent, settings)

    return LoginResponse(
        access_token=access,
        refresh_token=refresh_raw,
        token_type="bearer",
        expires_in=settings.mm_access_ttl_seconds,
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(
    request: Request,
    body: RefreshRequest,
    session: AsyncSession = Depends(get_db_session),
) -> RefreshResponse:
    """Rotate refresh token; return new access + refresh tokens."""
    settings = get_settings()
    new_raw, agent = await rotate_refresh_token(
        session,
        body.refresh_token,
        settings,
        user_agent=_user_agent(request),
        ip=_client_ip(request),
    )
    access = create_access_token(agent, settings)
    return RefreshResponse(
        access_token=access,
        refresh_token=new_raw,
        token_type="bearer",
        expires_in=settings.mm_access_ttl_seconds,
    )


@router.post("/logout", status_code=204)
async def logout(
    body: LogoutRequest,
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """Revoke the given refresh token."""
    await revoke_token(session, body.refresh_token)


@router.get("/me", response_model=AgentInfo)
async def me(
    agent: MmAgent = Depends(get_current_agent),
) -> AgentInfo:
    """Return current agent identity from JWT."""
    return AgentInfo(
        id=agent.id,
        mb_agent_id=agent.mb_agent_id,
        mb_name=agent.mb_name,
    )
