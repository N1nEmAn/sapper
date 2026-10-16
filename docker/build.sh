#!/usr/bin/env bash
# build.sh — build the sapper agent image and export it for TSecBench upload.
#
#   bash docker/build.sh              # build + export dist/sapper-agent.tar.gz
#   bash docker/build.sh --no-export  # build only
#
# TSecBench accepts .tar / .tar.gz / .tgz up to 3GB.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${IMAGE:-sapper-agent:latest}"
OUT="${OUT:-$REPO/dist/sapper-agent.tar.gz}"

cd "$REPO"

echo "==> building $IMAGE (context: $REPO)"
docker build -f docker/Dockerfile -t "$IMAGE" .

if [[ "${1:-}" == "--no-export" ]]; then
  echo "==> built $IMAGE (export skipped)"
  exit 0
fi

mkdir -p "$(dirname "$OUT")"
echo "==> exporting to $OUT"
docker save "$IMAGE" | gzip -9 > "$OUT"

SIZE=$(du -h "$OUT" | cut -f1)
echo "==> done: $OUT ($SIZE)"
echo
echo "Upload $OUT in the TSecBench console, and set the runtime env vars"
echo "listed in docker/ENV.md (model gateway + key). BENCHMARK_* are injected"
echo "by the platform automatically."
