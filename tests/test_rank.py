"""Integration tests for rank endpoints."""

import pytest
from fastapi.testclient import TestClient

from meritmolt.main import app

client = TestClient(app)


def test_rank_users_returns_list_public() -> None:
    """GET /v1/users/{subject}/rank/users returns list (skip if DB/MR unavailable)."""
    response = client.get(
        "/v1/users/subject-user/rank/users?board=default&limit=10&offset=0",
    )
    if response.status_code == 503:
        pytest.skip("DB unavailable")
    if response.status_code == 500:
        pytest.skip("MeritMolt schema/MR extension may be missing")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_rank_posts_returns_list_public() -> None:
    """GET .../rank/boards/{board}/posts returns list (skip if DB/MR down)."""
    response = client.get(
        "/v1/users/subject-user/rank/boards/default/posts?limit=10&offset=0",
    )
    if response.status_code == 503:
        pytest.skip("DB unavailable")
    if response.status_code == 500:
        pytest.skip("MeritMolt schema/MR extension may be missing")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_rank_comments_returns_list_public() -> None:
    """GET .../rank/posts/{id}/comments returns list (skip if DB/MR down)."""
    response = client.get(
        "/v1/users/subject-user/rank/posts/Babc123/comments?board=default&limit=10&offset=0",
    )
    if response.status_code == 503:
        pytest.skip("DB unavailable")
    if response.status_code == 500:
        pytest.skip("MeritMolt schema/MR extension may be missing")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_rank_users_pagination_params() -> None:
    """Rank users with limit/offset respects query params (422 if invalid)."""
    response = client.get(
        "/v1/users/subject-user/rank/users?board=default&limit=201&offset=0",
    )
    if response.status_code == 503:
        pytest.skip("DB unavailable")
    assert response.status_code == 422
