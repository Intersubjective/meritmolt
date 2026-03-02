#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# MM_IMAGE_TAG is passed by CI deploy action (e.g. dev-abc123 or sha-abc1234).
# Pull precisely that image by hash for reproducible deploys.
if [ -n "${MM_IMAGE_TAG:-}" ]; then
  echo "[deploy] Using image tag: ${MM_IMAGE_TAG}"
else
  if [ "${MM_DEV_SERVER:-}" = "1" ]; then
    echo "[deploy] No MM_IMAGE_TAG provided, using dev-latest (fallback for dev server)"
    export MM_IMAGE_TAG=dev-latest
  else
    echo "[deploy] ERROR: MM_IMAGE_TAG is required for non-dev deploys." >&2
    echo "[deploy] Set MM_IMAGE_TAG to the desired image tag (e.g. sha-abc1234) and re-run." >&2
    echo "[deploy] Or set MM_DEV_SERVER=1 to allow dev-latest fallback." >&2
    exit 1
  fi
fi

echo "[deploy] Pulling images..."
docker compose -f compose.yaml -f compose.deploy.yaml pull

echo "[deploy] Recreating containers..."
docker compose -f compose.yaml -f compose.deploy.yaml up -d

echo "[deploy] Cleaning old images..."
docker image prune -f

echo "[deploy] Done."
