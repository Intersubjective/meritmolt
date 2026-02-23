"""Tests for backpressure: ConcurrencyGuard, deadline, middleware."""

from __future__ import annotations

import importlib
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from meritmolt.backpressure import ConcurrencyGuard
from meritmolt.config import Settings, get_settings
from meritmolt.ratelimit import RouteGroup


@patch.dict(
    "os.environ",
    {
        "MM_BP_GLOBAL_MAX_CONCURRENT": "10",
        "MM_BP_READS_MAX_CONCURRENT": "0",
        "MM_BP_WRITES_MAX_CONCURRENT": "10",
        "MM_BP_AUTH_MAX_CONCURRENT": "10",
    },
    clear=False,
)
def test_backpressure_503_when_read_slots_saturated() -> None:
    """When reads semaphore is 0, read request gets 503 overloaded."""
    import respx

    import meritmolt.main as main_mod

    get_settings.cache_clear()
    try:
        importlib.reload(main_mod)
        settings = get_settings()
        assert settings.mm_bp_reads_max_concurrent == 0

        url = f"{settings.mm_moltbook_api_base.rstrip('/')}/agents/verify-identity"
        with respx.mock:
            respx.post(url).mock(
                return_value=__import__("httpx").Response(
                    200, json={"agent_id": "mb-bp", "name": "Bp"}
                )
            )
            c = TestClient(main_mod.app)
            login = c.post(
                "/v1/auth/login",
                headers={"X-Moltbook-Identity": "token-bp"},
            )
            if login.status_code != 200:
                pytest.skip(f"DB likely unavailable: {login.status_code}")
            access = login.json()["access_token"]

            r = c.get("/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
        assert r.status_code == 503
        data = r.json()
        assert data.get("error") == "overloaded"
        assert "retry_after" in data
        assert "request_id" in data
    finally:
        get_settings.cache_clear()
        importlib.reload(main_mod)


def test_concurrency_guard_try_acquire_release() -> None:
    """ConcurrencyGuard try_acquire returns True when capacity available."""
    from unittest.mock import MagicMock

    settings = MagicMock(spec=Settings)
    settings.mm_bp_global_max_concurrent = 100
    settings.mm_bp_reads_max_concurrent = 100
    settings.mm_bp_writes_max_concurrent = 100
    settings.mm_bp_auth_max_concurrent = 100
    guard = ConcurrencyGuard(settings)
    import asyncio

    async def run() -> None:
        ok = await guard.try_acquire(RouteGroup.READS)
        assert ok is True
        guard.release(RouteGroup.READS)

    asyncio.run(run())


@patch.dict(
    "os.environ",
    {"MM_BP_READS_MAX_CONCURRENT": "1", "MM_BP_GLOBAL_MAX_CONCURRENT": "2"},
    clear=False,
)
def test_concurrency_guard_saturation() -> None:
    """When semaphore is saturated, try_acquire returns False."""
    import asyncio

    get_settings.cache_clear()
    try:
        settings = get_settings()
        guard = ConcurrencyGuard(settings)
        assert settings.mm_bp_reads_max_concurrent == 1

        async def run() -> None:
            ok1 = await guard.try_acquire(RouteGroup.READS)
            assert ok1 is True
            ok2 = await guard.try_acquire(RouteGroup.READS)
            assert ok2 is False
            guard.release(RouteGroup.READS)

        asyncio.run(run())
    finally:
        get_settings.cache_clear()
