#!/usr/bin/env bash
set -euo pipefail

previous="${VERSION:-}"
if [[ -z "$previous" && -f releases/previous ]]; then previous=$(cat releases/previous); fi
if [[ -z "$previous" || ! -d "releases/$previous" ]]; then
  echo "Set VERSION to an installed release present under releases/" >&2
  exit 1
fi
ROLLBACK_MODE=1 ./scripts/install-local.sh "releases/$previous"
if [[ -n "${RESTORE_DUMP:-}" ]]; then
  ./scripts/restore-local.sh "releases/$previous" "$RESTORE_DUMP"
fi
