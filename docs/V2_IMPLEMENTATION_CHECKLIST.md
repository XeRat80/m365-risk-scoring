# V2 risk architecture implementation checklist

This file is the auditable execution sheet for the V2 work. A checked item means the implementation exists and its stated verification has passed. Demo/synthetic verification is never presented as real Microsoft 365 security validation.

## 0. Scope and safety

- [x] Preserve the existing V1 path for comparison and rollback.
- [x] Keep subject, body, preview, attachment bytes, plaintext addresses, and plaintext IPs out of persistence.
- [x] Define five non-duplicated final components: email threat, identity compromise, MFA exposure, privilege exposure, and endpoint threat.
- [x] Treat unavailable evidence as unavailable, never as safe.
- [x] Keep production promotion blocked without representative labelled Microsoft 365 validation data.

## 1. Versioned contracts

- [x] Add normalized `MailObservationV2` authentication and sender-integrity fields.
- [x] Add `SignInObservationV1` for privacy-safe Entra sign-in telemetry.
- [x] Add `SecurityAlertObservationV1` for optional Defender evidence.
- [x] Add `UserFeatureWindowV2` with canonical features, availability, provenance, and versions.
- [x] Add `UserRiskGraphV2` API response contract.
- [x] Add schema validation tests, including unknown/unavailable states.

## 2. Persistence and tenant isolation

- [x] Add tenant-scoped sign-in observation storage.
- [x] Add tenant-scoped security-alert observation storage.
- [x] Add tenant-scoped V2 feature-window storage.
- [x] Add indexes and composite tenant foreign keys.
- [x] Enable and force PostgreSQL RLS for every new table.
- [x] Add migration and RLS integration tests.
- [x] Add retention for sign-ins, alerts, and V2 feature windows.

## 3. Connectors and ingestion

- [x] Extend the connector contract with time-bounded sign-in ingestion.
- [x] Extend the connector contract with optional security-alert ingestion.
- [x] Implement real Graph sign-ins using least-privilege, bounded projections.
- [x] Implement optional real Graph security alerts.
- [x] Implement deterministic mock sign-ins and alerts for offline tests.
- [x] Correct the MFA registration-report permission declaration.
- [x] Preserve paging, retry, throttling, idempotency, and partial-failure behavior.
- [x] Add connector contract tests.

## 4. Canonical feature computation

- [x] Consolidate compauth/DMARC/DKIM/SPF into one `auth_integrity` input.
- [x] Consolidate sender/reply context without recounting DMARC alignment.
- [x] Fix train/serve recipient-count equivalence.
- [x] Compute local UEBA time, location, network, device, authentication, and application anomalies.
- [x] Consolidate Entra provider evidence once, without adding it to the same local evidence.
- [x] Compute explicit MFA and privilege exposure states.
- [x] Compute optional endpoint threat with availability status.
- [x] Compute daily email threat using a top-k aggregation rather than simultaneous max/mean/count inputs.
- [x] Add deterministic unit tests for every canonical feature and deduplication rule.

## 5. Model and dataset compatibility

- [x] Add V1-to-V2 dataset adapter with modern authentication fields marked `unknown`.
- [x] Add V2 dataset preflight validation and compatibility reporting.
- [x] Add missingness/availability masks to V2 training evaluation and inference scoring.
- [x] Train and compare transparent baseline, logistic, and nonlinear candidates where the data supports them.
- [x] Calibrate probabilities and evaluate chronological/grouped holdouts.
- [x] Report metrics separately for imported, generated, and real-labelled sources.
- [x] Keep any model trained without real Microsoft 365 labels explicitly unapproved.
- [x] Verify Python/portable-runtime parity and immutable artifact hashes.

## 6. API and investigation graph

- [x] Add user graph endpoint with nodes, edges, canonical components, evidence, coverage, and versions.
- [x] Ensure graph responses contain pseudonymous metadata only.
- [x] Add API authorization and tenant-isolation tests.
- [x] Add a Field Data Graph page to the application navigation.
- [x] Add employee selection, evidence-path filtering, and node detail inspection.
- [x] Clearly distinguish observation nodes, relationships, canonical features, and final components.
- [x] Display unavailable and insufficient-history states.
- [x] Add responsive and accessibility tests.

## 7. Verification and release posture

- [x] Run Python formatting, linting, type checks, and unit tests.
- [x] Run database migrations and tenant-isolation integration tests.
- [x] Regenerate the OpenAPI TypeScript contract.
- [x] Run frontend lint, unit tests, and production build.
- [x] Run browser verification of graph workflows at desktop and narrow widths.
- [x] Run offline retraining and record provenance and failed/passed gates.
- [x] Update model card, architecture, runbook, and threat model.
- [x] Record remaining real-tenant validation work without falsely checking it complete.

## External validation that cannot be simulated

- [ ] Obtain an authorized Microsoft 365 test tenant and restrict access to dedicated test mailboxes.
- [ ] Collect representative, privacy-reviewed, labelled Microsoft 365 events.
- [ ] Execute read-only shadow evaluation and analyst adjudication.
- [ ] Pass agreed precision, recall, calibration, false-alert, drift, and latency gates.
- [ ] Approve and sign a production model bundle only after those gates pass.
