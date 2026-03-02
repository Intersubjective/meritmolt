# Part 3 Design: Moltbook TextLake Crawler

**Note:** TextLake now shares the same database as MeritMolt (single DB `textlake`). Alembic migrations for the textlake schema have been removed; tables are created at startup via `TextLakeBase.metadata.create_all`. The crawler and MeritMolt both connect to the same DB.

---

This document records the main design decisions and reasons for the Moltbook TextLake Crawler: a separate process that continuously ingests Moltbook text objects (agents, submolts, posts, comments) and evolving metrics into a dedicated “text lake” Postgres database for use by MeritMolt and other services.

---

## 1. Separate package and database (textlake/ + DB `textlake`)

**Decision:** Add a top-level Python package `textlake/` beside `meritmolt/` in the same repo. The crawler connects to the same Postgres instance as MeritMolt but uses a separate database named `textlake`, with its own Alembic migrations and ORM base (`TextLakeBase`). No shared tables or schema coupling with the MeritMolt schema.

**Reasons:**

- **Isolation:** Consumers of the text lake (MeritMolt or others) read stable, normalized tables and time-series snapshots without depending on MR schema or MeritMolt schema triggers.
- **Independent lifecycle:** The crawler can be deployed, migrated, or scaled independently; schema changes to the text lake do not affect MeritMolt’s DB.
- **Shared Postgres ops:** One instance, one backup story; only the database name and migrations differ.

---

## 2. Same Docker image, separate entrypoint

**Decision:** Build a single image from the repo root; the crawler runs as a second Compose service (`textlake`) with `command: ["python", "-m", "textlake"]`. No second Dockerfile or base-image fork.

**Reasons:**

- **Minimal infra:** One build, one set of dependencies (`uv.lock`). Crawler-specific deps (aiolimiter, structlog, alembic) live in the same `pyproject.toml`.
- **Reproducibility:** Same Python and library versions for both services; shared base keeps images smaller and easier to maintain.

---

## 3. Hatchling must list both packages

**Decision:** Configure `[tool.hatch.build.targets.wheel]` with `packages = ["meritmolt", "textlake"]`. Relying on Hatchling’s default (single package matching project name) would not install `textlake/`, so `python -m textlake` would fail in the container.

**Reasons:**

- **Correct install:** `uv sync` installs the project in editable/installed form; the wheel must include both packages so the crawler entrypoint can import `textlake` modules.
- **Explicit over implicit:** Listing packages avoids surprises when adding sibling packages later.

---

## 4. Crawler config and DB bootstrap

**Decision:** Use a pydantic-settings `CrawlerSettings` class with `MB_CRAWLER_API_KEY`, `MB_API_BASE`, rate limit, concurrency, semaphore, and standard `POSTGRES_*` vars; `postgres_db` defaults to `"textlake"`. Bootstrap: connect with raw `asyncpg` to database `postgres`, run `CREATE DATABASE textlake` if missing, then use SQLAlchemy + Alembic against the `textlake` database.

**Reasons:**

- **CREATE DATABASE outside transaction:** Postgres does not allow `CREATE DATABASE` inside a transaction; using asyncpg directly for this one step keeps the rest of the stack on SQLAlchemy/Alembic.
- **Same env pattern as MeritMolt:** Reuse `POSTGRES_HOST`, `POSTGRES_USER`, etc.; only `POSTGRES_DB=textlake` differs for the crawler service, so Compose and ops stay consistent.

---

## 5. ORM: TextLakeBase, entities, time-series, crawl tables

**Decision:** All crawler tables are defined on a single `TextLakeBase` (separate from MeritMolt’s `Base` and MeritMolt schema’s `SchemaBase`). Core entities: `mb_agent`, `mb_submolt`, `mb_post`, `mb_comment` with CITEXT for natural keys and JSONB `raw_json`. Append-only time-series tables: `mb_agent_stats_ts`, `mb_submolt_stats_ts`, `mb_post_stats_ts`, `mb_comment_stats_ts` with composite PK `(ts, entity_id)`. Orchestration: `crawl_task` (work queue), `crawl_state` (cursors and adaptive state), `raw_capture` (optional TTL-pruned request/response log).

**Reasons:**

- **Single source of truth:** Schema lives in the ORM; Alembic migrations are generated or hand-written from it. CITEXT gives case-insensitive natural keys; `raw_json` preserves full API payloads for future fields without schema churn.
- **Partition-ready time-series:** Initial migrations create regular tables with composite PKs; monthly partitioning can be added later without changing the logical model.

---

