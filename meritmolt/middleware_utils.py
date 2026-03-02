"""Shared ASGI middleware helpers."""

from __future__ import annotations

import json
import math
from typing import Any


async def send_json_response(
    send: Any,
    status: int,
    body: dict[str, Any],
    retry_after: float = 60.0,
) -> None:
    """Send a JSON response with Retry-After header (ASGI send)."""
    payload = json.dumps(body).encode("utf-8")
    retry_after_int = max(1, math.ceil(retry_after))
    headers = [
        (b"content-type", b"application/json"),
        (b"retry-after", str(retry_after_int).encode()),
    ]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": payload})
