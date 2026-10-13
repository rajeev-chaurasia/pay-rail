#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
output="${1:-evidence/concurrency}"
mvn -q -Dtest=PayRailIntegrationTest#concurrencyEvidenceDetectsBrokenNegativeControl -Dpayrail.evidenceDir="$output" test
python3 scripts/seal_concurrency_evidence.py "$output"
python3 scripts/validate_concurrency_evidence.py "$output"
