"""Seed minimal data for integration tests (rank endpoints require agent + post).

Run after MeritMolt is up:
  POSTGRES_PASSWORD=test uv run python scripts/seed_integration_test_data.py

Inserts:
- mb_agent id='any-user' (required by ensure_agent_exists)
- mb_post id='Bpost123' author_id='any-user' (required by ensure_post_exists)
- meritrank_init() to sync graph
"""

from __future__ import annotations

import asyncio
import os
import time

import asyncpg

MAX_RETRIES = 10
RETRY_DELAY_SEC = 2


async def main() -> None:
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = int(os.environ.get("POSTGRES_PORT", "5432"))
    user = os.environ.get("POSTGRES_USER", "postgres")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    db = os.environ.get("POSTGRES_DB", "textlake")

    conn = None
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            conn = await asyncpg.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                database=db,
            )
            break
        except Exception as e:
            last_err = e
            if attempt < MAX_RETRIES - 1:
                print(f"Postgres not ready (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
                time.sleep(RETRY_DELAY_SEC)
            else:
                raise last_err from last_err

    assert conn is not None
    try:
        await conn.execute("""
            INSERT INTO mb_agent (id, name, raw_json, first_seen_at, last_seen_at)
            VALUES ('any-user', 'any-user', '{}', NOW(), NOW())
            ON CONFLICT (id) DO NOTHING
            """)
        await conn.execute("""
            INSERT INTO mb_post (id, author_id, raw_json, first_seen_at, last_seen_at)
            VALUES ('Bpost123', 'any-user', '{}', NOW(), NOW())
            ON CONFLICT (id) DO NOTHING
            """)
        await conn.execute("SELECT meritrank_init()")
        print(
            "Seeded integration test data (any-user, Bpost123) and ran meritrank_init()"
        )
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
