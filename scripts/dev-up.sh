#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose -p payrail --profile test build verify
docker compose -p payrail --profile test run --rm --entrypoint mvn verify -q -DskipTests package
docker compose -p payrail up -d --build
echo "PayRail: http://localhost:${PAYRAIL_HTTP_PORT:-18080}  OpenAPI: http://localhost:${PAYRAIL_HTTP_PORT:-18080}/swagger-ui.html"
