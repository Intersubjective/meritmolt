"""MoltBook API client: verify identity token."""

from __future__ import annotations

import httpx
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from meritmolt.config import Settings


class MBAgentInfo(BaseModel):
    """Agent info returned by MoltBook verify-identity endpoint."""

    agent_id: str
    name: str


def _should_retry(e: BaseException) -> bool:
    if isinstance(e, httpx.TransportError):
        return True
    if isinstance(e, httpx.HTTPStatusError) and e.response.status_code >= 500:
        return True
    return False


@retry(
    retry=retry_if_exception(_should_retry),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
async def verify_identity(identity_token: str, settings: Settings) -> MBAgentInfo:
    """
    Call MoltBook verify-identity; return agent info or raise.

    Raises:
        fastapi.HTTPException: 401 if token invalid, 502 on MB failure,
        503 if not configured.
    """
    from fastapi import HTTPException

    if not settings.mm_moltbook_app_key:
        raise HTTPException(
            status_code=503,
            detail="MoltBook not configured (MM_MOLTBOOK_APP_KEY missing)",
        )

    url = f"{settings.mm_moltbook_api_base.rstrip('/')}/agents/verify-identity"
    headers = {"X-Moltbook-App-Key": settings.mm_moltbook_app_key}
    body = {"token": identity_token}

    try:
        timeout = settings.mm_http_timeout_seconds
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=body, headers=headers)
    except httpx.TransportError as e:
        raise HTTPException(status_code=502, detail="MoltBook unreachable") from e

    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail="Invalid or expired MoltBook token")

    if resp.status_code >= 500:
        raise HTTPException(
            status_code=502,
            detail=f"MoltBook error: {resp.status_code}",
        ) from None

    resp.raise_for_status()
    data = resp.json()

    # Normalize MB response to agent_id + name (MB may use different keys)
    agent_id = data.get("agent_id") or data.get("id") or data.get("agentId") or ""
    name = data.get("name") or data.get("username") or data.get("display_name") or ""

    if not agent_id:
        raise HTTPException(status_code=502, detail="MoltBook missing agent_id")

    return MBAgentInfo(agent_id=str(agent_id), name=str(name))
