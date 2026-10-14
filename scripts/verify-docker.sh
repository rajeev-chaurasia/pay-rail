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
python3 scripts/performance/validate.py --allow-unqualified
python3 scripts/performance/render.py --check
python3 -m compileall -q scripts/performance scripts/flow-smoke.py scripts/kafka-recovery.py scripts/qualification-preflight.py
docker compose -p payrail config --quiet
bash -n scripts/*.sh
