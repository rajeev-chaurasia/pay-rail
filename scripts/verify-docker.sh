#!/usr/bin/env bash
set -euo pipefail
export GIT_CONFIG_COUNT=1
export GIT_CONFIG_KEY_0=safe.directory
export GIT_CONFIG_VALUE_0=/workspace
npm ci --ignore-scripts
npm run check
python3 scripts/check_style.py --self-test
mvn --batch-mode --no-transfer-progress verify
python3 scripts/validate_concurrency_evidence.py --self-test
python3 -m unittest discover -s scripts/performance -p 'test_*.py'
python3 -m unittest discover -s scripts/tests -p 'test_*.py'
python3 scripts/validate_qualification_evidence.py
python3 scripts/validate_pitr_evidence.py
python3 scripts/gcp/validate_campaign.py evidence/gcp/q-20261014092401-2304be
python3 scripts/performance/validate.py --allow-unqualified
python3 scripts/performance/render.py --check
python3 -m compileall -q scripts/performance scripts/flow-smoke.py scripts/kafka-recovery.py scripts/qualification-preflight.py scripts/compatibility-smoke.py scripts/validate_qualification_evidence.py scripts/poison-recovery.py scripts/recovery-smoke.py scripts/pitr-smoke.py scripts/validate_pitr_evidence.py
python3 -m compileall -q scripts/gcp
docker run --rm -v "${PAYRAIL_HOST_WORKSPACE}:/src:ro" -w /src golang:1.25.3@sha256:6d4e5e74f47db00f7f24da5f53c1b4198ae46862a47395e30477365458347bf2 go vet scripts/gcp/load.go
docker run --rm -v "${PAYRAIL_HOST_WORKSPACE}:/src:ro" -w /src golang:1.25.3@sha256:6d4e5e74f47db00f7f24da5f53c1b4198ae46862a47395e30477365458347bf2 go vet scripts/gcp/faultgen/main.go
docker compose -p payrail config --quiet
docker compose -p payrail-recovery-config -f compose.yml -f compose.recovery.yml config --quiet
docker compose -p payrail-pitr-config --profile pitr -f compose.yml -f compose.recovery.yml -f compose.pitr.yml config --quiet
docker compose -p payrail-qual-config -f compose.yml -f deploy/gcp/compose.yml config --quiet
bash -n scripts/*.sh
