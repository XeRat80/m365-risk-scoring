#!/usr/bin/env bash
set -euo pipefail

api="${API_URL:-http://127.0.0.1:8000}"
tenant="00000000-0000-4000-8000-000000000001"
token=$(curl -fsS -X POST "$api/api/v1/auth/mock-token" \
  -H 'Content-Type: application/json' \
  -d "{\"tenant_id\":\"$tenant\",\"role\":\"admin\"}" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
auth="Authorization: Bearer $token"
curl -fsS "$api/health/ready" >/dev/null
curl -fsS "$api/api/v1/dashboard/summary" -H "$auth" >/dev/null
curl -fsS "$api/api/v1/users?limit=1" -H "$auth" \
  | python3 -c 'import json,sys; value=json.load(sys.stdin); assert isinstance(value["items"],list)'
curl -fsS "$api/api/v1/models/current" -H "$auth" \
  | python3 -c 'import json,sys; value=json.load(sys.stdin); assert value["version"]'
curl -fsS "$api/api/v1/simulations/status" -H "$auth" >/dev/null

curl -fsS -X POST "$api/api/v1/simulations/reset" -H "$auth" >/dev/null
deadline=$((SECONDS + 30))
while (( SECONDS < deadline )); do
  latest=$(curl -fsS "$api/api/v1/sync/jobs?limit=1" -H "$auth")
  status=$(printf '%s' "$latest" | python3 -c 'import json,sys; items=json.load(sys.stdin)["items"]; print(items[0]["status"] if items else "missing")')
  [[ "$status" == "completed" ]] && break
  sleep 1
done
[[ "$status" == "completed" ]] || { echo "Reset synchronization did not complete" >&2; exit 1; }
baseline=$(curl -fsS "$api/api/v1/users/user-001/risk" -H "$auth" | python3 -c 'import json,sys; print(json.load(sys.stdin)["score"])')
curl -fsS -X POST "$api/api/v1/simulations/scenarios/credential-phishing/start" \
  -H "$auth" -H "Idempotency-Key: release-smoke-$(date +%s)" >/dev/null
deadline=$((SECONDS + 10))
score="$baseline"
while (( SECONDS < deadline )); do
  score=$(curl -fsS "$api/api/v1/users/user-001/risk" -H "$auth" | python3 -c 'import json,sys; print(json.load(sys.stdin)["score"])')
  (( score > baseline )) && break
  sleep 1
done
(( score > baseline )) || { echo "Phishing scenario did not raise risk within 10 seconds" >&2; exit 1; }
curl -fsS -X POST "$api/api/v1/simulations/scenarios/recovery/start" \
  -H "$auth" -H "Idempotency-Key: release-recovery-$(date +%s)" >/dev/null
echo "Local release smoke checks passed (risk $baseline -> $score)"
