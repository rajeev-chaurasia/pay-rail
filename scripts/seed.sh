#!/usr/bin/env bash
set -euo pipefail
count=100
seed=42
while (($#)); do case "$1" in --objects) count="$2"; shift 2;; --seed) seed="$2"; shift 2;; *) echo "unknown argument: $1" >&2; exit 2;; esac; done
url="${PAYRAIL_URL:-http://localhost:18080}"
key="${PAYRAIL_API_KEY:-pr_test_demo}"
for ((i=0;i<count;i++)); do
  curl --fail --silent --show-error -X POST "$url/v1/payment_intents" -H "Authorization: Bearer $key" -H "Idempotency-Key: seed-$seed-$i" -H 'Content-Type: application/json' -d "{\"amount\":$((100+(i%10000))),\"currency\":\"usd\",\"captureMethod\":\"manual\",\"metadata\":{\"seed\":$seed,\"ordinal\":$i}}" >/dev/null
done
echo "seeded $count payment intents (seed=$seed)"
