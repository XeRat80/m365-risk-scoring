#!/usr/bin/env bash
set -euo pipefail

api="${API_URL:-http://localhost:8000}"
web="${WEB_URL:-http://localhost:3000}"
for _ in $(seq 1 90); do
  if curl -fsS "$api/health/ready" >/dev/null && curl -fsS "$web" >/dev/null; then
    token=$(curl -fsS -X POST "$api/api/v1/auth/mock-token" \
      -H 'Content-Type: application/json' \
      -d '{"tenant_id":"00000000-0000-4000-8000-000000000001","role":"admin"}' \
      | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
    curl -fsS "$api/api/v1/dashboard/summary" -H "Authorization: Bearer $token" >/dev/null
    echo "Demo ready: $web (API docs: $api/docs)"
    exit 0
  fi
  sleep 2
done
docker compose ps
docker compose logs --tail=100 api worker mock-graph web
echo "Demo did not become healthy" >&2
exit 1
