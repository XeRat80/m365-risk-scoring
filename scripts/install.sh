#!/usr/bin/env bash
set -Eeuo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"

usage() {
  cat <<'HELP'
Usage: ./scripts/install.sh [--check] [--demo]

  --check  Check prerequisites without changing files or starting services.
  --demo   Install and start the local demonstration (default).

This installer currently supports the local demonstration. Connecting a real
Microsoft tenant requires the separate enterprise onboarding work described
in README.md; do not put company credentials into the demo configuration.
HELP
}

mode="${1:---demo}"
case "$mode" in
  --help|-h) usage; exit 0 ;;
  --check) exec ./scripts/doctor.sh ;;
  --demo) ;;
  *) usage >&2; printf 'Unknown option: %s\n' "$mode" >&2; exit 2 ;;
esac

if [[ "$#" -gt 1 ]]; then
  usage >&2
  exit 2
fi

printf '[1/5] Checking host requirements\n'
./scripts/doctor.sh

installation_step="configuration"
on_failure() {
  printf '[ERROR] Installation stopped during %s. Run ./scripts/doctor.sh --after-start for diagnostics.\n' "$installation_step" >&2
  if [[ "$installation_step" == "image build" ]]; then
    printf '        If Docker reports auth.docker.io or a DNS timeout, check network and proxy settings, then rerun this installer.\n' >&2
  fi
  docker compose ps >&2 || true
}
trap on_failure ERR

config_value() {
  local key="$1"
  awk -v key="$key" 'index($0, key "=") == 1 { sub(/^[^=]*=/, ""); print; exit }' .env
}

if [[ ! -f .env ]]; then
  printf '[2/5] Creating local configuration with unique keys\n'
  umask 077
  config_tmp="$(mktemp "$repo_dir/.env.install.XXXXXX")"
  trap 'rm -f "$config_tmp"' EXIT
  token_key="$(openssl rand -base64 32 | tr -d '\n')"
  pseudonym_key="$(openssl rand -hex 32)"
  metrics_key="$(openssl rand -hex 32)"
  mock_key="$(openssl rand -hex 32)"
  while IFS= read -r line || [[ -n "$line" ]]; do
    case "$line" in
      TOKEN_ENCRYPTION_KEY=*) printf 'TOKEN_ENCRYPTION_KEY=%s\n' "$token_key" ;;
      PSEUDONYMIZATION_KEY=*) printf 'PSEUDONYMIZATION_KEY=%s\n' "$pseudonym_key" ;;
      METRICS_KEY=*) printf 'METRICS_KEY=%s\n' "$metrics_key" ;;
      MOCK_ADMIN_SECRET=*) printf 'MOCK_ADMIN_SECRET=%s\n' "$mock_key" ;;
      *) printf '%s\n' "$line" ;;
    esac
  done < .env.example > "$config_tmp"
  mv "$config_tmp" .env
  trap - EXIT
else
  printf '[2/5] Keeping existing .env unchanged\n'
fi

connector_mode="$(config_value CONNECTOR_MODE)"
if [[ "$connector_mode" != "mock" ]]; then
  printf '[ERROR] Existing .env selects CONNECTOR_MODE=%s. This installer supports the local demo only.\n' "$connector_mode" >&2
  printf '        Review README.md before connecting a real company tenant.\n' >&2
  exit 1
fi

model_setting="$(config_value MODEL_BUNDLE_PATH)"
model_setting="${model_setting:-./artifacts/models/current}"
case "$model_setting" in
  /*) model_dir="$model_setting" ;;
  *) model_dir="$repo_dir/${model_setting#./}" ;;
esac
if [[ ! -f "$model_dir/manifest.json" ]]; then
  if [[ -d "$model_dir" ]] && [[ -n "$(find "$model_dir" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
    printf '[ERROR] The configured model directory contains files but has no manifest: %s\n' "$model_dir" >&2
    printf '        Preserve those files and set MODEL_BUNDLE_PATH to a new empty directory in .env.\n' >&2
    exit 1
  fi
  printf '[3/5] Building images and creating a clearly marked demo model\n'
  installation_step="image build"
  docker compose build api mock-graph web
  installation_step="demo model creation"
  mkdir -p "$model_dir"
  python_image="$(docker compose config --images | awk '/^m365-risk-python:/ { print; exit }')"
  if [[ -z "$python_image" ]]; then
    printf '[ERROR] Could not identify the built Python image. Check docker compose config.\n' >&2
    exit 1
  fi
  docker run --rm \
    --user "$(id -u):$(id -g)" \
    --volume "$model_dir:/app/artifacts/models/current" \
    "$python_image" python -m scripts.build_demo_model
else
  printf '[3/5] Using existing model bundle: %s\n' "$model_setting"
  installation_step="image build"
  docker compose build api mock-graph web
fi

printf '[4/5] Starting the local services\n'
installation_step="service startup"
docker compose up -d --no-build

printf '[5/5] Waiting for health checks\n'
installation_step="readiness checks"
ready=0
for (( attempt=1; attempt<=60; attempt++ )); do
  if curl --connect-timeout 2 --max-time 5 -fsS http://127.0.0.1:8000/health/ready >/dev/null 2>&1 \
    && curl --connect-timeout 2 --max-time 5 -fsS http://127.0.0.1:3000 >/dev/null 2>&1 \
    && curl --connect-timeout 2 --max-time 5 -fsS http://127.0.0.1:3002/health/live >/dev/null 2>&1 \
    && curl --connect-timeout 2 --max-time 5 -fsS http://127.0.0.1:8081/health/live >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
if [[ "$ready" -ne 1 ]]; then
  printf '[ERROR] Services did not become ready. Run ./scripts/doctor.sh --after-start\n' >&2
  docker compose ps >&2
  exit 1
fi

./scripts/doctor.sh --after-start
trap - ERR
printf '\nLocal demo ready:\n'
printf '  SOC dashboard: http://localhost:3000\n'
printf '  Validation lab: http://localhost:3002\n'
printf '  API docs:       http://localhost:8000/docs\n'
printf '  Diagnostics:    ./scripts/doctor.sh --after-start\n'
