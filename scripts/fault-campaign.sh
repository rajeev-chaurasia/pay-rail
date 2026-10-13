#!/usr/bin/env bash
set -euo pipefail
faults=20
seed=42
while (($#)); do case "$1" in --faults) faults="$2"; shift 2;; --seed) seed="$2"; shift 2;; *) echo "unknown argument: $1" >&2; exit 2;; esac; done
url="${PAYRAIL_URL:-http://localhost:18080}"
key="${PAYRAIL_API_KEY:-pr_test_demo}"
run_id="$(date -u +%Y%m%dT%H%M%SZ)-faults"
mkdir -p "artifacts/$run_id"
injected=0
for ((i=0;i<faults;i++)); do
  idem="fault-$seed-$((i/2))"
  curl --max-time 0.001 --silent -X POST "$url/v1/payment_intents" -H "Authorization: Bearer $key" -H "Idempotency-Key: $idem" -H 'Content-Type: application/json' -d '{"amount":101,"currency":"usd","captureMethod":"manual"}' >/dev/null 2>&1 || true
  injected=$((injected+1))
  curl --fail --silent --show-error -X POST "$url/v1/payment_intents" -H "Authorization: Bearer $key" -H "Idempotency-Key: $idem" -H 'Content-Type: application/json' -d '{"amount":101,"currency":"usd","captureMethod":"manual"}' >/dev/null
done
printf '{"seed":%s,"attempted_client_deadlines":%s,"scope":"very short HTTP client deadline plus stable-key duplicate retry; transport outcome is not asserted as server-committed"}\n' "$seed" "$injected" >"artifacts/$run_id/faults.json"
scripts/reconcile.sh >"artifacts/$run_id/reconcile.json"
echo "recorded $injected attempted client-deadline faults; results: artifacts/$run_id"
