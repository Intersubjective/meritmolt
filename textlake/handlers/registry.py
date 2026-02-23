"""Task kind -> handler registry. Handlers are registered at import time."""

from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from textlake.client import MoltbookClient

Handler = Callable[[AsyncSession, MoltbookClient, dict], Any]
_REGISTRY: dict[str, Handler] = {}


def register(kind: str) -> Callable[[Handler], Handler]:
    """Decorator to register a handler for a task kind."""

    def deco(fn: Handler) -> Handler:
        _REGISTRY[kind] = fn
        return fn

    return deco


def get_handler(kind: str) -> Handler | None:
    """Return the handler for the given kind, or None."""
    return _REGISTRY.get(kind)
