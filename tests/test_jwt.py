"""Unit tests for JWT create/decode (no DB)."""

import uuid

import pytest

from meritmolt.auth.jwt import create_access_token, decode_access_token
from meritmolt.config import get_settings


class _MockAgent:
    """Minimal agent-like object for JWT tests."""

    def __init__(self, id: uuid.UUID, mb_agent_id: str, mb_name: str) -> None:
        self.id = id
        self.mb_agent_id = mb_agent_id
        self.mb_name = mb_name


def test_create_and_decode_access_token_round_trip() -> None:
    """create_access_token then decode returns same sub and custom claims."""
    settings = get_settings()
    agent_id = uuid.uuid4()
    agent = _MockAgent(id=agent_id, mb_agent_id="mb-123", mb_name="Test Agent")

    token = create_access_token(agent, settings)
    assert isinstance(token, str)
    assert len(token) > 0

    payload = decode_access_token(token, settings)
    assert payload["sub"] == str(agent_id)
    assert payload["mb_agent_id"] == "mb-123"
    assert payload["mb_name"] == "Test Agent"
    assert payload["iss"] == "meritmolt"
    assert payload["aud"] == "meritmolt-api"
    assert "exp" in payload
    assert "iat" in payload
    assert "nbf" in payload
    assert "jti" in payload


def test_decode_invalid_token_raises() -> None:
    """decode_access_token with bad token raises HTTPException."""
    from fastapi import HTTPException

    settings = get_settings()
    with pytest.raises(HTTPException) as exc_info:
        decode_access_token("not.a.jwt", settings)
    assert exc_info.value.status_code == 401
