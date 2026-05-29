#!/bin/bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

mkdir -p logs

if [ -f "$ROOT_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
fi

SIMPLE_CLUSTERMANAGER_PORT="${SIMPLE_CLUSTERMANAGER_PORT:-9999}"
export SIMPLE_CLUSTERMANAGER_PORT

exec uvicorn main:app --host 0.0.0.0 --port "$SIMPLE_CLUSTERMANAGER_PORT"
