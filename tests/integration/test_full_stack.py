"""Integration tests: MeritMolt starts with full config (postgres, meritrank)."""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.integration
def test_health_ok(meritmolt_client: httpx.Client) -> None:
    """GET /health returns status ok."""
    r = meritmolt_client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.integration
def test_db_connected(meritmolt_client: httpx.Client) -> None:
    """GET /db confirms Postgres connection and init_db completed."""
    r = meritmolt_client.get("/db")
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "ok"
    assert data.get("db") is True


@pytest.mark.integration
def test_rank_users_returns_200(meritmolt_client: httpx.Client) -> None:
    """GET /v1/users/{id}/rank/users returns 200 (MeritRank + schema working)."""
    r = meritmolt_client.get("/v1/users/any-user/rank/users?board=general&limit=5")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.integration
def test_rank_posts_returns_200(meritmolt_client: httpx.Client) -> None:
    """GET /v1/users/{id}/rank/boards/{board}/posts returns 200."""
    r = meritmolt_client.get("/v1/users/any-user/rank/boards/general/posts?limit=5")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.integration
def test_rank_comments_returns_200(meritmolt_client: httpx.Client) -> None:
    """GET /v1/users/{id}/rank/posts/{id}/comments returns 200."""
    r = meritmolt_client.get(
        "/v1/users/any-user/rank/posts/Bpost123/comments?board=general&limit=5"
    )
    assert r.status_code == 200
    assert isinstance(r.json(), list)
