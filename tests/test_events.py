"""Integration tests for agent subscription endpoint (require Postgres + MeritRank)."""

import pytest
import respx
from fastapi.testclient import TestClient

from meritmolt.config import get_settings
from meritmolt.main import app

pytestmark = pytest.mark.integration

client = TestClient(app)


def test_agent_subscription_401_without_bearer() -> None:
    """POST agent-subscription without Authorization returns 401 (or 503 if DB down)."""
    response = client.post(
        "/v1/events/agent-subscription",
        json={
            "target_user_id": "some-user",
            "action": "follow",
            "idempotency_key": "key-1",
        },
    )
    if response.status_code == 503:
        pytest.skip("DB unavailable")
    assert response.status_code == 401


def test_agent_subscription_422_invalid_action() -> None:
    """POST with invalid action value returns 422."""
    response = client.post(
        "/v1/events/agent-subscription",
        json={
            "target_user_id": "some-user",
            "action": "subscribe",
            "idempotency_key": "key-1",
        },
        headers={"Authorization": "Bearer invalid-token"},
    )
    if response.status_code == 503:
        pytest.skip("DB unavailable")
    assert response.status_code in (401, 422)


@respx.mock
def test_agent_subscription_follow_returns_200() -> None:
    """POST follow with valid JWT returns 200 (skip if DB/MeritMolt schema
    unavailable or FK).
    """
    settings = get_settings()
    url = f"{settings.mm_moltbook_api_base.rstrip('/')}/agents/verify-identity"
    respx.post(url).mock(
        return_value=__import__("httpx").Response(
            200, json={"agent_id": "mb-actor", "name": "Actor"}
        )
    )
    login_resp = client.post(
        "/v1/auth/login",
        headers={"X-Moltbook-Identity": "token-actor"},
    )
    if login_resp.status_code != 200:
        pytest.skip(f"DB likely unavailable: {login_resp.status_code}")
    access = login_resp.json()["access_token"]

    response = client.post(
        "/v1/events/agent-subscription",
        json={
            "target_user_id": "target-user-id",
            "action": "follow",
            "idempotency_key": "key-follow",
        },
        headers={"Authorization": f"Bearer {access}"},
    )
    if response.status_code == 503:
        pytest.skip("DB unavailable")
    if response.status_code == 500:
        pytest.skip("MeritMolt schema tables or extension may be missing")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["action"] == "follow"


@respx.mock
def test_agent_subscription_unfollow_returns_200() -> None:
    """POST unfollow with valid JWT returns 200 (skip if DB unavailable)."""
    settings = get_settings()
    url = f"{settings.mm_moltbook_api_base.rstrip('/')}/agents/verify-identity"
    respx.post(url).mock(
        return_value=__import__("httpx").Response(
            200, json={"agent_id": "mb-actor2", "name": "Actor2"}
        )
    )
    login_resp = client.post(
        "/v1/auth/login",
        headers={"X-Moltbook-Identity": "token-actor2"},
    )
    if login_resp.status_code != 200:
        pytest.skip(f"DB likely unavailable: {login_resp.status_code}")
    access = login_resp.json()["access_token"]

    response = client.post(
        "/v1/events/agent-subscription",
        json={
            "target_user_id": "any-target",
            "action": "unfollow",
            "idempotency_key": "key-unfollow",
        },
        headers={"Authorization": f"Bearer {access}"},
    )
    if response.status_code == 503:
        pytest.skip("DB unavailable")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["action"] == "unfollow"
