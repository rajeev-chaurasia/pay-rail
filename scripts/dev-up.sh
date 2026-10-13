#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mvn -q -DskipTests package
docker compose -p payrail up -d --build
echo "PayRail: http://localhost:${PAYRAIL_HTTP_PORT:-18080}  OpenAPI: http://localhost:${PAYRAIL_HTTP_PORT:-18080}/swagger-ui.html"
