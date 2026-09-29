# Microsoft 365 User Risk Scoring Platform - implementation plan

## Outcome and scope

Build a deployable, metadata-only, multi-tenant MVP with a Next.js dashboard, FastAPI API/worker, PostgreSQL Row-Level Security (RLS), a hybrid ML scoring engine, Microsoft Graph synchronization, an offline Graph/OIDC simulator, and rollback-capable local Docker releases. Azure deployment is intentionally excluded from this release. The system must never persist message bodies, previews, unique bodies, or attachment content.

The first production slice is: onboard one tenant -> synchronize users, MFA posture, and selected message metadata -> extract features -> calculate a user score with explanations -> show it in the dashboard -> record analyst feedback.

## Decisions to lock before coding

1. Use one monorepo and one Python codebase shared by API and worker.
2. Start with calibrated logistic regression and compare a histogram gradient-boosting candidate only when time-split PR-AUC, calibration, and portable ONNX export improve materially.
3. Use Isolation Forest (or robust z-score baselines first) for user behavior anomaly scoring.
4. Keep the five score components and initial weights from the brief behind versioned configuration: email 0.35, behavior 0.20, Entra 0.20, MFA/posture 0.15, privilege/exposure 0.10.
5. Use app-only Graph access for scheduled tenant-wide sync. Request only `Mail.ReadBasic.All`, `User.Read.All`, `AuditLog.Read.All`, `RoleManagement.Read.Directory`, optional `IdentityRiskyUser.Read.All`, and optional `SecurityAlert.Read.All`. All application permissions require admin consent. Restrict mailboxes further with Exchange application access controls where the customer supports them.
6. Use `organizations` for onboarding, then the concrete tenant authority after discovering the `tid`. Validate signature, audience, issuer-to-tenant binding, nonce/state, and tenant allow-list status.
7. Never authorize from a client-supplied `tenant_id`. Derive tenant context from the verified token and set it in the database transaction before any query.

## Repository shape

```text
apps/web/                 Next.js dashboard
services/api/             FastAPI routes, auth, service layer
services/worker/          sync, aggregation, scoring, retention jobs
packages/ml/              parsers, feature contracts, training, inference
packages/contracts/       OpenAPI-generated/shared types
db/migrations/            schema, RLS policies, indexes
infra/                    Docker Compose, observability, local release tooling
tests/                    unit, integration, tenant-isolation, privacy
data/                     checksums and local-only datasets
docs/                     architecture, runbooks, model/data cards
```

## Data contracts

Create explicit versioned schemas before model work:

- `EmailMetadataV1`: immutable message ID hash, pseudonymous user/sender/domain IDs, received time, recipient counts, external flag, attachment boolean, importance, selected authentication/routing header features. No subject or body fields.
- `UserDailyFeaturesV1`: the fields in `data/synthetic/m365_user_daily.csv.gz`, plus a `feature_version` and calculation timestamps.
- `RiskScoreV1`: score 0-100, level, component contributions, top factors, model/scoring version, calculated time.
- `AnalystFeedbackV1`: risk ID, verdict, optional comment, actor, time, and immutable audit event.

Use time-based dataset splits to avoid leakage. Fit sender/domain baselines and scalers on training history only. Keep SpamAssassin source batches grouped during splitting so near-duplicate messages cannot cross train/test boundaries.

## Delivery sequence and gates

### Weeks 1-2 - foundation

- Initialize monorepo, local Docker Compose, lint/test tooling, ADRs, threat model, and data classification.
- Finalize Graph permissions and consent UX.
- Define Pydantic, SQL, and ML feature contracts.

Gate: containers start locally; CI runs; privacy contract rejects forbidden fields (`body`, `bodyPreview`, `uniqueBody`, attachment bytes).

### Weeks 3-5 - data pipeline

- Parse SpamAssassin/Enron with Python's email parser using headers only.
- Normalize dates/domains/authentication results; hash identifiers with a tenant-scoped HMAC key.
- Produce Parquet feature tables and data-quality reports.
- Validate the provided synthetic generator at small, demo, and stress scales.

Gate: deterministic pipeline, schema validation, corpus counts, missingness report, no-body-storage test.

### Weeks 6-8 - email model

- Build rule baseline and logistic regression.
- Evaluate precision, recall, F1, PR-AUC, confusion matrix, reliability curve, Brier score, and threshold trade-offs.
- Compare histogram gradient boosting only after the baseline is reproducible.
- Export a versioned model bundle with feature schema, thresholds, metrics, and model card.

Gate: reproducible evaluation from a clean checkout and calibrated probabilities; no random row split leakage.

### Weeks 9-11 - user risk engine

- Compute 7/30-day rolling aggregates and per-user/peer baselines.
- Implement behavior anomaly score and the versioned hybrid formula.
- Generate component-level contributions and stable human-readable explanations.
- Evaluate top-5% precision, top-10% recall, false alerts per 100 users, stability, and detection delay on synthetic scenarios.

