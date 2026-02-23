"""Tests for rate limiting: TokenBucket, BucketStore, RouteGroup, middleware."""

from __future__ import annotations

import importlib
import time
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from meritmolt.config import get_settings
from meritmolt.ratelimit import (
    BucketStore,
    RouteGroup,
    TokenBucket,
    _hash_key_for_log,
    extract_jwt_sub,
)


def test_token_bucket_burst_then_reject() -> None:
    """Burst allows N requests then rejects."""
    bucket = TokenBucket(max_tokens=3.0, refill_rate=0.0)
    assert bucket.try_acquire() == (True, 0.0)
    assert bucket.try_acquire() == (True, 0.0)
    assert bucket.try_acquire() == (True, 0.0)
    allowed, retry_after = bucket.try_acquire()
    assert allowed is False
    assert retry_after > 0


def test_token_bucket_refill() -> None:
    """After refill time, one more token is available."""
    bucket = TokenBucket(max_tokens=1.0, refill_rate=1.0)
    assert bucket.try_acquire() == (True, 0.0)
    allowed, retry_after = bucket.try_acquire()
    assert allowed is False
    assert 0.9 <= retry_after <= 1.1
    time.sleep(1.1)
    assert bucket.try_acquire() == (True, 0.0)


def test_bucket_store_lru_eviction() -> None:
    """At max_keys, oldest key is evicted."""
    store = BucketStore(max_keys=2, ttl_seconds=3600.0)
    b1 = store.get_or_create("k1", burst=10.0, refill_rate=1.0)
    store.get_or_create("k2", burst=10.0, refill_rate=1.0)
    assert b1.try_acquire() == (True, 0.0)
    store.get_or_create("k3", burst=10.0, refill_rate=1.0)
    assert "k1" not in store._order
    assert "k2" in store._order and "k3" in store._order


def test_bucket_store_ttl_expiry() -> None:
    """After TTL, key gets fresh bucket."""
    store = BucketStore(max_keys=10, ttl_seconds=0.1)
    b1 = store.get_or_create("k1", burst=1.0, refill_rate=0.0)
    b1.try_acquire()
    time.sleep(0.15)
    b2 = store.get_or_create("k1", burst=1.0, refill_rate=0.0)
    allowed, _ = b2.try_acquire()
    assert allowed is True


def test_route_group_classify() -> None:
    """RouteGroup.classify returns correct group for all known paths."""
    assert RouteGroup.classify("/") == RouteGroup.EXEMPT
    assert RouteGroup.classify("/health") == RouteGroup.EXEMPT
    assert RouteGroup.classify("/db") == RouteGroup.EXEMPT
    assert RouteGroup.classify("/v1/auth/login") == RouteGroup.AUTH_LOGIN
    assert RouteGroup.classify("/v1/auth/refresh") == RouteGroup.AUTH_REFRESH
    assert RouteGroup.classify("/v1/auth/logout") == RouteGroup.AUTH_REFRESH
    assert RouteGroup.classify("/v1/auth/me") == RouteGroup.READS
    assert RouteGroup.classify("/v1/events/agent-subscription") == RouteGroup.WRITES
    assert RouteGroup.classify("/v1/scores/users/abc") == RouteGroup.READS
    assert RouteGroup.classify("/v1/rank/users") == RouteGroup.READS
    assert RouteGroup.classify("/v1/auth/other") == RouteGroup.AUTH_REFRESH


def test_extract_jwt_sub_valid() -> None:
    """extract_jwt_sub returns sub for valid token."""
    from meritmolt.auth.jwt import create_access_token
    from meritmolt.database import MmAgent

    settings = get_settings()
    agent = MmAgent(
        id=uuid.uuid4(),
        mb_agent_id="mb-test",
        mb_name="Test",
    )
    token = create_access_token(agent, settings)
    assert extract_jwt_sub(token, settings) == str(agent.id)


def test_extract_jwt_sub_invalid_returns_none() -> None:
    """extract_jwt_sub returns None for invalid or expired token."""
    settings = get_settings()
    assert extract_jwt_sub("bad-token", settings) is None
    assert extract_jwt_sub("", settings) is None


def test_hash_key_for_log() -> None:
    """_hash_key_for_log returns short stable string."""
    h = _hash_key_for_log("127.0.0.1")
    assert len(h) == 12
    assert h == _hash_key_for_log("127.0.0.1")


@patch.dict(
    "os.environ",
    {
        "MM_RL_AUTH_LOGIN_LIMIT": "2",
        "MM_BP_AUTH_MAX_CONCURRENT": "10",
        "MM_BP_GLOBAL_MAX_CONCURRENT": "50",
    },
    clear=False,
)
def test_rate_limit_middleware_429_after_limit() -> None:
    """Exceeding auth/login limit returns 429 with Retry-After."""
    import meritmolt.main as main_mod

    get_settings.cache_clear()
    try:
        importlib.reload(main_mod)
        c = TestClient(main_mod.app)
        for _ in range(2):
            c.post("/v1/auth/login", headers={"X-Moltbook-Identity": "x"})
        r = c.post("/v1/auth/login", headers={"X-Moltbook-Identity": "y"})
        assert r.status_code == 429
        data = r.json()
        assert data.get("error") == "rate_limited"
        assert "retry_after" in data
        assert "request_id" in data
        assert "retry-after" in r.headers
    finally:
        get_settings.cache_clear()
        importlib.reload(main_mod)


def test_exempt_paths_not_limited() -> None:
    """Exempt paths (/, /health) do not get rate limited."""
    from meritmolt.main import app

    c = TestClient(app)
    for _ in range(50):
        r = c.get("/health")
        assert r.status_code == 200
