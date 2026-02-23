"""Refresh token mint, rotate, revoke; reuse detection."""

from __future__ import annotations

import base64
import os
import uuid
from datetime import datetime, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from meritmolt.config import Settings
from meritmolt.database import MmAgent, MmRefreshToken

_ph = PasswordHasher()


def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _base64url_decode(s: str) -> bytes:
    pad = 4 - len(s) % 4
    if pad != 4:
        s += "=" * pad
    return base64.urlsafe_b64decode(s)


def _hash_secret(secret: bytes) -> str:
    return _ph.hash(secret)


def _verify_secret(hash_str: str, secret: bytes) -> bool:
    try:
        _ph.verify(hash_str, secret)
        return True
    except VerifyMismatchError:
        return False


def _parse_raw_token(raw_token: str) -> tuple[uuid.UUID, bytes] | None:
    """Return (token_id, secret_bytes) or None if format invalid."""
    if "." not in raw_token:
        return None
    prefix, rest = raw_token.split(".", 1)
    try:
        token_id = uuid.UUID(hex=prefix)
        secret = _base64url_decode(rest)
        if len(secret) < 32:
            return None
        return (token_id, secret)
    except ValueError, TypeError:
        return None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def mint_refresh_token(
    session: AsyncSession,
    agent_id: uuid.UUID,
    settings: Settings,
    user_agent: str | None = None,
    ip: str | None = None,
    rotated_from_id: uuid.UUID | None = None,
) -> str:
    """
    Create a new refresh token for the agent; enforce max active per agent.
    Returns raw token string: <token_uuid_hex>.<base64url_secret>.
    """
    now = _utc_now()
    expires_at = datetime.fromtimestamp(
        now.timestamp() + settings.mm_refresh_ttl_seconds,
        tz=timezone.utc,
    )

    # Count active tokens; revoke oldest if at limit
    from sqlalchemy import func as sql_func

    count_result = await session.execute(
        select(sql_func.count(MmRefreshToken.id)).where(
            MmRefreshToken.agent_id == agent_id,
            MmRefreshToken.revoked_at.is_(None),
            MmRefreshToken.expires_at > now,
        )
    )
    count = count_result.scalar_one()
    if count >= settings.mm_refresh_max_active_per_agent:
        # Revoke oldest active token
        oldest = await session.execute(
            select(MmRefreshToken)
            .where(
                MmRefreshToken.agent_id == agent_id,
                MmRefreshToken.revoked_at.is_(None),
            )
            .order_by(MmRefreshToken.created_at.asc())
            .limit(1)
        )
        row = oldest.scalar_one_or_none()
        if row:
            row.revoked_at = now
            await session.flush()

    token_id = uuid.uuid4()
    secret = os.urandom(32)
    token_hash = _hash_secret(secret)

    row = MmRefreshToken(
        id=token_id,
        agent_id=agent_id,
        token_hash=token_hash,
        created_at=now,
        expires_at=expires_at,
        revoked_at=None,
        rotated_from_id=rotated_from_id,
        user_agent=user_agent,
        ip=ip,
    )
    session.add(row)
    await session.flush()

    raw = f"{token_id.hex}.{_base64url_encode(secret)}"
    return raw


async def rotate_refresh_token(
    session: AsyncSession,
    raw_token: str,
    settings: Settings,
    user_agent: str | None = None,
    ip: str | None = None,
) -> tuple[str, MmAgent]:
    """
    Validate refresh token, revoke it, mint a new one, return (new_raw_token, agent).
    On reuse (revoked token presented), revoke all agent tokens and raise 401.
    """
    parsed = _parse_raw_token(raw_token)
    if not parsed:
        raise HTTPException(status_code=401, detail="Invalid refresh token format")
    token_id, secret = parsed

    row = await session.get(MmRefreshToken, token_id)
    if row is None:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    if row.revoked_at is not None:
        # Reuse detected: revoke all tokens for this agent
        await revoke_all_agent_tokens(session, row.agent_id)
        raise HTTPException(
            status_code=401,
            detail="Refresh token reused; all sessions revoked. Re-login via MoltBook.",
        )

    if row.expires_at <= _utc_now():
        raise HTTPException(status_code=401, detail="Refresh token expired")

    if not _verify_secret(row.token_hash, secret):
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    # Revoke current token
    row.revoked_at = _utc_now()
    await session.flush()

    # Load agent for return and for mint
    agent = await session.get(MmAgent, row.agent_id)
    if agent is None:
        raise HTTPException(status_code=401, detail="Agent not found")

    new_raw = await mint_refresh_token(
        session,
        row.agent_id,
        settings,
        user_agent=user_agent,
        ip=ip,
        rotated_from_id=token_id,
    )
    return (new_raw, agent)


async def revoke_token(session: AsyncSession, raw_token: str) -> None:
    """Revoke the refresh token if found."""
    parsed = _parse_raw_token(raw_token)
    if not parsed:
        return
    token_id, _ = parsed
    row = await session.get(MmRefreshToken, token_id)
    if row is not None and row.revoked_at is None:
        row.revoked_at = _utc_now()
        await session.flush()


async def revoke_all_agent_tokens(session: AsyncSession, agent_id: uuid.UUID) -> None:
    """Revoke all active refresh tokens for the agent."""
    now = _utc_now()
    await session.execute(
        update(MmRefreshToken)
        .where(
            MmRefreshToken.agent_id == agent_id,
            MmRefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    await session.flush()
