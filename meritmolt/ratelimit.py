"""Rate limiting: token-bucket per principal per route group (pure ASGI middleware)."""

from __future__ import annotations

import hashlib
import logging
import math
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, cast

import jwt

from meritmolt.config import Settings

logger = logging.getLogger(__name__)

# Align with meritmolt.auth.jwt for decode
_JWT_ISSUER = "meritmolt"
_JWT_AUDIENCE = "meritmolt-api"
_JWT_ALGORITHM = "ES256"


class RouteGroup(str, Enum):
    """Route group for rate-limit bucket selection."""

    AUTH_LOGIN = "auth_login"
    AUTH_REFRESH = "auth_refresh"
    WRITES = "writes"
    READS = "reads"
    EXEMPT = "exempt"

    @classmethod
    def classify(cls, path: str) -> RouteGroup:
        """Classify path into a route group. Use prefix and exact path matching."""
        if path == "/" or path == "/health" or path == "/db":
            return cls.EXEMPT
        if path == "/v1/auth/login":
            return cls.AUTH_LOGIN
        if path in ("/v1/auth/refresh", "/v1/auth/logout"):
            return cls.AUTH_REFRESH
        if (
            path == "/v1/auth/me"
            or path.startswith("/v1/scores/")
            or path.startswith("/v1/rank/")
        ):
            return cls.READS
        if path.startswith("/v1/events/"):
            return cls.WRITES
        # Other /v1/auth/* (e.g. unknown) treat as auth_refresh for safety
        if path.startswith("/v1/auth/"):
            return cls.AUTH_REFRESH
        return cls.EXEMPT


@dataclass
class TokenBucket:
    """Token bucket: burst capacity and refill rate (tokens per second)."""

    max_tokens: float
    refill_rate: float
    tokens: float = field(default=0.0)
    last_refill: float = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        if self.tokens == 0.0 and self.max_tokens > 0:
            self.tokens = self.max_tokens

    def try_acquire(self) -> tuple[bool, float]:
        """
        Consume one token if available. Returns (allowed, retry_after_seconds).
        retry_after is 0 if allowed, else seconds until one token is available.
        """
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.max_tokens, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True, 0.0
        if self.refill_rate <= 0:
            return False, 60.0
        need = 1 - self.tokens
        retry_after = need / self.refill_rate
        return False, retry_after


class BucketStore:
    """LRU store for token buckets with TTL and max key cap."""

    def __init__(self, max_keys: int, ttl_seconds: float) -> None:
        self._max_keys = max_keys
        self._ttl = ttl_seconds
        self._order: OrderedDict[str, tuple[TokenBucket, float]] = OrderedDict()

    def get_or_create(
        self,
        key: str,
        burst: float,
        refill_rate: float,
    ) -> TokenBucket:
        now = time.monotonic()
        if key in self._order:
            bucket, created = self._order[key]
            if now - created > self._ttl:
                del self._order[key]
            else:
                self._order.move_to_end(key)
                return bucket
        while len(self._order) >= self._max_keys and self._order:
            self._order.popitem(last=False)
        bucket = TokenBucket(max_tokens=burst, refill_rate=refill_rate)
        self._order[key] = (bucket, now)
        return bucket


def extract_jwt_sub(token: str, settings: Settings) -> str | None:
    """
    Decode and verify JWT, return sub claim or None on any error.
    Does not raise; used by rate-limit middleware for key extraction.
    """
    keys = settings.mm_jwt_public_keys
    if not keys:
        return None
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if not kid or kid not in keys:
            return None
        public_pem = keys[kid]
    except jwt.DecodeError:
        return None
    try:
        payload = jwt.decode(
            token,
            public_pem,
            algorithms=[_JWT_ALGORITHM],
            audience=_JWT_AUDIENCE,
            issuer=_JWT_ISSUER,
            options={"require": ["exp", "iat", "nbf", "sub"]},
        )
    except jwt.PyJWTError:
        return None
    sub = payload.get("sub")
    if sub is None:
        return None
    return str(sub)


