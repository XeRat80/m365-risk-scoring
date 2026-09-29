#!/usr/bin/env bash
set -euo pipefail

installer_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bundle="$(cd "${1:-.}" && pwd)"
release_root="$(dirname "$bundle")"
version_dir="$(basename "$bundle")"
cd "$bundle"
test -f .release-version || { echo "Release version metadata is missing" >&2; exit 1; }
export M365_RISK_VERSION="$(cat .release-version)"
shasum -a 256 -c SHA256SUMS
test -f .env || cp .env.example .env
compose=(docker compose)
if [[ "${ROLLBACK_MODE:-0}" == "1" ]]; then
  rollback_override="$installer_dir/docker-compose.rollback.yml"
  test -f "$rollback_override" || { echo "Rollback Compose override is missing" >&2; exit 1; }
  compose+=(--file docker-compose.yml --file "$rollback_override")
fi
mkdir -p backups
if docker ps \
  --filter label=com.docker.compose.project=m365-risk \
  --filter label=com.docker.compose.service=postgres \
  --filter status=running --quiet | grep -q .; then
  "${compose[@]}" exec -T postgres pg_dump -U postgres -d m365risk -Fc > "backups/pre-install-$(date -u +%Y%m%dT%H%M%SZ).dump"
fi
machine=$(uname -m)
case "$machine" in
  arm64|aarch64) arch=arm64 ;;
  x86_64|amd64) arch=amd64 ;;
  *) echo "Unsupported architecture: $machine" >&2; exit 1 ;;
esac
for component in python web; do
  image="images/$component-$arch.tar"
  test -f "$image" || { echo "Release does not contain $component for $arch" >&2; exit 1; }
  docker load -i "$image"
done
docker tag "m365-risk-python:$M365_RISK_VERSION" "m365-risk-mock-graph:$M365_RISK_VERSION"
"${compose[@]}" up -d postgres mock-graph
if [[ "${ROLLBACK_MODE:-0}" != "1" ]]; then
  "${compose[@]}" run --rm api alembic upgrade head
fi
"${compose[@]}" up -d
./scripts/wait-for-demo.sh
./scripts/smoke-local.sh
if [[ "$(basename "$release_root")" == "releases" ]]; then
  if [[ -f "$release_root/latest" ]] && [[ "$(cat "$release_root/latest")" != "$version_dir" ]]; then
    cp "$release_root/latest" "$release_root/previous"
  fi
  echo "$version_dir" > "$release_root/latest"
fi
echo "Installed and verified M365 Risk release $M365_RISK_VERSION"
