"""Pytest fixtures and env for MeritMolt tests."""

import json
import os

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _generate_es256_keypair() -> tuple[str, str]:
    """Return (private_pem, public_pem) for ES256."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return (private_pem, public_pem)


# Set env before any meritmolt import so get_settings() sees them
_private_pem, _public_pem = _generate_es256_keypair()
os.environ.setdefault("MM_MOLTBOOK_APP_KEY", "test-app-key")
os.environ.setdefault(
    "MM_JWT_PRIVATE_KEYS",
    json.dumps({"default": _private_pem}),
)
os.environ.setdefault(
    "MM_JWT_PUBLIC_KEYS",
    json.dumps({"default": _public_pem}),
)
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "")
os.environ.setdefault("POSTGRES_DB", "postgres")


# Clear lru_cache so tests get fresh settings with the env we set
def _clear_settings_cache() -> None:
    from meritmolt.config import get_settings

    get_settings.cache_clear()


@pytest.fixture(scope="session", autouse=True)
def _env_and_cache() -> None:
    _clear_settings_cache()
    yield
    _clear_settings_cache()
