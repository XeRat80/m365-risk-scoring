#!/usr/bin/env bash
set -u

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir" || exit 1

after_start=0
case "${1:-}" in
  "") ;;
  --after-start) after_start=1 ;;
  --help|-h)
    echo "Usage: ./scripts/doctor.sh [--after-start]"
    echo "Checks host requirements and, optionally, the running local demo."
    exit 0
    ;;
  *) echo "Unknown option: $1" >&2; exit 2 ;;
esac

failures=0
ok() { printf '[OK] %s\n' "$1"; }
problem() { printf '[ERROR] %s\n' "$1" >&2; failures=$((failures + 1)); }
hint() { printf '        %s\n' "$1" >&2; }

case "$(uname -s)" in
  Darwin|Linux) ok "Supported host: $(uname -s)" ;;
  *) problem "This installer supports macOS and Linux only." ;;
esac
case "$(uname -m)" in
  arm64|aarch64|x86_64|amd64) ok "Supported CPU: $(uname -m)" ;;
  *) problem "Unsupported CPU: $(uname -m). Use ARM64 or x86-64." ;;
esac

for binary in docker curl openssl; do
  if command -v "$binary" >/dev/null 2>&1; then
    ok "$binary is installed"
  else
    problem "$binary is missing"
    case "$binary" in
      docker) hint "Install Docker Desktop (macOS) or Docker Engine with the Compose plugin (Linux)." ;;
      curl) hint "Install curl with your operating system's package manager." ;;
      openssl) hint "Install OpenSSL; it generates unique local configuration keys." ;;
    esac
  fi
done

if command -v docker >/dev/null 2>&1; then
  if docker compose version >/dev/null 2>&1; then
    ok "Docker Compose v2 is available"
  else
    problem "Docker Compose v2 is unavailable"
    hint "Install the Docker Compose plugin; the old docker-compose command is not sufficient."
  fi
  if docker info >/dev/null 2>&1; then
    ok "Docker daemon is running and accessible"
  else
    problem "Docker daemon is unavailable"
    hint "Start Docker Desktop, or start Docker Engine and grant this user Docker access."
  fi
fi

if [[ "$after_start" -eq 0 ]] && command -v curl >/dev/null 2>&1; then
  if curl --connect-timeout 4 --max-time 7 -sS -o /dev/null https://auth.docker.io/token 2>/dev/null; then
    ok "Docker Hub authentication endpoint is reachable"
  else
    problem "Cannot reach auth.docker.io to build the container images"
    hint "Check DNS, internet access, proxy settings, and Docker Desktop network settings."
  fi
fi

if [[ "$after_start" -eq 1 ]]; then
  if [[ ! -f .env ]]; then
    problem "Missing .env configuration"
    hint "Run ./scripts/install.sh to create the local demo configuration."
  else
    ok ".env exists"
  fi
  model_setting="$(awk 'index($0, "MODEL_BUNDLE_PATH=") == 1 { sub(/^[^=]*=/, ""); print; exit }' .env 2>/dev/null)"
  model_setting="${model_setting:-./artifacts/models/current}"
  if [[ ! -f "$model_setting/manifest.json" ]]; then
    problem "No default model manifest was found"
    hint "Run ./scripts/install.sh to create the local demo model."
  fi
  if command -v docker >/dev/null 2>&1 && docker compose ps --status running --services 2>/dev/null | awk '$0 == "worker" { found = 1 } END { exit !found }'; then
    ok "Background scanning worker is running"
  else
    problem "Background scanning worker is not running"
    hint "Inspect: docker compose logs --tail=80 worker"
  fi
  for entry in \
    "API|api|http://127.0.0.1:8000/health/ready" \
    "Dashboard|web|http://127.0.0.1:3000" \
    "Simulator|simulator|http://127.0.0.1:3002/health/live" \
    "Mock Graph|mock-graph|http://127.0.0.1:8081/health/live"; do
    label="${entry%%|*}"
    remainder="${entry#*|}"
    service="${remainder%%|*}"
    url="${remainder#*|}"
    if command -v curl >/dev/null 2>&1 && curl --connect-timeout 2 --max-time 5 -fsS "$url" >/dev/null 2>&1; then
      ok "$label responds at $url"
    else
      problem "$label is not ready at $url"
      hint "Inspect: docker compose ps; docker compose logs --tail=80 $service"
    fi
  done
fi

if [[ "$failures" -gt 0 ]]; then
  printf '\n%d check(s) failed. Fix them and rerun ./scripts/doctor.sh%s\n' "$failures" "$([[ "$after_start" -eq 1 ]] && printf ' --after-start')" >&2
  exit 1
fi
printf '\nAll requested checks passed.\n'