def _extract_client_ip_from_scope(scope: dict[str, Any]) -> str:
    """Extract client IP from ASGI scope (X-Forwarded-For first hop or client host)."""
    import ipaddress

    headers = scope.get("headers") or []
    xff = None
    for raw_name, raw_value in headers:
        if raw_name.lower() == b"x-forwarded-for":
            xff = raw_value.decode("latin-1").strip()
            break
    if xff:
        first = xff.split(",")[0].strip()
        try:
            ipaddress.ip_address(first)
            return cast(str, first)
        except ValueError:
            pass
    client = scope.get("client")
    if client and isinstance(client, (list, tuple)) and len(client) >= 1:
        return str(client[0])
    return "unknown"


def _get_bearer_token_from_scope(scope: dict[str, Any]) -> str | None:
    """Extract Bearer token from Authorization header in ASGI scope."""
    headers = scope.get("headers") or []
    for raw_name, raw_value in headers:
        if raw_name.lower() == b"authorization":
            value = raw_value.decode("latin-1").strip()
            if value.lower().startswith("bearer "):
                return cast(str, value[7:].strip())
            return None
    return None


def _hash_key_for_log(key: str) -> str:
    """Return a short hash for logging (privacy)."""
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def _build_stores(settings: Settings) -> dict[RouteGroup, BucketStore]:
    """Build one BucketStore per rate-limited route group."""
    max_keys = settings.mm_rl_bucket_max_keys
    ttl = float(settings.mm_rl_bucket_ttl_seconds)
    return {
        RouteGroup.AUTH_LOGIN: BucketStore(max_keys, ttl),
        RouteGroup.AUTH_REFRESH: BucketStore(max_keys, ttl),
        RouteGroup.WRITES: BucketStore(max_keys, ttl),
        RouteGroup.READS: BucketStore(max_keys, ttl),
    }


def _get_bucket_params(group: RouteGroup, settings: Settings) -> tuple[float, float]:
    """Return (burst, refill_rate) for the route group."""
    if group == RouteGroup.AUTH_LOGIN:
        n = settings.mm_rl_auth_login_limit
        return float(n), n / 3600.0
    if group == RouteGroup.AUTH_REFRESH:
        n = settings.mm_rl_auth_refresh_limit
        return float(n), n / 60.0
    if group == RouteGroup.WRITES:
        burst = settings.mm_rl_writes_burst
        sustain = settings.mm_rl_writes_sustain
        return float(burst), sustain / 60.0
    if group == RouteGroup.READS:
        burst = settings.mm_rl_reads_burst
        sustain = settings.mm_rl_reads_sustain
        return float(burst), sustain / 60.0
    return 0.0, 0.0


async def _send_json_response(
    send: Any,
    status: int,
    body: dict[str, Any],
    retry_after: float,
) -> None:
    """Send a JSON response with Retry-After header (ASGI send)."""
    import json

    payload = json.dumps(body).encode("utf-8")
    retry_after_int = max(1, math.ceil(retry_after))
    headers = [
        (b"content-type", b"application/json"),
        (b"retry-after", str(retry_after_int).encode()),
    ]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": payload})


class RateLimitMiddleware:
    """Pure ASGI rate-limit middleware: token bucket per key per route group."""

    def __init__(self, app: Any, settings: Settings) -> None:
        self._app = app
        self._settings = settings
        self._stores = _build_stores(settings)

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        path = scope.get("path") or "/"
        group = RouteGroup.classify(path)
        if group == RouteGroup.EXEMPT:
            await self._app(scope, receive, send)
            return

        request_id = (scope.get("state") or {}).get("request_id") or ""

        if group in (RouteGroup.AUTH_LOGIN, RouteGroup.AUTH_REFRESH):
            key = _extract_client_ip_from_scope(scope)
        else:
            bearer = _get_bearer_token_from_scope(scope)
            sub = extract_jwt_sub(bearer, self._settings) if bearer else None
            key = sub if sub else _extract_client_ip_from_scope(scope)

        store = self._stores[group]
        burst, refill_rate = _get_bucket_params(group, self._settings)
        bucket = store.get_or_create(key, burst, refill_rate)
        allowed, retry_after = bucket.try_acquire()
        if allowed:
            await self._app(scope, receive, send)
            return

        logger.warning(
            "rate_limit_hit key_hash=%s route_group=%s request_id=%s",
            _hash_key_for_log(key),
            group.value,
            request_id,
        )
        body = {
            "error": "rate_limited",
            "detail": f"Rate limit exceeded for route group '{group.value}'",
            "retry_after": retry_after,
            "request_id": request_id,
        }
        await _send_json_response(send, 429, body, retry_after)
