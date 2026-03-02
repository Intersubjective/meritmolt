#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# MM_IMAGE_TAG is passed by CI deploy action (e.g. dev-abc123 or sha-abc1234).
# Pull precisely that image by hash for reproducible deploys.
if [ -n "${MM_IMAGE_TAG:-}" ]; then
  echo "[deploy] Using image tag: ${MM_IMAGE_TAG}"
else
  echo "[deploy] No MM_IMAGE_TAG provided, using latest (fallback)"
  export MM_IMAGE_TAG=latest
fi

echo "[deploy] Pulling images..."
docker compose -f compose.yaml -f compose.deploy.yaml pull

echo "[deploy] Recreating containers..."
docker compose -f compose.yaml -f compose.deploy.yaml up -d

echo "[deploy] Cleaning old images..."
docker image prune -f

echo "[deploy] Done."
