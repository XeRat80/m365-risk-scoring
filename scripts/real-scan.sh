#!/usr/bin/env bash
set -Eeuo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

usage() {
  printf '%s\n' \
    'Usage: ./scripts/real-scan.sh check TENANT_ID CLIENT_ID USER_ID|all-users' \
    '       ./scripts/real-scan.sh scan TENANT_ID CLIENT_ID USER_ID|all-users RUN_NAME' \
    '' \
    'Requires ./scripts/setup-real-scan.sh and Graph application admin consent.' \
    'The client secret is requested interactively; never put it in the command.' \
    'Results stay on this machine under private/scans/RUN_NAME.'
}

if [[ "${1:-}" == '--help' || "${1:-}" == '-h' ]]; then
  usage
  exit 0
fi
if [[ "$#" -lt 4 || "$#" -gt 5 ]]; then
  usage >&2
  exit 2
fi
command_name="$1"
tenant_id="$2"
client_id="$3"
target="$4"
if [[ "$command_name" != 'check' && "$command_name" != 'scan' ]]; then
  usage >&2
  exit 2
fi
if [[ "$command_name" == 'check' && "$#" -ne 4 || "$command_name" == 'scan' && "$#" -ne 5 ]]; then
  usage >&2
  exit 2
fi
if [[ ! -f private/collector.key ]]; then
  printf '[ERROR] Run ./scripts/setup-real-scan.sh first.\n' >&2
  exit 1
fi
if [[ "$target" == 'all-users' ]]; then
  scope=(--all-users)
else
  scope=(--user-id "$target")
fi
output_args=()
if [[ "$command_name" == 'scan' ]]; then
  run_name="$5"
  if [[ ! "$run_name" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$ ]]; then
    printf '[ERROR] RUN_NAME must use only letters, digits, underscore or hyphen.\n' >&2
    exit 2
  fi
  if [[ -e "private/scans/$run_name" ]]; then
    printf '[ERROR] Run directory already exists. Choose a new RUN_NAME.\n' >&2
    exit 1
  fi
  output_args=(--out "/app/private/scans/$run_name")
fi

printf 'Read-only Graph %s. Raw responses and credentials are not saved.\n' "$command_name"
docker run --rm --interactive --tty \
  --user "$(id -u):$(id -g)" \
  --mount "type=bind,source=$repo_dir/private,target=/app/private" \
  m365-risk-collector:local \
  python -m scripts.real_graph_scan "$command_name" \
  --tenant-id "$tenant_id" --client-id "$client_id" \
  --key-file /app/private/collector.key "${scope[@]}" "${output_args[@]}"
