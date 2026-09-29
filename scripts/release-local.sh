#!/usr/bin/env bash
set -euo pipefail

version="${VERSION:-$(git describe --tags --always --dirty 2>/dev/null || date -u +%Y%m%d%H%M%S)}"
manifest="artifacts/models/current/manifest.json"
test -f "$manifest" || { echo "Model manifest missing; run make train" >&2; exit 1; }
if [[ "${ALLOW_DEMO_MODEL:-0}" == "1" ]]; then
  .venv/bin/python -c 'from pathlib import Path; from packages.ml.m365risk_ml.runtime import ModelRuntime; ModelRuntime.load(Path("artifacts/models/current"))'
else
  .venv/bin/python -m scripts.check_model_gate "$manifest" --require-approved
fi

bundle="releases/$version"
mkdir -p "$bundle/images" "$bundle/artifacts/models/current" "$bundle/scripts" "$bundle/db"
echo "$version" > "$bundle/.release-version"
M365_RISK_VERSION="$version" docker compose build api mock-graph
if [[ "${OFFLINE_WEB_BUILD:-0}" == "1" ]]; then
  ./scripts/build-web-offline.sh "$version"
else
  M365_RISK_VERSION="$version" docker compose build web
fi
machine=$(uname -m)
case "$machine" in
  arm64|aarch64) arch=arm64 ;;
  x86_64|amd64) arch=amd64 ;;
  *) echo "Unsupported architecture: $machine" >&2; exit 1 ;;
esac
docker save "m365-risk-python:$version" -o "$bundle/images/python-$arch.tar"
docker save "m365-risk-web:$version" -o "$bundle/images/web-$arch.tar"
cp docker-compose.yml .env.example alembic.ini "$bundle/"
cp -R db/migrations db/init "$bundle/db/"
find "$bundle/db" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$bundle/db" -type f -name '*.pyc' -delete
cp scripts/install-local.sh scripts/restore-local.sh scripts/rollback-local.sh scripts/smoke-local.sh scripts/wait-for-demo.sh scripts/docker-compose.rollback.yml "$bundle/scripts/"
cp artifacts/models/current/{pipeline.joblib,model.onnx,feature_schema.json,hybrid_weights.json,thresholds.json,metrics.json,coefficients.csv,behavior_baseline.json,manifest.json,model_card.md} "$bundle/artifacts/models/current/"
if command -v syft >/dev/null 2>&1; then
  syft "m365-risk-python:$version" -o cyclonedx-json="$bundle/python.sbom.json"
  syft "m365-risk-web:$version" -o cyclonedx-json="$bundle/web.sbom.json"
elif docker sbom --help >/dev/null 2>&1; then
  docker sbom --format cyclonedx-json "m365-risk-python:$version" > "$bundle/python.sbom.json"
  docker sbom --format cyclonedx-json "m365-risk-web:$version" > "$bundle/web.sbom.json"
else
  echo "Install syft or the Docker SBOM plugin before creating a release" >&2
  exit 1
fi
(cd "$bundle" && find . -type f ! -name SHA256SUMS | sort | xargs shasum -a 256 > SHA256SUMS)
tar -C releases -czf "releases/m365-risk-$version.tar.gz" "$version"
echo "Created releases/m365-risk-$version.tar.gz"
