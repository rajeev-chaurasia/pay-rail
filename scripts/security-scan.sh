#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "$0")/.." && pwd)"
output="${1:-$task_root/artifacts/security}"
mkdir -p "$output"
output="$(cd "$output" && pwd)"
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$output:/reports" \
  -v payrail-trivy-cache:/root/.cache/trivy \
  aquasec/trivy:0.75.0@sha256:af6acf9a6b85dfe389a1941505c0ce9efef52a4719635e1a962f022a3d855daa \
  image --scanners vuln --image-src docker --severity HIGH,CRITICAL --exit-code 1 \
  --format json --output /reports/runtime-gate.json payrail-app
