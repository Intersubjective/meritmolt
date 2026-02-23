# Part 2 Design: MR Read APIs + Agent Subscriptions (ORM Hybrid)

This document records the main design decisions and reasons for MeritMolt Part 2: agent follow/unfollow events, MeritRank score endpoints, and ranked-list endpoints, with the Tentura schema owned as ORM plus DDL applied at startup.

---

## 1. Tentura schema in ORM; triggers/functions as DDL at startup (Option B)

**Decision:** Define all Tentura tables (`user`, `post`, `comment`, `vote_user`, `vote_post`, `vote_comment`, `user_vsids`, `user_board`, `schema_version`) as SQLAlchemy ORM models on a separate `TenturaBase`. Triggers, views, and wrapper functions are not in the ORM; they are applied as idempotent SQL in `init_db()` after `TenturaBase.metadata.create_all`, using constants in `meritmolt/tentura/ddl.py`.

**Reasons:**

- **Single source of truth for tables:** Schema shape lives in `tentura/models.py`; no hand-maintained `schema.sql` for table definitions. Aligns with Part 1’s “ORM creates tables” approach.
- **Battle-tested trigger logic:** Trigger functions are copied verbatim from the existing Tentura dump; only attachment uses `DROP TRIGGER IF EXISTS` + `CREATE TRIGGER` for idempotency. MR plugin functions (`mr_put_edge`, `mr_delete_edge`, etc.) remain untouched and are provided by the Postgres image (e.g. postgres-tentura with pgmer2).
- **Option B over event listeners:** Applying DDL in a single, explicit sequence in `init_db()` is easier to reason about and to re-run (e.g. after image restart) than scattering trigger DDL across SQLAlchemy `event.listen` hooks.

---

## 2. Separate TenturaBase; MM tables after Tentura DDL

**Decision:** Use two declarative bases: `TenturaBase` for Tentura tables, `Base` for MM tables (`mm_agents`, `mm_refresh_tokens`). Startup order: create extension → create Tentura tables → create views → create trigger functions → create triggers → create wrapper functions → create MM tables.

**Reasons:**

- **Clear ownership:** Tentura models are isolated in `meritmolt/tentura/models.py`; MM models stay in `database.py`. Triggers and functions depend on Tentura table names and columns; creating MM tables last avoids any cross-dependency.
- **Extension first:** `CREATE EXTENSION IF NOT EXISTS pgmer2` runs before any table or function that references `mr_*` so the extension is present when triggers and wrappers are created.

---

## 3. Actor from JWT only; mapped to `public."user".id`

**Decision:** All Part 2 endpoints require `Authorization: Bearer <MM access JWT>`. The actor is resolved via `get_current_agent`; `actor_user_id` is `agent.mb_agent_id`, which corresponds to `public."user".id` in the Tentura schema. No actor fields are accepted in request bodies or query parameters.

**Reasons:**

- **Consistency with Part 1:** Same rule as “Actor from JWT only”—prevents impersonation by trusting only the signed access token.
- **Spec alignment:** Part 2 spec states that `actor_user_id` is resolved from the JWT and mapped to `public."user".id`; using `mb_agent_id` implements that mapping.

---

## 4. Agent subscription: ORM for `vote_user`; idempotency key accepted but not stored

**Decision:** `POST /v1/events/agent-subscription` uses the ORM: follow is `pg_insert(VoteUser).values(...).on_conflict_do_update(...)`; unfollow is `delete(VoteUser).where(...)`. The request body includes `idempotency_key`; it is accepted and logged but not persisted. Triggers `vote_user_before_insert` and `notify_meritrank_vote_user_mutation` run on the table and call MR functions automatically.

**Reasons:**

- **No duplicate application logic:** Follow/unfollow semantics are implemented once in the DB (INSERT/DELETE + triggers). The API is a thin wrapper.
- **Natural idempotency:** Follow is idempotent via `ON CONFLICT DO UPDATE`; unfollow is idempotent by key. Storing idempotency keys would add state and complexity without benefit for this use case; the key is still useful for client-side dedup and audit logging.

---

## 5. Score and ranking: raw SQL in query helpers

**Decision:** Calls to Tentura wrapper functions (`user_get_scores`, `post_get_scores`, `comment_get_scores`, `rating`, `my_field`) and the lateral-join query for ranked comments are implemented in `meritmolt/tentura/queries.py` using raw SQL (`text(...)`) and bound parameters. Routers call these helpers and map results to Pydantic `MutualScore` / `CommentRank`. No MR logic is implemented in the application layer.

**Reasons:**

