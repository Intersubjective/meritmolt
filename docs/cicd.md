# CI/CD Pipeline

This document describes the build, test, and deployment flow for MeritMolt.

---

## Overview

The pipeline is defined in `.github/workflows/build-and-push.yml` and runs on **pushes** and **pull requests** to `main` and `release`.

---

## Triggers

| Event           | Branches      |
|-----------------|---------------|
| `push`          | `main`, `release` |
| `pull_request`  | `main`, `release` |

---

## Jobs and Flow

### 1. `determine-target` (runs first)

Selects what to build and where to deploy:

- **Push to `main`** → `build_type=dev`, deploy to **dev**
- **Push to `release`** → `build_type=release`, deploy to **stage** and **prod**
- **PRs** → no deployment, only build and test

Also extracts `version` from `pyproject.toml` and the short commit SHA.

### 2. `test-unit` (runs in parallel)

- Python 3.14, `uv`
- `uv sync --extra dev`
- `pytest -m "not integration" -v`
- Uses SQLite for tests (`MM_USE_SQLITE_FOR_TESTS=1`)

### 3. `test-integration` (runs in parallel)

- Starts full stack: `docker compose -f compose.yaml -f compose.ci.yaml up -d postgres meritrank meritmolt`
- `compose.ci.yaml` builds MeritMolt from source instead of pulling an image
- Generates JWT keys for tests
- Waits for MeritMolt health at `http://localhost:8000/health`
- Seeds data: `scripts/seed_integration_test_data.py`
- Runs `pytest -m integration -v`
- Tears down containers with `docker compose down`

### 4. `build-images` (depends on `determine-target`)

- **PRs or non-deploy builds**: build image only, no push
- **Push to `main`**: build and push to GHCR with tags:
  - `dev-<full-sha>`
  - `dev-latest`
- **Push to `release`**: build and push with tags:
  - `v<version>` (from `pyproject.toml`)
  - `latest`
  - `sha-<short-sha>`
- Uses GitHub Actions cache for Docker layers (`scope=meritmolt`)

### 5. `deploy-dev` (only on push to `main`)

- Needs: `determine-target`, `test-unit`, `test-integration`, `build-images`
- Uses GitHub environment `dev`
- Concurrency: one deploy at a time, newer runs cancel older ones
- Calls `./.github/actions/deploy` with `image-tag: dev-${{ github.sha }}`

### 6. `deploy-stage` (only on push to `release`)

- Same dependencies as `deploy-dev`
- Uses environment `stage`
- Deploys `image-tag: sha-<short-sha>`

### 7. `deploy-prod` (only on push to `release`)

- Needs: `deploy-stage` plus the same test/build jobs
- Uses environment `prod`
- Deploys `image-tag: sha-<short-sha>`

---

## Deploy Action (`.github/actions/deploy/action.yml`)

The deploy action:

1. Sets up SSH with `VPS_SSH_KEY`
2. Adds the VPS host to `known_hosts`
3. SSHs as `deploy@<VPS_HOST>` into `/opt/meritmolt`
4. Sets `MM_IMAGE_TAG` and runs `./deploy.sh`

Each environment (`dev`, `stage`, `prod`) must provide secrets:

- `VPS_HOST`
- `VPS_SSH_KEY`

---

## Deployment on the VPS

On the server, `deploy.sh` is expected to:

- Use `compose.deploy.yaml`, which pulls `ghcr.io/intersubjective/meritmolt:${MM_IMAGE_TAG}`
- Run `docker compose -f compose.yaml -f compose.deploy.yaml up -d` (or equivalent)

---

## Flow Diagram

```
                    ┌─────────────────────┐
                    │  determine-target   │
                    └──────────┬──────────┘
                               │
         ┌─────────────────────┼─────────────────────┐
         ▼                     ▼                     ▼
  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
  │  test-unit   │     │test-integration│   │ build-images │
  └──────┬───────┘     └──────┬───────┘     └──────┬───────┘
         │                    │                    │
         └────────────────────┼────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
  │ deploy-dev   │     │ deploy-stage │     │ deploy-prod  │
  │ (main only)  │     │(release only)│     │(release,     │
  │              │     │              │     │ after stage) │
  └──────────────┘     └──────────────┘     └──────────────┘
```
