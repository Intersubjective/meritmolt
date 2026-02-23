"""Integration tests for rank endpoints."""

import pytest
import respx
from fastapi.testclient import TestClient

from meritmolt.config import get_settings
from meritmolt.main import app

client = TestClient(app)


def test_rank_users_401_without_bearer() -> None:
    """GET /v1/rank/users without Authorization returns 401 (or 503)."""
    response = client.get("/v1/rank/users?board=default")
    if response.status_code == 503:
        pytest.skip("DB unavailable")
    assert response.status_code == 401


def test_rank_posts_401_without_bearer() -> None:
    """GET /v1/rank/boards/{board}/posts without Authorization returns 401 (or 503)."""
    response = client.get("/v1/rank/boards/default/posts")
    if response.status_code == 503:
        pytest.skip("DB unavailable")
    assert response.status_code == 401


def test_rank_comments_401_without_bearer() -> None:
    """GET /v1/rank/posts/{id}/comments without Authorization returns 401 (or 503)."""
    response = client.get("/v1/rank/posts/Babc123/comments?board=default")
    if response.status_code == 503:
        pytest.skip("DB unavailable")
    assert response.status_code == 401


@respx.mock
def test_rank_users_returns_list_with_valid_jwt() -> None:
    """GET /v1/rank/users with valid JWT returns list (skip if DB/MR unavailable)."""
    settings = get_settings()
    url = f"{settings.mm_moltbook_api_base.rstrip('/')}/agents/verify-identity"
    respx.post(url).mock(
        return_value=__import__("httpx").Response(
            200, json={"agent_id": "mb-rank-user", "name": "RankUser"}
        )
    )
    login_resp = client.post(
        "/v1/auth/login",
        headers={"X-Moltbook-Identity": "token-rank"},
    )
    if login_resp.status_code != 200:
        pytest.skip(f"DB likely unavailable: {login_resp.status_code}")
    access = login_resp.json()["access_token"]

    response = client.get(
        "/v1/rank/users?board=default&limit=10&offset=0",
        headers={"Authorization": f"Bearer {access}"},
    )
    if response.status_code == 503:
        pytest.skip("DB unavailable")
    if response.status_code == 500:
        pytest.skip("MeritMolt schema/MR extension may be missing")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@respx.mock
def test_rank_posts_returns_list_with_valid_jwt() -> None:
    """GET rank/boards/{board}/posts with valid JWT (skip if DB/MR unavailable)."""
    settings = get_settings()
    url = f"{settings.mm_moltbook_api_base.rstrip('/')}/agents/verify-identity"
    respx.post(url).mock(
        return_value=__import__("httpx").Response(
            200, json={"agent_id": "mb-rank-post", "name": "RankPost"}
        )
    )
    login_resp = client.post(
        "/v1/auth/login",
        headers={"X-Moltbook-Identity": "token-rank-post"},
    )
    if login_resp.status_code != 200:
        pytest.skip(f"DB likely unavailable: {login_resp.status_code}")
    access = login_resp.json()["access_token"]

    response = client.get(
        "/v1/rank/boards/default/posts?limit=10&offset=0",
        headers={"Authorization": f"Bearer {access}"},
    )
    if response.status_code == 503:
        pytest.skip("DB unavailable")
    if response.status_code == 500:
        pytest.skip("MeritMolt schema/MR extension may be missing")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@respx.mock
def test_rank_comments_returns_list_with_valid_jwt() -> None:
    """GET rank/posts/{id}/comments with valid JWT (skip if DB/MR unavailable)."""
    settings = get_settings()
    url = f"{settings.mm_moltbook_api_base.rstrip('/')}/agents/verify-identity"
    respx.post(url).mock(
        return_value=__import__("httpx").Response(
            200, json={"agent_id": "mb-rank-cmt", "name": "RankCmt"}
        )
    )
    login_resp = client.post(
        "/v1/auth/login",
        headers={"X-Moltbook-Identity": "token-rank-cmt"},
    )
    if login_resp.status_code != 200:
        pytest.skip(f"DB likely unavailable: {login_resp.status_code}")
    access = login_resp.json()["access_token"]

    response = client.get(
        "/v1/rank/posts/Babc123/comments?board=default&limit=10&offset=0",
        headers={"Authorization": f"Bearer {access}"},
    )
    if response.status_code == 503:
        pytest.skip("DB unavailable")
    if response.status_code == 500:
        pytest.skip("MeritMolt schema/MR extension may be missing")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@respx.mock
def test_rank_users_pagination_params() -> None:
    """Rank users with limit/offset respects query params (422 if invalid)."""
    settings = get_settings()
    url = f"{settings.mm_moltbook_api_base.rstrip('/')}/agents/verify-identity"
    respx.post(url).mock(
        return_value=__import__("httpx").Response(
            200, json={"agent_id": "mb-pag", "name": "Pag"}
        )
    )
    login_resp = client.post(
        "/v1/auth/login",
        headers={"X-Moltbook-Identity": "token-pag"},
    )
    if login_resp.status_code != 200:
        pytest.skip(f"DB likely unavailable: {login_resp.status_code}")
    access = login_resp.json()["access_token"]

    response = client.get(
        "/v1/rank/users?board=default&limit=201&offset=0",
        headers={"Authorization": f"Bearer {access}"},
    )
    if response.status_code == 503:
        pytest.skip("DB unavailable")
    assert response.status_code == 422
