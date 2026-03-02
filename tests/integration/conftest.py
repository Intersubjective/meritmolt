"""Fixtures for integration tests against live MeritMolt (docker compose).

Run full stack (pull from GHCR):  docker compose up -d
Run full stack (build locally):
    docker compose -f compose.yaml -f compose.ci.yaml up -d
Run tests:  uv run pytest tests/integration/ -v -m integration
Or run all: uv run pytest tests/  (integration tests skip if unreachable)
"""

import httpx
import pytest

INTEGRATION_BASE_URL = "http://localhost:8000"
INTEGRATION_TIMEOUT = 10.0


def _meritmolt_reachable() -> bool:
    """Return True if MeritMolt responds at localhost:8000."""
    try:
        with httpx.Client(timeout=2.0) as client:
            r = client.get(f"{INTEGRATION_BASE_URL}/health")
            return r.status_code == 200
    except httpx.ConnectError, httpx.ConnectTimeout:
        return False


@pytest.fixture(scope="module")
def meritmolt_client() -> httpx.Client:
    """HTTP client for MeritMolt. Skips all tests in module if service unreachable."""
    if not _meritmolt_reachable():
        pytest.skip(
            "MeritMolt not reachable at localhost:8000. Run: docker compose up -d"
        )
    return httpx.Client(base_url=INTEGRATION_BASE_URL, timeout=INTEGRATION_TIMEOUT)
