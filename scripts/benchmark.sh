#!/usr/bin/env bash
set -euo pipefail
command -v k6 >/dev/null || { echo "k6 is required; no benchmark was run" >&2; exit 2; }
profile=quick
rate=10
duration=30s
while (($#)); do case "$1" in --profile) profile="$2"; shift 2;; --rate) rate="$2"; shift 2;; --duration) duration="$2"; shift 2;; *) echo "unknown argument: $1" >&2; exit 2;; esac; done
run_id="$(date -u +%Y%m%dT%H%M%SZ)-$profile"
mkdir -p "artifacts/$run_id"
configured_rpm="${RATE_LIMIT_RPM:-600}"
if ((rate * 60 > configured_rpm)); then echo "offered rate exceeds RATE_LIMIT_RPM=$configured_rpm; raise the runtime and shell value or lower --rate" >&2; exit 2; fi
printf '{"run_id":"%s","profile":"%s","offered_rate":%s,"duration":"%s","configured_rate_limit_rpm":%s,"note":"Measured local result; no extrapolation"}\n' "$run_id" "$profile" "$rate" "$duration" "$configured_rpm" >"artifacts/$run_id/manifest.json"
PAYRAIL_RUN_ID="$run_id" PAYRAIL_RATE="$rate" PAYRAIL_DURATION="$duration" k6 run --summary-export "artifacts/$run_id/summary.json" scripts/load.js
echo "results: artifacts/$run_id"
