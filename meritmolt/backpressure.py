"""Backpressure: concurrency semaphores and request deadline (pure ASGI middleware)."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from meritmolt.config import Settings
from meritmolt.middleware_utils import send_json_response
from meritmolt.ratelimit import RouteGroup

logger = logging.getLogger(__name__)


class ConcurrencyGuard:
    """Global and per-route-group semaphores; try_acquire returns False when full."""

    def __init__(self, settings: Settings) -> None:
        self._global_sem = asyncio.Semaphore(settings.mm_bp_global_max_concurrent)
        self._group_sems: dict[RouteGroup, asyncio.Semaphore] = {
            RouteGroup.AUTH_LOGIN: asyncio.Semaphore(
                settings.mm_bp_auth_max_concurrent
            ),
            RouteGroup.AUTH_REFRESH: asyncio.Semaphore(
                settings.mm_bp_auth_max_concurrent
            ),
            RouteGroup.WRITES: asyncio.Semaphore(settings.mm_bp_writes_max_concurrent),
            RouteGroup.READS: asyncio.Semaphore(settings.mm_bp_reads_max_concurrent),
        }

    async def try_acquire(self, group: RouteGroup) -> bool:
        """Acquire global and group semaphore (non-EXEMPT). Return False when full."""
        try:
            await asyncio.wait_for(self._global_sem.acquire(), timeout=1.0)
        except asyncio.TimeoutError:
            return False
        if group == RouteGroup.EXEMPT:
            return True
        sem = self._group_sems.get(group)
        if not sem:
            return True
        try:
            await asyncio.wait_for(sem.acquire(), timeout=1.0)
        except asyncio.TimeoutError:
            self._global_sem.release()
            return False
        return True

    def release(self, group: RouteGroup) -> None:
        """Release in reverse order of acquire."""
        if group != RouteGroup.EXEMPT:
            sem = self._group_sems.get(group)
            if sem:
                sem.release()
        self._global_sem.release()


def _get_request_id_from_scope(scope: dict[str, Any]) -> str:
    raw_headers = scope.get("headers") or []
    for raw_name, raw_value in raw_headers:
        if raw_name.lower() == b"x-request-id":
            return raw_value.decode("latin-1").strip() or str(uuid.uuid4())
    return str(uuid.uuid4())


class BackpressureMiddleware:
    """Pure ASGI backpressure: request ID, concurrency limit, and deadline for reads."""

    def __init__(self, app: Any, settings: Settings) -> None:
        self._app = app
        self._settings = settings
        self._guard = ConcurrencyGuard(settings)

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request_id = _get_request_id_from_scope(scope)
        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["request_id"] = request_id

        path = scope.get("path") or "/"
        group = RouteGroup.classify(path)

        if not await self._guard.try_acquire(group):
            logger.warning(
                "backpressure_saturation route_group=%s request_id=%s",
                group.value,
                request_id,
            )
            await send_json_response(
                send,
                503,
                {
                    "error": "overloaded",
                    "detail": "Server at capacity; try again later",
                    "retry_after": 60.0,
                    "request_id": request_id,
                },
                60.0,
            )
            return

        try:
            if group == RouteGroup.READS:
                deadline_sec = self._settings.mm_bp_request_deadline_seconds
                try:
                    await asyncio.wait_for(
                        self._app(scope, receive, send),
                        timeout=deadline_sec,
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "deadline_exceeded route_group=reads request_id=%s",
                        request_id,
                    )
                    await send_json_response(
                        send,
                        503,
                        {
                            "error": "deadline_exceeded",
                            "detail": "Request timed out",
                            "retry_after": min(60.0, deadline_sec),
                            "request_id": request_id,
                        },
                        deadline_sec,
                    )
            else:
                await self._app(scope, receive, send)
        finally:
            self._guard.release(group)
