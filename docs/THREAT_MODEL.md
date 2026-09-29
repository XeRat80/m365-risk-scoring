# Threat model and privacy controls

## Assets and trust boundaries

Protected assets are tenant identity, Graph application credentials, pseudonymous mail metadata, risk scores, analyst feedback, model artifacts, and audit history. Trust boundaries exist at the browser/API token boundary, API/database RLS boundary, worker/Graph boundary, environment/credential store, model bundle loader, and localhost simulator administration interface.

## Principal threats and mitigations

| Threat | Control | Verification |
|---|---|---|
| Forged, wrong-issuer, wrong-audience, expired, or malformed tenant tokens | RS256 JWKS validation with required issuer/audience/time/`tid`; tenant is never read from request data | Auth negative tests |
| Cross-tenant reads/writes or identifiers | Tenant on every business key, forced RLS, non-bypass app role, composite tenant foreign keys, tenant-first indexes | ORM/raw SQL, policy, and cross-reference integration tests |
| OAuth consent CSRF/replay | Signed 10-minute state with tenant, subject, nonce, and JTI; consumed JTI stored in audit log | Tenant-binding and replay tests |
| Secret disclosure | AES-GCM tenant-bound ciphertext; environment master key; no secret logging; production default-secret refusal | Crypto and configuration tests |
| Mail-content overcollection | Exact Graph `$select`; header-only archive reader with byte cap; Pydantic extra-field rejection; forbidden names excluded from persistence | Privacy/parser/connector tests |
| Sign-in location/network overcollection | Raw IP is reduced to IPv4 `/24` or IPv6 `/48` in memory and tenant-keyed HMAC hashed before persistence; app and device IDs are also tenant-keyed hashes | Worker/unit tests and schema inspection |
| Misleading missing evidence | Per-component availability masks; unknown authentication is never pass; V2 score withheld below 60% weighted coverage | Canonical feature tests |
| Double-counted security evidence | Authentication precedence, one sender-context feature, max fusion for local/provider identity evidence, and one top-k email aggregate | V2 deduplication tests |
| Queue duplication or concurrent tenant sync | Idempotency keys, `SKIP LOCKED`, one running job per tenant, advisory lock, unique metadata IDs | Queue and duplicate-delivery tests |
| Graph throttling/failure | `Retry-After`, bounded exponential retry, durable retry schedule, delta restart, dead jobs, timeout recovery | Connector/fault/worker tests |
| Model substitution or schema drift | Manifest hashes, feature-order equality, normalized weights, joblib/ONNX parity, production approval gate | Runtime and training tests |
| Simulator exposure | Host port bound to loopback; admin secret; every admin/Graph endpoint returns 404 outside mock mode | Mock-mode tests and Compose config |
| Sensitive telemetry | Structured logs omit payloads and hash tenant identifiers; spans use redacted tenant/model/job tags | Log review and tests |

## Data classification

- Prohibited: subject, body, body preview, unique body, attachment content/bytes, access tokens, plaintext connector secrets.
- Confidential tenant data: user display name, pseudonymous principal, MFA/Entra posture, pseudonymous sign-in/alert observations, message-derived features, scores, feedback.
- Operational: job identifiers/status, model version, aggregate metrics, redacted tenant hash.
- Public/local research: SpamAssassin and Enron archives, with only metadata copied to processed Parquet.

Analyst feedback must not paste mail content; the dashboard states this at entry. Scores support prioritization and human review only. They must not autonomously disable accounts.

## Residual risks

Public spam labels do not represent Microsoft 365 account compromise, Enron is dated, synthetic user windows are not production ground truth, and directory/risky-user endpoints depend on tenant permissions/licensing. The demo model is therefore explicitly unapproved. A real release needs representative validation, legal/privacy review, Exchange application access controls, secret-manager integration, key rotation, and an approved model bundle.
