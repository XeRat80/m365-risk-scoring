#!/usr/bin/env bash
set -Eeuo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

for binary in docker openssl; do
  if ! command -v "$binary" >/dev/null 2>&1; then
    printf '[ERROR] %s is missing. Install it, then rerun this setup.\n' "$binary" >&2
    exit 1
  fi
done
if ! docker info >/dev/null 2>&1; then
  printf '[ERROR] Docker is not running or is inaccessible. Start Docker and retry.\n' >&2
  exit 1
fi

mkdir -p private/scans
chmod 700 private private/scans
if [[ ! -e private/collector.key ]]; then
  umask 077
  openssl rand -hex -out private/collector.key 32
  printf '[OK] Created a company-local pseudonym key. Keep private/collector.key safe for repeat scans.\n'
else
  printf '[OK] Existing pseudonym key preserved.\n'
fi
chmod 600 private/collector.key

printf '[1/2] Building the read-only collector image\n'
docker build --tag m365-risk-collector:local --file Dockerfile.python .
printf '[2/2] Verifying the collector command\n'
docker run --rm m365-risk-collector:local python -m scripts.real_graph_scan --help >/dev/null
printf '\nCollector ready. Run ./scripts/real-scan.sh --help for the next command.\n'
