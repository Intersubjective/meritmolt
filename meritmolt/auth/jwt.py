"""JWT access tokens: ES256 sign/verify with kid for key rotation."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import jwt
from fastapi import HTTPException

from meritmolt.config import Settings
from meritmolt.database import MmAgent

ISSUER = "meritmolt"
AUDIENCE = "meritmolt-api"
ALGORITHM = "ES256"


def create_access_token(agent: MmAgent, settings: Settings) -> str:
    """Sign and return a JWT access token for the agent."""
    keys = settings.mm_jwt_private_keys
    if not keys:
        raise ValueError("MM_JWT_PRIVATE_KEYS must contain at least one key")
    kid = next(iter(keys))
    private_pem = keys[kid]
    now = datetime.now(timezone.utc)
    exp = now.timestamp() + settings.mm_access_ttl_seconds
    iat = now.timestamp()
    nbf = iat
    payload = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": str(agent.id),
        "exp": exp,
        "iat": iat,
        "nbf": nbf,
        "jti": str(uuid.uuid4()),
        "mb_name": agent.mb_name,
        "mb_agent_id": agent.mb_agent_id,
    }
    return jwt.encode(
        payload,
        private_pem,
        algorithm=ALGORITHM,
        headers={"kid": kid},
    )


def decode_access_token(token: str, settings: Settings) -> dict[str, object]:
    """
    Decode and verify JWT; return claims dict.

    Raises:
        HTTPException: 401 on invalid or expired token.
    """
    keys = settings.mm_jwt_public_keys
    if not keys:
        raise HTTPException(status_code=501, detail="JWT public keys not configured")

    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if not kid or kid not in keys:
            raise HTTPException(status_code=401, detail="Invalid token kid")
        public_pem = keys[kid]
    except jwt.DecodeError:
        raise HTTPException(status_code=401, detail="Invalid token format") from None

    try:
        payload = jwt.decode(
            token,
            public_pem,
            algorithms=[ALGORITHM],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "nbf", "sub"]},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired") from None
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token") from None

    return payload
