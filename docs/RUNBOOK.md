# Operations runbook

## Bootstrap and local demo

For a fresh clone, use `./scripts/install.sh`. It requires Docker, curl and OpenSSL on the host; it performs the checks and starts the demo without installing host Python or Node. Run `./scripts/install.sh --check` before installation or `./scripts/doctor.sh --after-start` to diagnose a running installation. The installer preserves an existing `.env` and model bundle.

The commands below are the development workflow for contributors who need local Python, Node, training datasets and notebooks:

```bash
cp .env.example .env
make bootstrap
make data
make train
make demo
```

`make bootstrap` installs/pins Python 3.13 through `uv`, creates `.venv`, syncs hash-locked development dependencies, selects/installs Node 24 on supported macOS hosts, activates pinned pnpm, installs the frozen frontend lockfile, and verifies a running Docker engine.

Check `/health/live`, `/health/ready`, protected `/metrics`, connector health in the dashboard, and `docker compose logs api worker mock-graph`. Enable telemetry with `docker compose --profile observability up -d`.

## Two-window validation workflow

1. Open the SOC product at `http://localhost:3000`. This window is monitoring-only and contains no scenario controls.
2. Open Signal Forge at `http://localhost:3002` in a second window.
3. Select the tenant, target employee, and exactly one scenario family.
4. Start the targeted validation. The lab injects evidence into Mock Graph; it never writes a score or alert directly into PostgreSQL.
5. Follow the live stages: scenario injection → Mock Graph → connector sync → feature extraction → V2 scoring → target-specific SOC detection.
6. In the product window, open the target investigation to verify the same mail, identity, MFA, Entra, or endpoint evidence.
7. Use **Reset healthy baseline** before an independent test. Reset removes derived observations and scores, restores healthy mock identity posture, and enqueues a clean synchronization. Validation history is retained.

The default Compose deployment mounts `artifacts/models/v3-precision-20260923-r2` as the active `0.3.1-precision` bundle. Override `MODEL_BUNDLE_PATH` to test another immutable bundle. After a model change, rebuild the Python image, restart API/worker, reset the tenant, and verify 100 low-risk identities with average score 0 before launching a targeted scenario.

The pass condition is target-specific. A risky event for another employee cannot make the current run pass. Mail scenarios require high-risk mail plus an elevated canonical email component; identity, MFA, and Entra scenarios require their corresponding evidence and component instead of duplicating the same fact across multiple inputs.

## Common incidents

- **Job retrying/dead:** inspect its redacted structured log and error field. Check Graph 429/`Retry-After`, revoked consent, mailbox availability, and credentials. A retry uses exponential delay; timed-out running work is recovered after 60 seconds in the MVP worker loop.
- **Expired delta:** the connector discards only the invalid mailbox delta and performs a fresh collection. IDs make replay idempotent.
- **P2 unavailable:** provider identity risk is marked unavailable; it is never converted to a zero/safe value. Other covered components continue in V2 shadow mode.
- **V2 graph unavailable:** run a synchronization, inspect optional sign-in/alert permission errors, then query `/api/v1/users/{user_id}/risk-graph`. A missing source must appear as `unavailable`, not as zero.
- **Stale dashboard:** verify the worker, newest job, data freshness, model integrity, and database pool. A scenario target should update within ten seconds after initial sync.
- **Model load failure:** compare every file with `manifest.json`, verify feature order and weights, and restore the immutable bundle. Never bypass approval in production.
- **Suspected tenant leak:** stop API/worker, preserve audit/log evidence, rotate signing/Graph/master keys, run forced-RLS and composite-FK tests, and notify affected owners.

## Real Graph onboarding

### Continuous collection and SOC closure

The API and recurring worker use the same queue and connector. Keep the worker
running after a manual scan. `SYNC_INTERVAL_SECONDS` controls scheduling; Graph
ingestion delays, retries and scan duration add to detection delay. Mail resumes
delta checkpoints. Sign-ins and alerts use a rolling 30-day query; alerts filter
by `lastUpdateDateTime` to refresh changed alerts. User risk windows still use
observations created in the last 30 days.