- **ROW-type arguments:** The wrapper functions take composite row types (e.g. `(SELECT u FROM public."user" u WHERE u.id = :user_id)`). Expressing that in the ORM is awkward; raw SQL matches the spec and stays readable.
- **Read-only, spec-defined queries:** All of these are one-off read queries that mirror the spec; keeping them in a small `queries` module avoids ORM overhead and keeps the dependency on MR entirely in SQL and triggers.

---

## 6. Wrapper functions and views in DDL constants

**Decision:** Views (`mutual_score`, `neighbors_score`, `edge`) and wrapper functions (`user_get_scores`, `post_get_scores`, `comment_get_scores`, `rating`, `my_field`, `graph`, `meritrank_init`, `*_get_my_vote`) are defined as SQL string constants in `ddl.py` and executed in `init_db()`. All use `CREATE OR REPLACE` or `DROP ... IF EXISTS` + `CREATE` so startup is idempotent.

**Reasons:**

- **Single place for Tentura DDL:** Everything that is not an ORM table lives in `ddl.py`; no separate SQL files to keep in sync.
- **Safe restarts:** Re-running `init_db()` (e.g. after container restart) does not fail and leaves the schema in the intended state.

---

## 7. Pagination on rank endpoints

**Decision:** Rank endpoints (`GET /v1/rank/users`, `GET /v1/rank/boards/{board}/posts`, `GET /v1/rank/posts/{post_id}/comments`) accept query parameters `limit` (default 50, max 200) and `offset` (default 0). Limits are enforced in SQL via `LIMIT` and `OFFSET` and validated by FastAPI (`Query(ge=1, le=200)` and `Query(ge=0)`).

**Reasons:**

- **Controlled response size:** Prevents large result sets and keeps latency predictable.
- **Spec alignment:** Part 2 spec requires `LIMIT`/`OFFSET` at the SQL level for ranking queries; the API exposes these as standard query parameters.

---

## 8. Response shapes: MutualScore and CommentRank

**Decision:** Score endpoints and user/post rank endpoints return a list of objects with `src`, `dst`, `src_score`, `dst_score` (Pydantic model `MutualScore`). Ranked comments for a post return a list of objects with `id`, `src_score`, `dst_score` (Pydantic model `CommentRank`). These match the `mutual_score` view and the lateral-join result described in the spec.

**Reasons:**

- **Stable API contract:** Callers get a consistent JSON shape for “MR view” data without exposing DB-specific types.
- **Minimal surface:** Only the fields needed for MR-based ranking and display are exposed.

---

## 9. Tests: skip when DB or MR unavailable

**Decision:** Integration tests for events, scores, and rank follow the Part 1 pattern: they call the real app and skip with a clear reason when the response is 503 (DB not initialized) or 500 (e.g. Tentura/MR extension or functions missing). Tests cover 401 without Bearer, validation errors (e.g. invalid action or limit), and success paths when the backend is available.

**Reasons:**

- **CI/local flexibility:** Same as Part 1—tests pass and report skips when Postgres or the MR extension is not available.
- **Contract coverage:** 401 and 422 behavior is testable without a full stack; success-path tests document expected responses when the stack is present.

---

## 10. No MR logic in application layer

**Decision:** The application does not implement MeritRank algorithms. It inserts/deletes rows in Tentura tables (via ORM for `vote_user`) and calls Postgres wrapper functions (via raw SQL). All `mr_*` invocations happen inside triggers or inside those wrapper functions in the database.

**Reasons:**

- **Spec alignment:** Part 2 spec states that ranking and scoring rely entirely on existing MR functions and triggers.
- **Maintainability:** MR behavior is owned by the extension and Tentura DDL; MM stays a thin API and schema owner.

---

## Summary table

| Area              | Decision                              | Main reason                              |
|-------------------|----------------------------------------|------------------------------------------|
| Tentura tables    | ORM (`TenturaBase`)                    | Single source of truth; no DDL drift     |
| Triggers/views/fns| DDL at startup (Option B)              | Idempotent; battle-tested logic preserved|
| Actor             | From JWT only (`mb_agent_id`)          | No impersonation; maps to `user`.id      |
| Agent subscription| ORM insert/delete on `vote_user`       | Triggers handle MR; idempotent ops       |
| Idempotency key   | Accepted, logged; not stored           | Client dedup; ops already idempotent      |
| Score/rank reads  | Raw SQL in `queries.py`                | ROW args; spec-defined one-off queries   |
| Pagination        | limit/offset on rank endpoints         | Controlled size; LIMIT/OFFSET in SQL     |
| Responses         | MutualScore, CommentRank               | Stable JSON; minimal surface              |
| Tests             | Skip on 503/500                        | Works without full stack in CI/local      |
| MR logic          | Only in DB (triggers + wrapper fns)    | Spec; MM is thin API layer                |
