#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
profile=smoke
output="artifacts/benchmark-$(date -u +%Y%m%dT%H%M%SZ)-$$"
args=()
while (($#)); do
  case "$1" in
    --profile) profile="$2"; shift 2;;
    --rate) args+=(--rate "$2"); shift 2;;
    --duration) value="${2%s}"; args+=(--duration "$value"); shift 2;;
    --output) output="$2"; shift 2;;
    *) echo "Unknown argument: $1" >&2; exit 2;;
  esac
done
[[ "$profile" != quick ]] || profile=smoke
docker compose -p payrail --profile test build verify
docker compose -p payrail --profile test run --rm --entrypoint python3 verify scripts/performance/run.py --profiles "$profile" --output "$output" "${args[@]}"
docker compose -p payrail --profile test run --rm --entrypoint python3 verify scripts/performance/validate.py "$output"