## 6. Enrichment-only upserts (COALESCE; raw_json by source)

**Decision:** Upserts use `INSERT ... ON CONFLICT DO UPDATE` with `COALESCE(EXCLUDED.col, table.col)` for enrichment columns so existing non-null data is never overwritten by null from partial embedded objects. `last_seen_at` is always set to `now()`; `first_seen_at` is set once via `COALESCE(table.first_seen_at, now())`. For `raw_json`, an `is_authoritative` flag distinguishes dedicated endpoints (e.g. `fetch_post`, `fetch_submolt`) from stubs (e.g. feed or embedded payloads): authoritative overwrites; non-authoritative only set `raw_json` on INSERT and never replace existing richer data.

**Reasons:**

- **Partial objects:** Moltbook often returns partial agent/submolt objects inside posts or comments; naive overwrites would replace richer rows with stubs. COALESCE and authoritative-vs-stub semantics preserve the best available data.
- **Spec alignment:** The crawler spec requires “enrichment-only” updates and a clear raw_json strategy; this implements both without a separate `mb_raw` side table.

---

## 7. Synthetic IDs when API omits stable id

**Decision:** If a payload has no stable id for an agent or submolt, use a synthetic id = `sha256("agent:" + lower(name))` or `sha256("submolt:" + lower(name))` as a hex string. The name is the canonical natural key; any “real id” observed later is stored in `raw_json` for reconciliation but the primary key is never rewritten.

**Reasons:**

- **Stable identity:** Avoids mid-stream identity merges and duplicate rows when the API later adds ids; one row per natural key.
- **Deterministic:** Same name always yields the same id across runs and workers.

---

## 8. HTTP client: Bearer, limiter, semaphore, retries, 401/429 handling

**Decision:** `MoltbookClient` uses a long-lived `httpx.AsyncClient` with `Authorization: Bearer {MB_CRAWLER_API_KEY}`, an `aiolimiter.AsyncLimiter` (baseline 100 req/min, adjustable from `X-RateLimit-*` headers), and an `asyncio.Semaphore` to cap concurrent outbound requests. Tenacity retries on transport errors and 5xx; 429 is not retried indefinitely—the client raises `RateLimitReset(reset_at)` so the worker can set `task.not_before` to the server-indicated reset time. Unexpected 401 on GET raises `TransientAuthError` so the worker backs off that task without killing the process.

**Reasons:**

- **Upstream constraints:** Moltbook rate limits and occasional auth glitches; respecting headers and treating 401 as transient keeps the crawler robust and avoids bans.
- **Backpressure:** Global limiter plus semaphore gives predictable load; workers can pipeline (DB-heavy work releases the semaphore for others to call the API).

---

## 9. DB-backed work queue (no external broker)

**Decision:** A single scheduler loop enqueues recurring tasks into `crawl_task`; N worker loops claim tasks with `SELECT ... FOR UPDATE SKIP LOCKED` where `not_before <= now()` and `locked_until` is null or expired, set a lease (`locked_until = now() + lease`), run the handler, then delete the task on success or update `attempts`, `not_before`, and `last_error` on failure. Dedupe by `dedupe_key = sha256(kind + canonical_json(params))`; enqueue uses `ON CONFLICT (dedupe_key) DO NOTHING`.

**Reasons:**

- **Crash safety:** No external broker; Postgres is the single source of truth. If the process dies, leases expire and tasks become claimable again.
- **Reproducibility and simplicity:** Same DB as the rest of the crawler; no RabbitMQ/Redis; minimal infra.

---

## 10. Worker finalize: backoff, park, 429/401 not_before

**Decision:** On handler failure, increment `attempts` and set `not_before = now() + backoff(attempts)` (exponential with cap). If `attempts >= max_attempts`, park the task by setting `not_before` far in the future (e.g. 30 days) and keep `last_error`. On `TransientAuthError` or `RateLimitReset`, set `not_before` to the server-indicated reset (or a short backoff for 401). Parked tasks can be recovered by a periodic scheduler pass that resets `attempts` and `not_before` after a cooldown so the same logical task can be re-enqueued.

**Reasons:**

- **Spec:** “On 429 set task.not_before to server reset time”; “treat unexpected 401 on GET as transient (backoff that task) not fatal.”
- **Dedupe_key reuse:** Parked tasks still hold their `dedupe_key`; recovery allows recurring tasks to be enqueued again without permanent blockage.

---

## 11. Scheduler: recurring tasks, intervals, raw_capture prune

