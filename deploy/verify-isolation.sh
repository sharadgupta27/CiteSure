#!/usr/bin/env sh
# Proves the private stack's claims from inside the API container. Usage: deploy/verify-isolation.sh [compose args...]
set -eu
cd "$(dirname "$0")/.."
docker compose -f docker-compose.private.yml "$@" exec -T api python - < deploy/verify-isolation.py
