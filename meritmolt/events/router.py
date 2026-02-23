"""Agent subscription API: POST /v1/events/agent-subscription."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from meritmolt.auth.dependencies import get_current_agent, get_db_session
from meritmolt.database import MmAgent
from meritmolt.events.schemas import AgentSubscriptionRequest
from meritmolt.tentura.models import VoteUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/events", tags=["events"])


@router.post("/agent-subscription")
async def agent_subscription(
    body: AgentSubscriptionRequest,
    agent: MmAgent = Depends(get_current_agent),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    """
    Record agent follow/unfollow (target_user_id). Actor is taken from JWT.
    follow => INSERT into vote_user with ON CONFLICT DO UPDATE; unfollow => DELETE.
    Triggers notify MeritRank automatically.
    """
    actor_user_id = agent.mb_agent_id
    target = body.target_user_id
    action = body.action
    # Idempotency key accepted for client dedup; not stored (ops are idempotent)
    logger.info(
        "agent_subscription action=%s target=%s idempotency_key=%s",
        action,
        target,
        body.idempotency_key,
    )
    if action == "follow":
        stmt = pg_insert(VoteUser).values(
            subject=actor_user_id,
            object=target,
            amount=1,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["subject", "object"],
            set_={"amount": 1},
        )
        await session.execute(stmt)
    else:
        await session.execute(
            delete(VoteUser).where(
                VoteUser.subject == actor_user_id,
                VoteUser.object == target,
            )
        )
    return {"status": "ok", "action": action}
