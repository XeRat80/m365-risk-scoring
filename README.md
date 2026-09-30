# M365 Risk Scoring

Collect Microsoft 365 security metadata, calculate user risk, and expose results to a company SOC through a REST API. Data stays in the company's deployment.

## Install

Requirements: Git, Docker with Compose v2, curl, OpenSSL; macOS or Linux. Python 3 is needed for the CLI.

```bash
git clone https://github.com/XeRat80/m365-risk-scoring.git
cd m365-risk-scoring
./scripts/install.sh --check
./scripts/install.sh
./scripts/doctor.sh --after-start
```

The installer currently starts a simulated Microsoft environment for development. For a company tenant, complete [Graph configuration](docs/RUNBOOK.md#real-graph-onboarding), admin consent, API authentication and model configuration first. Real-tenant operation has not yet been validated.

## 1. Scan and collect

Set `M365_RISK_TOKEN` to your API administrator token, then run against your configured company deployment:

```bash
python3 scripts/scan_cli.py scan --api https://YOUR-COMPANY-API --out output/scans/run-001 --show-results
```

The API queues the scan; workers collect metadata and build features. To export existing features:

```bash
python3 scripts/scan_cli.py collect --api https://YOUR-COMPANY-API --out output/scans/run-002
```

For the installed test environment, use `--demo` and omit `--api`. This selects simulated data.

## 2. Test

```bash
make bootstrap
make test
make integration
```

Model evaluation requires scanned features and independently reviewed labels: [training instructions](docs/COMMAND_FIRST_WORKFLOW.md). Software tests do not measure model accuracy.

## 3. Show results

```bash
python3 scripts/scan_cli.py results --api https://YOUR-COMPANY-API --top 10
```

API documentation: `http://localhost:8000/docs`. Optional dashboard: `http://localhost:3000`.

## Continuous monitoring

```bash
docker compose up -d api worker
docker compose logs --tail=80 -f worker
```

Set `SYNC_INTERVAL_SECONDS` in `.env`. Workers repeat scans, resume mail checkpoints, refresh alert states and recalculate risk. Detection delay includes Graph availability, throttling and scan duration.

- `POST /api/v1/sync`: request a scan (administrator).
- `GET /api/v1/sync/jobs`: check progress.
- `GET /api/v1/alerts`: read collected user-linked security alerts.
- `POST /api/v1/alerts/{id}/close`: close locally with `{"reason":"resolved"}`, `false_positive`, or `accepted_risk`.

Closure records the analyst, time and reason, and survives synchronization. It preserves evidence and does not change Microsoft Defender or erase calculated risk. New alert IDs remain open.

See [operations and limitations](docs/RUNBOOK.md) for permissions and deployment details. Keep credentials and company exports out of GitHub.
