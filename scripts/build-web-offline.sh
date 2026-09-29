#!/usr/bin/env bash
set -euo pipefail

version="${1:?usage: build-web-offline.sh VERSION}"
./scripts/pnpm24.sh --dir apps/web build
docker build --pull=false \
  --file apps/web/Dockerfile.offline \
  --tag "m365-risk-web:$version" \
  apps/web
