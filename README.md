# M365 Risk Platform

Offline-first Microsoft 365 user-risk scoring prototype. It runs without a company tenant by combining a signed mock OIDC provider, a Microsoft Graph-compatible simulator, continuous mail metadata, PostgreSQL row-level security, model inference, a worker queue, and a Next.js analyst dashboard. Real-tenant deployment and model quality on company data are not yet validated.

The project is metadata-only: message subject, body, preview, unique body, and attachment bytes are never requested or persisted.

## Install from GitHub

GitHub distributes the source and installation instructions. The application, model and scanned data run on the installing organization's machine or private infrastructure. Copy the HTTPS clone URL from this repository's **Code** button.

Requirements for the current local demonstration: macOS or Linux on ARM64 or x86-64, Docker Desktop or Docker Engine with the Compose v2 plugin, `curl`, `openssl`, and enough free disk space for the container images. Git is needed to clone the repository. Python and Node.js are built into the images and are not required on the host.

```bash
git clone GITHUB_REPOSITORY_URL m365-risk
cd m365-risk
./scripts/install.sh --check
./scripts/install.sh
```

The installer checks prerequisites, creates an ignored `.env` with unique local keys, builds images, creates an explicitly marked demonstration model when no bundle exists, starts the stack, and verifies the web services and background worker. The worker begins synchronization automatically. The installer keeps an existing `.env` and model bundle. A failed check prints the missing requirement or failing service and the corresponding diagnostic command. Rerunning preserves configuration and the database volume; it can restart services and reset in-memory demo scenarios.

```bash
./scripts/doctor.sh --after-start  # diagnose an installed demo
docker compose ps
docker compose logs --tail=80 api worker
docker compose down                # stop services; keep data
```

Open:

- SOC monitoring product: <http://localhost:3000>
- Security validation simulator: <http://localhost:3002>
- API documentation: <http://localhost:8000/docs>
- Mock Graph/OIDC discovery: <http://localhost:8081/.well-known/openid-configuration>

The mock login issues a locally signed JWT. Choose either demo tenant and the analyst or administrator role. No Microsoft 365 account is required. This GitHub install path currently starts the **local demonstration**; it does not access a company tenant.

### Hosting choice for the PFE prototype

The current prototype runs model inference in the local worker container. It does not require a paid model-hosting service or send scoring inputs to a public notebook. GitHub distributes source and installation instructions; it does not host the running scanner. The host still needs a machine, storage, and network access to obtain dependencies, so this is not a claim of zero operating cost.

For a future company deployment, the preferred managed option is an authenticated, private model endpoint in the customer's own infrastructure or Azure subscription, alongside company-controlled data storage. That endpoint is **a proposed production architecture, not an implemented feature of this release**. Before enabling real tenant scans, the team must complete admin consent, permitted Graph collection, security review, model approval, and a validated private deployment. Company mail exports, identities, tokens, and scoring features must not be uploaded to Kaggle or another public notebook as part of the default workflow.

### Command-first scanner and remote training experiment

The API and CLI can be used without either dashboard. Once the local demo stack is running, a single command requests a scan, waits for the worker, and exports stored V2 feature windows:

```bash
python3 scripts/scan_cli.py scan --demo --out output/scans/demo-001
python3 scripts/scan_cli.py results --demo --top 5
python3 scripts/scan_cli.py scan --demo --scan-only
python3 scripts/scan_cli.py collect --demo --out output/scans/demo-002
```

The `results` command prints the current operational risk-band summary and top scores without display names; `scan --show-results` does both in one command. These scores come from the currently configured runtime model, **not** the separate experimental training script. The export contains only whitelisted derived features, five canonical components, explicit availability states, HMAC-pseudonymous sample/subject keys, and a checksum manifest. It excludes message content, raw headers, raw identities, existing risk scores, and labels. The same authenticated endpoint is `GET /api/v1/datasets/scanned` (administrator only). Scanning does **not** create trustworthy incident labels. A separate, analyst-reviewed `sample_id,label` CSV is required before training/testing.

