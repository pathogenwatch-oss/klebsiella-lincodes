#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

IMAGE="${IMAGE:-902121496535.dkr.ecr.eu-west-2.amazonaws.com/pathogenwatch-source/plincer}"
BUILD_DATE="${BUILD_DATE:-$(date +%Y-%m-%d)}"
LOG="${LOG:-INFO}"
CACHE_DIR="${CACHE_DIR:-cache_dir}"
SECRETS_FILE="${SECRETS_FILE:-$SCRIPT_DIR/secrets.json}"

VERSION="$(awk '
  /^\[project\]$/ { in_project = 1; next }
  /^\[/ { in_project = 0 }
  in_project && $0 ~ /^version[[:space:]]*=/ {
    value = $0
    sub(/^[^=]*=[[:space:]]*"/, "", value)
    sub(/"[[:space:]]*$/, "", value)
    print value
    exit
  }
' pyproject.toml)"

if [[ -z "$VERSION" ]]; then
    echo "Could not read [project].version from pyproject.toml" >&2
    exit 1
fi

if [[ ! -f "$SECRETS_FILE" ]]; then
    echo "Secrets file not found: $SECRETS_FILE" >&2
    exit 1
fi

TAG="v${VERSION}-${BUILD_DATE}"

docker build --progress plain \
    --build-arg "BUILD_DATE=${BUILD_DATE}" \
    --build-arg "LOG=${LOG}" \
    --secret "id=secrets,src=${SECRETS_FILE}" \
    --cache-from "type=local,src=${CACHE_DIR}" \
    --cache-to "type=local,dest=${CACHE_DIR}" \
    -t "${IMAGE}:${TAG}" \
    .

docker push "${IMAGE}:${TAG}"
