"""Shared parsing and mapping utilities for handlers."""

from __future__ import annotations

from datetime import datetime, timezone

from textlake.ids import synthetic_agent_id


def parse_ts(raw: object) -> datetime | None:
    """Parse timestamp from int/float (unix) or ISO8601 string."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(float(raw), tz=timezone.utc)
    if isinstance(raw, str):
        try:
            if "T" in raw or "Z" in raw or "+" in raw:
                return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(
                    timezone.utc
                )
            return None
        except ValueError:
            return None
    return None


def agent_stub(data: dict) -> dict | None:
    """Build mb_agent stub from embedded author (name, username, author_name)."""
    name = (
        data.get("name") or data.get("username") or data.get("author_name") or ""
    ).strip()
    if not name:
        return None
    aid = data.get("id") or data.get("agent_id") or synthetic_agent_id(name)
    if isinstance(aid, dict):
        aid = aid.get("id") or synthetic_agent_id(name)
    return {
        "id": str(aid),
        "name": name,
        "description": data.get("description"),
        "created_at_src": parse_ts(data.get("created_at")),
        "karma": data.get("karma"),
        "is_claimed": data.get("is_claimed"),
        "is_human": data.get("is_human"),
        "raw_json": data,
    }
