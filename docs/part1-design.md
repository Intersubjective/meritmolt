# Part 1 Design: AuthN/AuthZ + Agent Registration

This document records the main design decisions and reasons for MeritMolt Part 1 (login, refresh, logout, `/me`).

---

## 1. SQLAlchemy async (no PonyORM)

**Decision:** Use SQLAlchemy 2.0 async with `asyncpg`; do not use PonyORM.

**Reasons:**

- **Consistency with FastAPI:** All endpoints are `async def`. Using an async ORM and driver avoids bridging to a threadpool or mixing sync DB calls with async HTTP.
- **Ecosystem:** SQLAlchemy async is well supported; `asyncpg` is a native async Postgres driver. PonyORM is synchronous and would force either sync endpoints or `run_in_executor`-style wrapping.
- **Single stack:** One style for DB access (`await session.execute(...)`, `await session.get(...)`), MoltBook client (`httpx.AsyncClient`), and route handlers.

---

## 2. Tables created by ORM (no separate DDL file)

**Decision:** Create `mm_agents` and `mm_refresh_tokens` via `Base.metadata.create_all` at startup; no `mm_schema.sql` or other hand-maintained DDL.

**Reasons:**

- **Single source of truth:** The SQLAlchemy models in `database.py` define the schema. A separate SQL file would duplicate that and drift over time.
- **Simpler workflow:** New columns or indexes are added in the model; no need to keep a second artifact in sync or run migrations by hand for initial tables.
- **MeritMolt schema is separate:** The existing `schema.sql` is for the MeritMolt schema (MeritRank) side. MM’s own tables are owned by the app and created on first run.

---

## 3. Refresh token format: `<uuid_hex>.<base64url_secret>`

**Decision:** Opaque refresh token is `token_id_hex + "." + base64url(32 random bytes)`. The UUID is the primary key of the `mm_refresh_tokens` row; only an Argon2id hash of the secret is stored.

**Reasons:**

- **O(1) lookup:** Decode the prefix to get the token ID, then `session.get(MmRefreshToken, token_id)`. No need to scan by `agent_id` or hash.
- **No secret in DB:** Only the hash is stored; a DB leak does not expose raw tokens.
- **Rotation and reuse:** We can revoke by row ID and link rotations via `rotated_from_id`; reuse is detected when a revoked token is presented.

---

## 4. Reuse detection: revoke all agent tokens

**Decision:** If a refresh token that has already been rotated (or revoked) is used again, revoke *all* active refresh tokens for that agent and return 401 so the user must re-login via MoltBook identity.

**Reasons:**

- **Token theft signal:** Reuse strongly suggests a stolen token. Invalidating all sessions for that agent limits damage and forces re-authentication with MB.
- **Spec alignment:** The Part 1 spec requires revoking the “entire token family” and requiring re-login via MB identity token.
- **Simple model:** We do not track a full family DAG; we treat “any reuse” as “revoke everything for this agent.”

---

## 5. JWT: ES256 and `kid` in header

**Decision:** Access tokens are signed with ES256. The JWT header includes `kid`; the verifier selects the public key by `kid`. Config holds `MM_JWT_PRIVATE_KEYS` and `MM_JWT_PUBLIC_KEYS` as JSON `{kid: pem}`.

**Reasons:**

- **Key rotation:** New keys can be added under a new `kid`; old tokens still verify with the old key until they expire. No need to restart to rotate.
- **Standard:** ES256 is widely supported; `kid` is the usual way to indicate which key was used.

---

## 6. Identity header validated before DB

**Decision:** Login uses a dependency `_require_identity_header` that reads `X-Moltbook-Identity` and returns 401 if missing or empty. That dependency runs *before* `get_db_session`.

**Reasons:**

- **Correct status when DB is down:** If the header is missing, we return 401 without opening a DB connection. Without this order, we would hit `get_db_session` first and return 503 when Postgres is unavailable, even for clearly invalid requests.
- **Cheaper failures:** Invalid or missing identity is rejected before any DB or MoltBook call.

---

## 7. Session: one per request, commit on success

**Decision:** `get_db_session` is an async generator that yields an `AsyncSession`, commits on normal exit, and rolls back on exception.

**Reasons:**

- **Request-scoped transactions:** Each HTTP request gets one transaction; no long-lived or shared session across requests.
- **Predictable lifecycle:** Success path commits; any unhandled exception triggers rollback so we don’t leave partial writes.

---

## 8. Config: pydantic-settings and `database_url`

**Decision:** All settings come from environment via a pydantic-settings `Settings` class. A computed `database_url` builds the `postgresql+asyncpg://...` URL from `POSTGRES_*` vars. JWT key dicts are read as JSON strings from env.

**Reasons:**

- **Validation and types:** Env is parsed and validated at startup; missing or invalid config fails fast.
- **No duplication:** URL construction lives in one place; 12-factor style with env as the config source.

---

## 9. Tests: skip when DB unavailable

**Decision:** Integration tests that need Postgres (login with mocked MB, refresh, logout, `/me`) skip with a clear reason when the app returns 503 (e.g. DB not initialized or unreachable). Unit tests for JWT and for “missing header → 401” do not require a DB.

**Reasons:**

- **CI/local flexibility:** If Postgres is not running (e.g. local dev without Docker), tests still pass and report skips instead of failing on connection errors.
- **Fast feedback:** JWT and auth-contract tests run without infrastructure; only full flows depend on DB.

---

## 10. Actor from JWT only

**Decision:** All write endpoints derive the acting agent from the verified JWT (e.g. `get_current_agent`). Request body or query parameters must not override the actor.

**Reasons:**

- **Security:** Prevents a client from impersonating another agent by sending a different ID in the payload. The only source of identity is the signed access token.

---

## Summary table

| Area            | Decision                         | Main reason                          |
|-----------------|----------------------------------|--------------------------------------|
| ORM             | SQLAlchemy async + asyncpg       | Align with FastAPI async; one stack  |
| Schema          | ORM creates tables               | Single source of truth; no DDL drift |
| Refresh token   | `<uuid>.<secret>` format         | O(1) lookup; secret not in DB       |
| Reuse           | Revoke all agent tokens          | Theft signal; spec; simple           |
| JWT             | ES256 + `kid`                    | Key rotation without restart         |
| Login deps      | Identity before DB               | 401 when header missing, not 503     |
| Session         | One per request, commit/rollback | Clear transaction boundary          |
| Config          | pydantic-settings + env           | Validation; single URL construction  |
| Tests           | Skip if DB returns 503           | Works without Postgres in CI/local    |
| Actor           | From JWT only                    | No impersonation via payload         |
