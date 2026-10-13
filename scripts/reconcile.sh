#!/usr/bin/env bash
set -euo pipefail
url="${PAYRAIL_URL:-http://localhost:18080}"
token="${MIGRATION_ADMIN_TOKEN:-local-admin-token}"
command -v jq >/dev/null || { echo "jq is required" >&2; exit 2; }
result="$(curl --fail --silent --show-error "$url/v1/admin/migrations/payment-v2/reconcile" -H "X-Admin-Token: $token")"
echo "$result"
jq -e '(.missing|tonumber)==0 and (.extra|tonumber)==0 and (.mismatched|tonumber)==0' <<<"$result" >/dev/null
