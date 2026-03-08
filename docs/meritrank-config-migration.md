# MeritRank service config migration (0.2.59 → current)

## 1. Which config is used

The **main service binary** (`meritrank_service`) reads config only from **`service/src/settings.rs`** via `load_from_env()`. It does **not** use the legacy `AugMultiGraphSettings` / `parse_settings()` from `service/src/legacy/settings.rs` (that path is for the legacy stack). So all "current" and "deprecated" below refer to what the **main** binary actually uses.

---

## 2. Deprecated or removed — what to drop or replace

| Old / legacy env | Action |
|------------------|--------|
| **`MERITRANK_NUM_WALK`** | **Remove.** Use **`MERITRANK_NUM_WALKS`** (with `S`). The legacy parser still accepts `MERITRANK_NUM_WALK` with a deprecation warning; the main service does not read it. |
| **`MERITRANK_ZERO_OPINION_NUM_WALKS`** | **Remove from service config.** Not present in current `Settings`. The single walk count is **`MERITRANK_NUM_WALKS`** for both main and zero-opinion behavior. |
| **`MERITRANK_TOP_NODES_LIMIT`** | **Remove.** Not in current `Settings` (only in legacy `AugMultiGraphSettings`). |
| **`MERITRANK_FILTER_NUM_HASHES`**, **`MERITRANK_FILTER_MAX_SIZE`**, **`MERITRANK_FILTER_MIN_SIZE`** | **Remove.** Filter settings are commented out in `Settings` and not loaded. |
| **`MERITRANK_SLEEP_DURATION_AFTER_PUBLISH_MS`** | **Remove.** Not in current `Settings`; was used by the legacy server. |
| **`MERITRANK_SERVICE_ADDRESS`** | **Do not use for the service.** Binding is controlled by **`MERITRANK_SERVER_ADDRESS`** and **`MERITRANK_SERVER_PORT`**. Use **`MERITRANK_SERVICE_URL`** only on the **client** (e.g. psql-connector) to point at the service. |
| **`MERITRANK_SERVICE_THREADS`** / **`MERITRANK_SERVICE_URL`** (on the service) | Service binary does not use these for its own binding. Use **`MERITRANK_SERVER_*`** for the service; keep **`MERITRANK_SERVICE_URL`** only where the **connector** runs. |

---

## 3. Changed semantics — fix values

### `MERITRANK_ZERO_OPINION_FACTOR`

- **Old (legacy):** Integer **0–100** (percent); stored as `(n as f64) * 0.01`.
- **Current:** Float **0.0–1.0** (direct factor). Invalid values are rejected; default `0.2` is kept.

**Migration:**  
If you had `MERITRANK_ZERO_OPINION_FACTOR=2` (2%) or `20` (20%), set:

- `MERITRANK_ZERO_OPINION_FACTOR=0.02` or `MERITRANK_ZERO_OPINION_FACTOR=0.2` respectively.

So: **percent ÷ 100** and use a float in `[0.0, 1.0]`. Remove integer percent values (e.g. `2`, `20`) to avoid misconfiguration or parse errors.

---

## 4. Current env vars the service actually reads

These are the ones that matter for the **main** service binary.

### Server binding

- **`MERITRANK_SERVER_ADDRESS`** — default `127.0.0.1`
- **`MERITRANK_SERVER_PORT`** — default `8080` (Dockerfile uses `10234`)

So the service listens on `MERITRANK_SERVER_ADDRESS:MERITRANK_SERVER_PORT`. For clients (e.g. psql-connector), set **`MERITRANK_SERVICE_URL`** to that host:port (e.g. `tcp://meritrank:10234`).

### Legacy server (if you still run it)

- **`MERITRANK_LEGACY_SERVER_PORT`** — default `10234`
- **`MERITRANK_LEGACY_SERVER_NUM_THREADS`** — default `4`

### Algorithm and caches

- **`MERITRANK_NUM_WALKS`** — default `10000`
- **`MERITRANK_ZERO_OPINION_FACTOR`** — float in `[0.0, 1.0]`, default `0.2`
- **`MERITRANK_SCORE_CLUSTERS_CACHE_SIZE`** — default `10240`
- **`MERITRANK_SCORE_CLUSTERS_TIMEOUT`** — seconds, default `21600`
- **`MERITRANK_SCORES_CACHE_SIZE`** — default `10240`
- **`MERITRANK_SCORES_CACHE_TIMEOUT`** — seconds, default `3600`
- **`MERITRANK_WALKS_CACHE_SIZE`** — max egos to keep walk data per subgraph; **`0`** = unlimited (default). Use a positive value to cap memory; eviction is per-ego.

### Behavior flags

- **`MERITRANK_OMIT_NEG_EDGES_SCORES`** — default `false`
- **`MERITRANK_FORCE_READ_GRAPH_CONN`** — default `false`

