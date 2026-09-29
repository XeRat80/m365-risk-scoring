#!/usr/bin/env bash
set -euo pipefail

name="${1:-credential-phishing}"
api="${API_URL:-http://localhost:8000}"
token="${TOKEN:-}"
if [[ -z "$token" ]]; then
  token=$(curl -fsS -X POST "$api/api/v1/auth/mock-token" \
    -H 'Content-Type: application/json' \
    -d '{"tenant_id":"00000000-0000-4000-8000-000000000001","role":"admin"}' \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
fi
curl -fsS -X POST "$api/api/v1/simulations/scenarios/$name/start" \
  -H "Authorization: Bearer $token" \
  -H "Idempotency-Key: cli-$name-$(date +%s)"
echo