**Decision:** Scheduler runs in a loop (~30 s); enqueues `list_submolts` (e.g. every 15 min) and `poll_posts_feed` per sort (hot, new, rising, top) every 60 s. Runs parked-task recovery and a raw_capture TTL prune (delete rows older than configured hours). All enqueues use dedupe_key so the same logical task is not duplicated.

**Reasons:**

- **Spec intervals:** “list_submolts … every 10–30 min”; “poll_posts_feed … every 30–90 s” per sort—chosen values sit in that range and keep the lake fresh without hammering the API.
- **Optional raw_capture:** Table is for debugging; TTL prune keeps it bounded.

---

## 12. Handlers and comment completeness

**Decision:** Handlers implement: `list_submolts` (GET /submolts, upsert stubs, enqueue fetch_submolt per name); `fetch_submolt` (GET /submolts/:name, enrich + snapshot); `poll_posts_feed` (GET /posts, upsert stubs and agent/submolt stubs, enqueue fetch_post and fetch_post_comments with bounded budget); `fetch_post` (GET /posts/:id, enrich + snapshot, enqueue fetch_post_comments when comment_count > comments_fetched and last fetch is stale); `fetch_post_comments` (GET /posts/:id/comments, upsert comments, update `mb_post.comments_fetched` and set `comments_truncated` when fetched < expected or API appears capped); optional `search_probe`. No attempt to “finish all comments” for huge threads; incompleteness is exposed via `comments_truncated` and `last_seen_at`.

**Reasons:**

- **Comment APIs may be capped:** Downstream must not assume full graphs; `comments_fetched` and `comments_truncated` document coverage.
- **Stale-page and non-deterministic listing:** Handlers can record state in `crawl_state` for adaptive backoff and stale-page detection; random-offset or varied sort/limit can be enqueued to escape duplicate-heavy pages.

---

## 13. Output contract for consumers

**Decision:** The textlake DB exposes stable tables `mb_agent`, `mb_submolt`, `mb_post`, `mb_comment` and time-series tables. Consumers should use normalized columns for common queries and `raw_json` for new or API-specific fields. They must interpret `comments_truncated` and `last_seen_at` to assess freshness and coverage. No REST API is provided for the text lake; consumers read the DB directly.

**Reasons:**

- **Multiple downstreams:** MeritMolt or other services can query the same DB without schema churn or coupling to the crawler’s task model.
- **Spec:** “Supports multiple downstream projects without schema churn coupling.”

---

## 14. No Caddy route for crawler; no coupling to MR schema

**Decision:** The crawler does not expose HTTP endpoints and is not behind Caddy. It is a headless worker. It does not read or write MeritMolt schema tables; it only uses the `textlake` database.

**Reasons:**

- **Separation of concerns:** Crawler ingests; MeritMolt (and others) consume via DB. No need to expose crawler to the internet or to mix MR and text-lake traffic.
- **Isolation:** Confirms that the text lake is a standalone asset with its own lifecycle.

---

## Summary table

| Area              | Decision                                      | Main reason                                  |
|-------------------|-----------------------------------------------|----------------------------------------------|
| Package/DB         | `textlake/` + DB `textlake`                   | Isolation; independent lifecycle; shared PG   |
| Docker             | Same image, separate command                  | Minimal infra; one build                      |
| Hatchling          | `packages = ["meritmolt", "textlake"]`         | Both packages installed in wheel              |
| Bootstrap         | asyncpg CREATE DATABASE, then Alembic         | CREATE DB outside transaction                 |
| ORM                | TextLakeBase; entities, timeseries, crawl     | Single source of truth; partition-ready       |
| Upserts            | COALESCE enrichment; is_authoritative raw_json | Partial objects; preserve richer data        |
| Synthetic IDs      | sha256(agent\|submolt : name)                 | Stable identity when API omits id             |
| HTTP client        | Bearer, limiter, semaphore, 401/429 handling  | Rate limits; backpressure; spec               |
| Work queue         | crawl_task, FOR UPDATE SKIP LOCKED, dedupe_key | Crash-safe; no broker; reproducible           |
| Worker             | Backoff, park, 429/401 not_before; recovery   | Spec; dedupe_key reuse                        |
| Scheduler          | Recurring tasks, intervals, prune, recovery    | Fresh data; bounded raw_capture               |
| Handlers           | list/fetch submolts, feed, post, comments     | Comment completeness; adaptive state          |
| Consumers          | Read DB; use comments_truncated, last_seen_at | Multiple downstreams; no schema churn         |
| Crawler exposure   | No REST, no Caddy                             | Headless worker; no MR coupling               |