### Processing and tuning

- **`MERITRANK_NUM_SCORE_QUANTILES`** — default `100`
- **`MERITRANK_MIN_OPS_BEFORE_SWAP`** — ops before swapping double-buffer; default `1`
- **`MERITRANK_SUBGRAPH_QUEUE_CAPACITY`** — per-subgraph op queue; default `1024`

### Observability / load testing

- **`MERITRANK_COLLECT_STATS`** — default `false`. Set to `true` to enable GetStats/ResetStats (queue length and per-op processing time). Use **ResetStats** after warmup and **GetStats** to read metrics (e.g. median/p95/p99 in µs). Leave `false` in production unless you need this.

### VSIDS (separate module, still env-based)

- **`VSIDS_BUMP`** — read in `vsids.rs` when `VSIDSManager::new()` runs; default `1.03`. No need to change unless you tune decay.

---

## 5. New or important settings to adopt

- **`MERITRANK_WALKS_CACHE_SIZE`**  
  - `0` (default): no limit on cached walks (best latency, more memory).  
  - Set to a positive value (e.g. `20` in eviction load tests) to cap memory and test eviction behavior.

- **`MERITRANK_MIN_OPS_BEFORE_SWAP`**  
  - Controls how often the double-buffer is published. Default `1` is fine for low latency; increase to batch more ops per swap if you want to reduce publish overhead.

- **`MERITRANK_SUBGRAPH_QUEUE_CAPACITY`**  
  - Size of the per-subgraph op queue. Increase if you see backpressure under high load (e.g. `2048` or `4096`).

- **`MERITRANK_COLLECT_STATS`**  
  - Enable only when doing load testing or profiling; use with **ResetStats** after warmup and **GetStats** to harvest stats. Off by default for production.

- **`MERITRANK_NUM_SCORE_QUANTILES`**  
  - Used for score bucketing; default `100` is usually sufficient.

---

## 6. Example: fixing a 0.2.59-style compose

**Before (problematic):**

```yaml
environment:
  - "MERITRANK_SERVICE_ADDRESS=0.0.0.0"
  - "MERITRANK_SERVICE_URL=tcp://meritrank:10234"
  - "MERITRANK_SERVER_PORT=10234"
  - "MERITRANK_ZERO_OPINION_FACTOR=2"
  - "MERITRANK_ZERO_OPINION_NUM_WALKS=10000"
```

**After (correct for current service):**

- Service container: set **binding** with **`MERITRANK_SERVER_*`**; use **float** for zero opinion; drop vars the service no longer reads:

```yaml
environment:
  - "MERITRANK_SERVER_ADDRESS=0.0.0.0"
  - "MERITRANK_SERVER_PORT=10234"
  - "MERITRANK_ZERO_OPINION_FACTOR=0.02"
  # MERITRANK_SERVICE_URL is for the client (e.g. psql-connector), not this service
```

- Connector/client container: keep **`MERITRANK_SERVICE_URL`** so it can reach the service:

```yaml
environment:
  - "MERITRANK_SERVICE_URL=tcp://meritrank:10234"
```

Optional tuning you can add on the service:

```yaml
  - "MERITRANK_WALKS_CACHE_SIZE=0"
  - "MERITRANK_SUBGRAPH_QUEUE_CAPACITY=1024"
  - "MERITRANK_COLLECT_STATS=false"
```

---

## 7. Quick checklist for an LLM applying the migration

1. Replace **`MERITRANK_NUM_WALK`** with **`MERITRANK_NUM_WALKS`** and remove **`MERITRANK_ZERO_OPINION_NUM_WALKS`** and **`MERITRANK_TOP_NODES_LIMIT`** from service env.
2. Convert **`MERITRANK_ZERO_OPINION_FACTOR`** from 0–100 integer to 0.0–1.0 float (e.g. `2` → `0.02`, `20` → `0.2`).
3. Use **`MERITRANK_SERVER_ADDRESS`** and **`MERITRANK_SERVER_PORT`** for the service; use **`MERITRANK_SERVICE_URL`** only on the client (e.g. psql-connector).
4. Remove **`MERITRANK_SERVICE_ADDRESS`**, **`MERITRANK_FILTER_*`**, **`MERITRANK_SLEEP_DURATION_AFTER_PUBLISH_MS`** from service config.
5. Optionally set **`MERITRANK_WALKS_CACHE_SIZE`** (0 = unlimited), **`MERITRANK_MIN_OPS_BEFORE_SWAP`**, **`MERITRANK_SUBGRAPH_QUEUE_CAPACITY`**, and **`MERITRANK_COLLECT_STATS`** only when needed.
6. Keep **`VSIDS_BUMP`** only if you explicitly tune VSIDS; otherwise omit (default 1.03 is used).

This is the minimal set of changes to adapt old config to the current service and use the new options where useful.
