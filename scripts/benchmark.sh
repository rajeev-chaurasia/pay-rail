#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
profile=smoke
args=()
while (($#)); do
  case "$1" in
    --profile) profile="$2"; shift 2;;
    --rate) args+=(--rate "$2"); shift 2;;
    --duration) value="${2%s}"; args+=(--duration "$value"); shift 2;;
    --output) args+=(--output "$2"); shift 2;;
    *) echo "Unknown argument: $1" >&2; exit 2;;
  esac
done
[[ "$profile" != quick ]] || profile=smoke
python3 scripts/performance/run.py --profiles "$profile" "${args[@]}"
python3 scripts/performance/validate.py --allow-unqualified
