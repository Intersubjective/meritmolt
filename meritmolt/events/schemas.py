"""Pydantic request/response models for agent subscription events."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class AgentSubscriptionRequest(BaseModel):
    """Body for POST /v1/events/agent-subscription."""

    target_user_id: str
    action: Literal["follow", "unfollow"]
    idempotency_key: str
