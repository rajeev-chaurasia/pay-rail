#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y docker.io docker-compose-v2 git jq python3 ca-certificates
systemctl enable --now docker
mkdir -p /srv/payrail-qualification
touch /srv/payrail-qualification/bootstrap-ready
