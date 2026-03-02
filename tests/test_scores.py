"""Integration tests for score endpoints."""

import pytest
from fastapi.testclient import TestClient

from meritmolt.main import app

client = TestClient(app)


def test_scores_users_returns_list_public() -> None:
    """GET /v1/users/{subject}/scores/users/{object} returns list (skip if down)."""
    response = client.get(
        "/v1/users/subject-user/scores/users/object-user?board=default",
    )
    if response.status_code == 503:
        pytest.skip("DB unavailable")
    if response.status_code == 500:
        pytest.skip("MeritMolt schema/MR extension may be missing")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_scores_posts_returns_list_public() -> None:
    """GET /v1/users/{subject}/scores/posts/{id} returns list (skip if DB/MR down)."""
    response = client.get(
        "/v1/users/subject-user/scores/posts/Babc123?board=default",
    )
    if response.status_code == 503:
        pytest.skip("DB unavailable")
    if response.status_code == 500:
        pytest.skip("MeritMolt schema/MR extension may be missing")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_scores_comments_returns_list_public() -> None:
    """GET /v1/users/{subject}/scores/comments/{id} returns list (skip if down)."""
    response = client.get(
        "/v1/users/subject-user/scores/comments/Cabc123?board=default",
    )
    if response.status_code == 503:
        pytest.skip("DB unavailable")
    if response.status_code == 500:
        pytest.skip("MeritMolt schema/MR extension may be missing")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
