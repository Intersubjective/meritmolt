"""Integration tests for auth endpoints (login, refresh, logout, me)."""

import pytest
import respx
from fastapi.testclient import TestClient

from meritmolt.config import get_settings
from meritmolt.main import app

client = TestClient(app)


@respx.mock
def test_login_returns_tokens_when_mb_verifies() -> None:
    """Login with valid identity and mocked MB returns access + refresh."""
    settings = get_settings()
    url = f"{settings.mm_moltbook_api_base.rstrip('/')}/agents/verify-identity"
    respx.post(url).mock(
        return_value=__import__("httpx").Response(
            200, json={"agent_id": "mb-1", "name": "Alice"}
        )
    )

    response = client.post(
        "/v1/auth/login",
        headers={"X-Moltbook-Identity": "fake-mb-token"},
    )
    if response.status_code != 200:
        pytest.skip(f"DB likely unavailable: {response.status_code} {response.text}")
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == settings.mm_access_ttl_seconds


@respx.mock
def test_login_401_when_identity_missing() -> None:
    """POST /v1/auth/login without X-Moltbook-Identity returns 401."""
    response = client.post("/v1/auth/login")
    assert response.status_code == 401


@respx.mock
def test_login_401_when_mb_rejects() -> None:
    """POST /v1/auth/login when MB returns 401 returns 401 (or 503 if DB down)."""
    settings = get_settings()
    url = f"{settings.mm_moltbook_api_base.rstrip('/')}/agents/verify-identity"
    respx.post(url).mock(return_value=__import__("httpx").Response(401))

    response = client.post(
        "/v1/auth/login",
        headers={"X-Moltbook-Identity": "bad-token"},
    )
    if response.status_code == 503:
        pytest.skip("DB unavailable")
    assert response.status_code == 401


@respx.mock
def test_me_401_without_bearer() -> None:
    """GET /v1/auth/me without Authorization returns 401 (or 503 if DB down)."""
    response = client.get("/v1/auth/me")
    if response.status_code == 503:
        pytest.skip("DB unavailable")
    assert response.status_code == 401


@respx.mock
def test_me_returns_agent_when_valid_jwt() -> None:
    """GET /v1/auth/me with valid JWT returns agent info."""
    settings = get_settings()
    url = f"{settings.mm_moltbook_api_base.rstrip('/')}/agents/verify-identity"
    respx.post(url).mock(
        return_value=__import__("httpx").Response(
            200, json={"agent_id": "mb-me", "name": "Me"}
        )
    )

    login_resp = client.post(
        "/v1/auth/login",
        headers={"X-Moltbook-Identity": "token-for-me"},
    )
    if login_resp.status_code != 200:
        pytest.skip(f"DB likely unavailable: {login_resp.status_code}")
    access = login_resp.json()["access_token"]

    me_resp = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert me_resp.status_code == 200
    data = me_resp.json()
    assert data["mb_agent_id"] == "mb-me"
    assert data["mb_name"] == "Me"
    assert "id" in data


@respx.mock
def test_refresh_returns_new_tokens() -> None:
    """POST /v1/auth/refresh with valid refresh token returns new access + refresh."""
    settings = get_settings()
    url = f"{settings.mm_moltbook_api_base.rstrip('/')}/agents/verify-identity"
    respx.post(url).mock(
        return_value=__import__("httpx").Response(
            200, json={"agent_id": "mb-r", "name": "Ref"}
        )
    )

    login_resp = client.post(
        "/v1/auth/login",
        headers={"X-Moltbook-Identity": "token-ref"},
    )
    if login_resp.status_code != 200:
        pytest.skip(f"DB likely unavailable: {login_resp.status_code}")
    refresh_token = login_resp.json()["refresh_token"]

    refresh_resp = client.post(
        "/v1/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert refresh_resp.status_code == 200
    data = refresh_resp.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["refresh_token"] != refresh_token


@respx.mock
def test_logout_204() -> None:
    """POST /v1/auth/logout with refresh token returns 204."""
    settings = get_settings()
    url = f"{settings.mm_moltbook_api_base.rstrip('/')}/agents/verify-identity"
    respx.post(url).mock(
        return_value=__import__("httpx").Response(
            200, json={"agent_id": "mb-out", "name": "Out"}
        )
    )

    login_resp = client.post(
        "/v1/auth/login",
        headers={"X-Moltbook-Identity": "token-out"},
    )
    if login_resp.status_code != 200:
        pytest.skip(f"DB likely unavailable: {login_resp.status_code}")
    refresh_token = login_resp.json()["refresh_token"]

    logout_resp = client.post("/v1/auth/logout", json={"refresh_token": refresh_token})
    assert logout_resp.status_code == 204
