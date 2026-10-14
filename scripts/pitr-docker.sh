#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
project="payrail-pitr-$(date +%s)-$$"
export PAYRAIL_HTTP_PORT=0 PAYRAIL_POSTGRES_PORT=0 PAYRAIL_REDIS_PORT=0 PAYRAIL_KAFKA_PORT=0
compose=(docker compose -p "$project" --profile test --profile pitr -f compose.yml -f compose.recovery.yml -f compose.pitr.yml)
cleanup() { "${compose[@]}" down --volumes --remove-orphans; }
trap cleanup EXIT
"${compose[@]}" up -d --no-build --wait postgres redis kafka
"${compose[@]}" exec -T -u root postgres sh -c 'chown postgres:postgres /archive /backups /restore /negative; chmod 700 /archive /backups /restore /negative'
"${compose[@]}" up -d --no-build app
# Create empty restore containers without starting them before backup preparation.
"${compose[@]}" create --no-build restored negative restored-app
"${compose[@]}" run --rm --no-deps --entrypoint python3 \
  -e PITR_PROJECT="$project" \
  -e PITR_POSTGRES="$("${compose[@]}" ps -q postgres)" \
  -e PITR_RESTORED="$("${compose[@]}" ps -aq restored)" \
  -e PITR_NEGATIVE="$("${compose[@]}" ps -aq negative)" \
  -e PITR_APP="$("${compose[@]}" ps -q app)" \
  -e PITR_RESTORED_APP="$("${compose[@]}" ps -aq restored-app)" \
  verify scripts/pitr-smoke.py "$@"