The real connector maps alerts_v2 `evidence.userAccount.azureAdUserId` to employees.
Device-only and unmatched alerts are kept in the tenant SOC queue without a user link.
Evidence is reduced in memory to allowed identifiers. Microsoft evidence payloads
can contain sensitive fields, so collection needs company privacy review under a
strict no-content-access policy. Raw evidence is not persisted. See the
[Microsoft schema](https://learn.microsoft.com/en-us/graph/api/resources/security-alert?view=graph-rest-1.0).

`GET /api/v1/alerts` exposes provider status separately from local SOC status.
Analysts and administrators may call `POST /api/v1/alerts/{id}/close` with reason
`resolved`, `false_positive` or `accepted_risk`. Closure is tenant-scoped, audited,
idempotent and preserved during sync. New alert IDs are open. Local closure does
not clear calculated risk or write to Microsoft. Provider-resolved alerts no longer
contribute to the active endpoint component. These API actions support SOC integration;
the local web dashboard exposes this action at `/alerts`. One provider alert linked to
several users creates an observation per user; each observation has its own local closure.

Graph mail message headers can contain a sender-supplied `Authentication-Results`
line. The real connector does not treat this raw line as a trusted SPF, DKIM or
DMARC verdict for V2 scoring. Authentication remains unavailable until a trusted
transport verdict source is integrated; the mock source supplies structured test
verdicts only.


**Current status:** this is a development path, not a one-command company installation. The GitHub installer starts only the mock environment. Before enabling real scans, implement and verify tenant onboarding, production identity and API roles, permission and licence preflight, company-owned storage and credentials, source coverage reporting, and an approved model. The company administrator must explicitly grant Graph permissions; installation alone cannot grant consent.

The default five-second polling interval is for the local development environment.
Each cycle currently fetches the directory, MFA, roles and a rolling sign-in/alert
window again; it has not been benchmarked for a company tenant. A production setup
needs source-specific checkpoints and measured freshness under Graph throttling.

The current code expects `CONNECTOR_MODE=real`, a production issuer/audience, Graph client ID/secret, redirect URI, non-default encryption/metrics/mock-boundary secrets, and an approved model. The requested application permissions include `User.Read.All` for `/users`, `Mail.ReadBasic.All`, `AuditLog.Read.All`, `IdentityRiskyUser.Read.All` (Entra P2), `RoleManagement.Read.Directory`, and `SecurityAlert.Read.All`. Permission/licence preflight and genuinely optional consent scopes remain to be implemented. Complete admin consent as a tenant admin and restrict mailbox scope with Exchange Application RBAC. The current client-secret and mock-dependent Compose configuration are development scaffolding; production needs a company-owned credential store and an independently validated deployment. The callback encrypts a tenant-bound credential copy; the worker never uses a request-supplied tenant ID.

Start with dedicated test users and read-only shadow evaluation. Verify licensing and permissions separately: sign-in/risk evidence may require Entra premium capabilities and endpoint alerts require the corresponding Defender source. Do not promote `shadow-rules-v2` or a retrained bundle until privacy-reviewed Microsoft 365 labels and analyst adjudication pass the documented gates.

## Release, backup, restore, rollback

```bash
ALLOW_DEMO_MODEL=1 make release-local VERSION=demo-test  # demo rehearsal only
scripts/install-local.sh releases/demo-test
make rollback
scripts/restore-local.sh releases/demo-test /absolute/path/to/pre-install.dump
```

Production-like release creation fails unless the model is approved. Installation verifies all checksums, selects the host architecture, loads images, tags the shared Python image for the simulator, backs up PostgreSQL, runs forward-compatible migrations, waits for readiness, and runs authenticated smoke checks. The prior release pointer is retained. Normal rollback starts the previous images against backward-compatible schema; set `RESTORE_DUMP` only when an explicit data restore is required.

The verified local demo package is `releases/0.1.0-demo-j`. It is explicitly non-production because its model manifest is unapproved; use `ALLOW_DEMO_MODEL=1` only for offline rehearsal. The default release command refuses that bundle.

## Secret and key rotation

1. Schedule downtime and back up PostgreSQL.
2. Decrypt each connector secret with the old master key inside a controlled one-off process, re-encrypt with the new key and the same tenant associated data, then atomically replace ciphertext. Rotate the independent pseudonymization key only with a planned identifier re-key migration.
3. Rotate Graph credentials in Microsoft Entra, update encrypted records through re-consent, rotate metrics and simulator boundary secrets, restart services, and revoke old values.
4. Run readiness, authenticated smoke, connector delta, RLS, and log-redaction checks.

Never rotate the master key by simply changing the environment value; existing ciphertext would become undecryptable.
