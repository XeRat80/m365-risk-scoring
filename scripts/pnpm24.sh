#!/usr/bin/env bash
set -euo pipefail

major=$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || true)
if [[ "$major" != "24" ]] && command -v brew >/dev/null 2>&1; then
  node24=$(brew --prefix node@24 2>/dev/null || true)
  if [[ -n "$node24" ]]; then export PATH="$node24/bin:$PATH"; fi
fi
major=$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || true)
if [[ "$major" != "24" ]]; then
  echo "Node.js 24 is required; run make bootstrap" >&2
  exit 1
fi
exec corepack pnpm "$@"