`scripts/train_scanned.py` is a standalone Python 3.11+ experiment (NumPy, scikit-learn, joblib) designed to run on a remote machine. It checks the export checksum, rejects real scan data in public-notebook mode, keeps all windows of an employee in one split, compares logistic regression with random forest, and writes an **unapproved** model and holdout report. Example remote command:

```bash
python scripts/train_scanned.py \
  --features /private/data/feature_windows.jsonl \
  --labels /private/data/reviewed_labels.csv \
  --out /private/results/experiment-001
```

For the public PFE demonstration, use only synthetic/generated exports with `--public-notebook` on a free Kaggle notebook. Real company scans and reviewed labels must stay on company-controlled compute unless the organization explicitly approves an external processor. This training experiment is **not connected to live inference or model promotion yet**. See [the command-first workflow](docs/COMMAND_FIRST_WORKFLOW.md), [supervisor demo script](docs/SUPERVISOR_DEMO.md), and [public release checklist](docs/PUBLIC_RELEASE_CHECKLIST.md).

### Company deployment status

The code contains a real Graph connector and a draft admin-consent flow, but the one-command enterprise installation is not yet complete. It requires company identity configuration, Graph permission checks, a company-owned storage location, a production credential such as a certificate or managed identity, an approved model, and an authenticated SOC API integration. The current installer deliberately rejects `CONNECTOR_MODE=real` so an incomplete deployment cannot be mistaken for a working company scan. See [Real Graph onboarding](docs/RUNBOOK.md#real-graph-onboarding) for the development checklist. Do not add company secrets or exported mail responses to GitHub.

Useful commands:

```bash
make scenario NAME=credential-phishing
make scenario NAME=account-takeover
make test
make integration
make e2e
make benchmark
make notebooks
make down
```

## Architecture

```text
SOC product :3000 --------+
                           |
Validation lab :3002 -----+--> FastAPI API :8000 ---- signed JWT/JWKS ---- Mock OIDC + Graph :8081
        |                                      |
        v                                      | delta pages / MFA / risk
PostgreSQL 17 <---- SKIP LOCKED worker <-------+
   forced RLS          |
                      v
             joblib/ONNX model bundle
```

- `apps/web`: Next.js 16 App Router dashboard, TanStack Query, Recharts, Vitest, and Playwright.
- `services/simulator`: separate target-specific validation lab with live run stages, score telemetry, canonical components, and persisted run history.
- `services/api`: authenticated FastAPI API, tenant context, stable errors, metrics, health, and OpenTelemetry hooks.
- `services/worker`: durable PostgreSQL queue, Graph delta ingestion, daily aggregation, scoring, retry, recovery, and retention.
- `services/mock_graph`: two isolated tenants, 100 users each, 90 days of history, live mail every two seconds, and controllable failures/attacks.
- `packages/ml`: privacy-safe parsing, versioned feature contracts, training, evaluation, inference, and export.
- `db`: Alembic schema, tenant-first indexes, forced RLS policies, and non-bypass application role.

The real Graph adapter is selected with `CONNECTOR_MODE=real`. It uses tenant-specific client credentials, exact `$select` projections, immutable IDs, pagination, delta checkpoints, `Retry-After`, and optional Entra risky-user data. Live tenant tests remain opt-in until credentials and admin consent are provided.

## Data and model workflow

```bash
make data          # download/checksum and build metadata-only Parquet features
make train         # train candidates, enforce gates, export a versioned bundle
make notebooks     # Papermill execution plus HTML reports
```

Raw SpamAssassin and Enron archives, generated Parquet, reports, and model artifacts are local-only and ignored by Git. The five notebooks cover integrity/privacy, EDA/leakage, email-model iterations, behavioral anomaly/hybrid tuning, and final explanation/export parity.

`make demo` may build an explicitly marked demo model. Production/release workflows reject a bundle unless its manifest is approved. An approved bundle contains joblib and ONNX models, feature schema, hybrid weights, thresholds, metrics, feature importances, manifest, and model card. Runtime uses the checksum-verified ONNX artifact when available and falls back to joblib; export tests enforce numerical parity.

A fresh GitHub clone generates `rules-demo-1`, which has no measured precision and is for local demonstration only. This development workspace also has an optional `0.3.1-precision` artifact in `artifacts/models/v3-precision-20260923-r2`. On the untouched chronological email holdout it measured 87.70% precision, 84.70% recall, 0.8735 PR-AUC, and 0.0730 Brier loss. It remains deliberately unapproved because the training corpus is legacy SpamAssassin rather than labelled Microsoft 365 compromise data. Model artifacts are ignored by Git, so a company installer must obtain a separately published, approved bundle before real scans are enabled.

Dataset sources, limitations, and privacy boundaries are described in the [data card](docs/DATA_CARD.md). Local dataset files and manifests are not included in this public source release.

## Security and tenancy

- Tenant identity comes only from a validated `tid` JWT claim; request-supplied tenant IDs are never authorization inputs.
- Every business table contains `tenant_id`, enables and forces RLS, and is queried through a transaction-scoped `app.tenant_id`.
- The application database role neither owns tables nor bypasses RLS.
- Connector credentials are encrypted with `TOKEN_ENCRYPTION_KEY`; production mode refuses mock/default secrets.
- Admin-consent state is signed, expiring, tenant-bound, and replay-protected.
- Logs use request IDs and redacted tenant identifiers.
- Simulator administration is localhost-only and unavailable unless `CONNECTOR_MODE=mock`.
- The shipped-product UI never exposes scenario controls. Validation traffic is launched only from port 3002 and enters through Mock Graph, so the product observes the same connector and scoring path used by real data.

## Verification

```bash
make test          # Ruff, mypy, pytest, frontend lint/unit tests
make integration   # PostgreSQL migrations, RLS and API/worker integration
make e2e           # signed login, isolation, live mail, scenario, feedback, recovery
make benchmark     # API p95, event throughput, update delay
```

CI additionally checks migration drift, OpenAPI-generated TypeScript drift, notebook smoke execution, Docker Compose, dependency audits, Gitleaks, Trivy, SBOMs, and AMD64/ARM64 image builds.

An earlier local acceptance run passed 51 unit tests at 71.21% coverage, 6 PostgreSQL integration tests, Playwright E2E, all 5 notebooks, dependency audits, and fixable high/critical Trivy gates. It measured 6.75 ms read p95, 4,718.3 metadata events/minute, and 465.86 MiB core Compose memory. Those figures are historical local evidence, not a claim that the current public commit has passed every CI gate or has been validated on a real tenant.

The end-of-study evidence report is generated at `output/pdf/m365-risk-offline-demo-evidence-report.pdf`. It includes 12 vector architecture/UML diagrams, 14 live behavior captures, model graphs, acceptance evidence, and release posture. Editable standalone SVG versions of every diagram are exported under `output/diagrams/`.

## Releases and rollback

GitHub Actions are defined in `.github/workflows`:

- `ci.yml`: pull-request/main quality, security, integration, notebook, and E2E gates.
- `models.yml`: manual full-data training and immutable approved-model artifact publication.
- `release-local.yml`: tag-triggered multi-architecture local release bundle with checksums and SBOMs.

Local production-like packaging and rollback:

```bash
make release-local VERSION=v0.1.0
scripts/install-local.sh releases/v0.1.0
make rollback
```

Installation chooses the host architecture, backs up PostgreSQL, migrates, performs health/E2E smoke checks, and retains the previous release. Azure deployment is intentionally outside this release.

## Configuration and operations

Copy `.env.example` and replace every production secret. Optional observability services are enabled with:

```bash
docker compose --profile observability up -d
```

This starts the OpenTelemetry Collector, Prometheus, and Grafana in addition to the core services. Health endpoints are `/health/live` and `/health/ready`; protected Prometheus metrics are at `/metrics`.

See the [architecture](docs/ARCHITECTURE.md), [threat model](docs/THREAT_MODEL.md), [operations runbook](docs/RUNBOOK.md), [data card](docs/DATA_CARD.md), and [implementation rationale](docs/IMPLEMENTATION_PLAN.md). Personal reports, meeting material, and the original internship brief are intentionally excluded from the public source release.
