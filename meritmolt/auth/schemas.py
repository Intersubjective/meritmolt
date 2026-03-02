"""Pydantic request/response models for auth endpoints."""

from __future__ import annotations

import uuid

from pydantic import BaseModel


class TokenResponse(BaseModel):
    """Response for POST /v1/auth/login and POST /v1/auth/refresh."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    """Body for POST /v1/auth/refresh."""

    refresh_token: str


class LogoutRequest(BaseModel):
    """Body for POST /v1/auth/logout."""

    refresh_token: str


class AgentInfo(BaseModel):
    """Response for GET /v1/auth/me."""

    id: uuid.UUID
    mb_agent_id: str
    mb_name: str
