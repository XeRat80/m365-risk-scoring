#!/usr/bin/env bash
set -euo pipefail

if ! command -v uv >/dev/null 2>&1; then
  python3 -m pip install --user uv
  export PATH="$(python3 -m site --user-base)/bin:$PATH"
fi
uv python install 3.13
uv venv --clear --python 3.13 .venv
uv pip sync --python .venv/bin/python requirements-dev.txt

major=$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || true)
if [[ "$major" != "24" ]]; then
  if command -v brew >/dev/null 2>&1; then
    brew list node@24 >/dev/null 2>&1 || brew install node@24
    export PATH="$(brew --prefix node@24)/bin:$PATH"
  else
    echo "Install Node.js 24 (see .nvmrc), then rerun make bootstrap" >&2
    exit 1
  fi
fi
test "$(node -p 'process.versions.node.split(".")[0]')" = "24"
corepack enable
corepack prepare pnpm@10.28.0 --activate
corepack pnpm --dir apps/web install --frozen-lockfile

docker --version
docker compose version
docker info >/dev/null
echo "Bootstrap complete: $(.venv/bin/python --version), Node $(node --version), $(corepack pnpm --version)"
