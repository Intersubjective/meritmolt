"""Minimal tests for the FastAPI app."""

from fastapi.testclient import TestClient

from meritmolt.main import app

client = TestClient(app)


def test_root() -> None:
    """Root endpoint returns status ok."""
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health() -> None:
    """Health endpoint returns status ok."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
