"""Optional search probe handler for edge discovery."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from textlake.client import MoltbookClient
from textlake.handlers.registry import register


@register("search_probe")
async def handle_search_probe(
    session: AsyncSession,
    client: MoltbookClient,
    params: dict,
) -> None:
    """GET /search?q=...; optional edge discovery; upsert any new entities found."""
    q = params.get("q") or params.get("query")
    if not q:
        return
    limit = params.get("limit", 25)
    data = await client.get("/search", params={"q": q, "limit": limit})
    if not isinstance(data, dict):
        return
    items = data.get("items") or data.get("data") or data.get("results") or []
    if not isinstance(items, list):
        return
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("id") and item.get("title"):
            from textlake.handlers.posts import _post_row
            from textlake.upsert import upsert_post

            row = _post_row(item, is_authoritative=False)
            if row:
                await upsert_post(session, row, is_authoritative=False)
    await session.commit()
