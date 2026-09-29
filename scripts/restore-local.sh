#!/usr/bin/env bash
set -euo pipefail

bundle="${1:-.}"
dump="${2:-}"
test -n "$dump" || { echo "Usage: restore-local.sh RELEASE_DIR BACKUP.dump" >&2; exit 1; }
dump="$(cd "$(dirname "$dump")" && pwd)/$(basename "$dump")"
cd "$bundle"
test -f "$dump" || { echo "Backup not found: $dump" >&2; exit 1; }
export M365_RISK_VERSION="$(cat .release-version)"
docker compose stop api worker web
docker compose exec -T postgres dropdb -U postgres --force --if-exists m365risk
docker compose exec -T postgres createdb -U postgres m365risk
docker compose exec -T postgres pg_restore -U postgres -d m365risk --no-owner --clean --if-exists < "$dump"
docker compose run --rm api alembic upgrade head
docker compose up -d
./scripts/wait-for-demo.sh
./scripts/smoke-local.sh
echo "PostgreSQL restore completed from $dump"
