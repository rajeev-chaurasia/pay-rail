#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
project="payrail-recovery-$(date +%s)-$$"
export PAYRAIL_HTTP_PORT=0 PAYRAIL_POSTGRES_PORT=0 PAYRAIL_REDIS_PORT=0 PAYRAIL_KAFKA_PORT=0
compose=(docker compose -p "$project" --profile test -f compose.yml -f compose.recovery.yml)
cleanup() { "${compose[@]}" down --volumes --remove-orphans; }
trap cleanup EXIT
"${compose[@]}" up -d --no-build app
"${compose[@]}" run --rm --no-deps --entrypoint python3 \
  -e RECOVERY_PROJECT="$project" \
  -e RECOVERY_APP="$("${compose[@]}" ps -q app)" \
  -e RECOVERY_POSTGRES="$("${compose[@]}" ps -q postgres)" \
  -e RECOVERY_KAFKA="$("${compose[@]}" ps -q kafka)" \
  verify scripts/recovery-smoke.py "$@"