Gate: golden test cases reproduce scores exactly and every high/critical result has factors.

### Weeks 12-15 - Microsoft Graph connector

- Implement admin-consent start/callback with state/nonce and encrypted credentials.
- Sync user basics, `userRegistrationDetails`, and optional `riskyUsers`.
- Synchronize mail folder changes using delta links, exact `$select` fields, paging, retry/backoff, and resumable checkpoints.
- Build a mock Graph service covering pagination, 429/Retry-After, expired delta tokens, partial failures, and P2-unavailable mode.

Gate: real or mock tenant completes initial and incremental sync; captured payload tests prove forbidden content is not persisted.

### Weeks 16-18 - API and database

- Add Alembic migrations for tenants, users, connections, sync jobs/checkpoints, email features, daily aggregates, scores, factors, feedback, model versions, and audit logs.
- Apply RLS to every business table; indexes begin with `tenant_id`.
- Implement the nine REST endpoints in the brief with idempotency for job starts and cursor pagination for lists.

Gate: cross-tenant negative tests pass for every repository/API path, including background jobs and raw SQL; OpenAPI contract is stable.

### Weeks 19-21 - dashboard

- Implement tenant onboarding/status, risk overview, searchable users, user detail/history, factor explanations, sync status, and feedback.
- Add accessible loading/empty/error states and explicit data freshness timestamps.

Gate: an analyst can go from critical KPI to user evidence and submit feedback; keyboard/accessibility smoke tests pass.

### Weeks 22-24 - hardening and MLOps

- Add model registry metadata, scheduled retraining evaluation (not automatic promotion), drift/data-quality monitoring, OpenTelemetry, Prometheus/Grafana, retention deletion jobs, backup/restore tests, and secret rotation guidance.
- Add dependency/container scanning, multi-architecture image validation, SBOMs, and versioned local Docker release/rollback automation.

Gate: load, retry, recovery, retention, privacy, and tenant-isolation suites pass; dashboards/alerts cover sync and scoring failures.

### Weeks 25-26 - validation and handoff

- Run the complete demo, performance/security evaluation, limitations review, deployment rehearsal, and restore rehearsal.
- Finish architecture diagrams, API docs, data/model cards, operations runbook, report, and presentation.

Gate: definition of done from the PDF is demonstrated end to end and deployment is reproducible by another engineer.

## Database/RLS pattern

All tenant business tables include `tenant_id uuid not null`. For each request/worker transaction:

```sql
select set_config('app.tenant_id', :verified_tenant_id, true);
```

Policies compare `tenant_id` to `current_setting('app.tenant_id', true)::uuid`. The application role must not own tables and must not have `BYPASSRLS`; force RLS on protected tables. Connection-pool cleanup and missing-context failures require tests.

## Graph collection contract

For messages, request only identifiers and metadata needed for features, including `internetMessageHeaders` via `$select`; never request `body`, `bodyPreview`, `uniqueBody`, or attachment content. Use immutable IDs and folder-scoped delta links. Preserve the full returned `@odata.nextLink`/`@odata.deltaLink` rather than parsing their tokens.

Standard mode works without risky-user data. Enhanced mode adds `GET /identityProtection/riskyUsers`, requires `IdentityRiskyUser.Read.All`, and depends on Microsoft Entra ID P2. MFA posture uses `GET /reports/authenticationMethods/userRegistrationDetails` with application permission `AuditLog.Read.All`. Optional Defender evidence uses `SecurityAlert.Read.All`.

## Test matrix

- Data: archive counts, malformed email handling, timezone normalization, missing headers, duplicate grouping, schema drift.
- ML: deterministic split/training, calibration, threshold regression, feature-order mismatch, missing feature behavior.
- Security: forged/wrong-audience/wrong-issuer tokens, replayed OAuth state, cross-tenant IDs, RLS absent context, secret redaction.
- Privacy: forbidden field/property assertions at connector, DTO, persistence, logs, traces, exports, and backups.
- Graph: paging, throttling, retry-after, token expiration, consent revoked, P2 absent, mailbox unavailable, delta reset.
- Product: empty/new tenant, stale sync, partial connector health, score explanations, feedback auditability.
- Performance: per-1,000-message sync time, p95 API latency, scoring throughput, database growth, and worker backpressure.

## First 10 implementation tickets

1. Bootstrap monorepo and Docker Compose.
2. Add feature/privacy Pydantic contracts and forbidden-field tests.
3. Add SpamAssassin header-only parser plus corpus-count test.
4. Add Enron metadata sampler and time-split manifest.
5. Add Parquet feature pipeline and data-quality report.
6. Train/evaluate calibrated logistic baseline.
7. Add hybrid scorer with golden explanation tests.
8. Add PostgreSQL schema and forced-RLS integration harness.
9. Add mock Graph server with delta/throttling fixtures.
10. Build one vertical API/dashboard slice using synthetic data.

This order removes the highest uncertainty early: privacy-safe features, label limitations, RLS correctness, and Graph permission/licensing constraints.
