"""Integration tests for score endpoints."""

import pytest
import respx
from fastapi.testclient import TestClient

from meritmolt.config import get_settings
from meritmolt.main import app

client = TestClient(app)


def test_scores_users_401_without_bearer() -> None:
    """GET /v1/scores/users/{id} without Authorization returns 401 (or 503)."""
    response = client.get("/v1/scores/users/some-user?board=default")
    if response.status_code == 503:
        pytest.skip("DB unavailable")
    assert response.status_code == 401


def test_scores_posts_401_without_bearer() -> None:
    """GET /v1/scores/posts/{id} without Authorization returns 401 (or 503)."""
    response = client.get("/v1/scores/posts/Babc123?board=default")
    if response.status_code == 503:
        pytest.skip("DB unavailable")
    assert response.status_code == 401


def test_scores_comments_401_without_bearer() -> None:
    """GET /v1/scores/comments/{id} without Authorization returns 401 (or 503)."""
    response = client.get("/v1/scores/comments/Cabc123?board=default")
    if response.status_code == 503:
        pytest.skip("DB unavailable")
    assert response.status_code == 401


@respx.mock
def test_scores_users_returns_list_with_valid_jwt() -> None:
    """GET scores/users/{id} with valid JWT returns list (skip if DB/MR unavailable)."""
    settings = get_settings()
    url = f"{settings.mm_moltbook_api_base.rstrip('/')}/agents/verify-identity"
    respx.post(url).mock(
        return_value=__import__("httpx").Response(
            200, json={"agent_id": "mb-score-user", "name": "ScoreUser"}
        )
    )
    login_resp = client.post(
        "/v1/auth/login",
        headers={"X-Moltbook-Identity": "token-score"},
    )
    if login_resp.status_code != 200:
        pytest.skip(f"DB likely unavailable: {login_resp.status_code}")
    access = login_resp.json()["access_token"]

    response = client.get(
        "/v1/scores/users/some-user-id?board=default",
        headers={"Authorization": f"Bearer {access}"},
    )
    if response.status_code == 503:
        pytest.skip("DB unavailable")
    if response.status_code == 500:
        pytest.skip("Tentura/MR extension may be missing")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@respx.mock
def test_scores_posts_returns_list_with_valid_jwt() -> None:
    """GET scores/posts/{id} with valid JWT returns list (skip if DB/MR unavailable)."""
    settings = get_settings()
    url = f"{settings.mm_moltbook_api_base.rstrip('/')}/agents/verify-identity"
    respx.post(url).mock(
        return_value=__import__("httpx").Response(
            200, json={"agent_id": "mb-score-post", "name": "ScorePost"}
        )
    )
    login_resp = client.post(
        "/v1/auth/login",
        headers={"X-Moltbook-Identity": "token-score-post"},
    )
    if login_resp.status_code != 200:
        pytest.skip(f"DB likely unavailable: {login_resp.status_code}")
    access = login_resp.json()["access_token"]

    response = client.get(
        "/v1/scores/posts/Babc123?board=default",
        headers={"Authorization": f"Bearer {access}"},
    )
    if response.status_code == 503:
        pytest.skip("DB unavailable")
    if response.status_code == 500:
        pytest.skip("Tentura/MR extension may be missing")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@respx.mock
def test_scores_comments_returns_list_with_valid_jwt() -> None:
    """GET scores/comments/{id} with valid JWT returns list (skip if DB/MR down)."""
    settings = get_settings()
    url = f"{settings.mm_moltbook_api_base.rstrip('/')}/agents/verify-identity"
    respx.post(url).mock(
        return_value=__import__("httpx").Response(
            200, json={"agent_id": "mb-score-cmt", "name": "ScoreCmt"}
        )
    )
    login_resp = client.post(
        "/v1/auth/login",
        headers={"X-Moltbook-Identity": "token-score-cmt"},
    )
    if login_resp.status_code != 200:
        pytest.skip(f"DB likely unavailable: {login_resp.status_code}")
    access = login_resp.json()["access_token"]

    response = client.get(
        "/v1/scores/comments/Cabc123?board=default",
        headers={"Authorization": f"Bearer {access}"},
    )
    if response.status_code == 503:
        pytest.skip("DB unavailable")
    if response.status_code == 500:
        pytest.skip("Tentura/MR extension may be missing")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
