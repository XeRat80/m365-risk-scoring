# Read-only scan of a real Microsoft tenant

This collector runs on a company-controlled macOS/Linux machine. It calls Microsoft Graph directly; it does **not** scan the demo PostgreSQL database or need the SOC dashboard. Send this procedure to the Microsoft 365/Entra IT administrator, not HR unless HR is authorized to administer the tenant. We have not yet validated a run against a company tenant.

## 1. IT administrator preparation

Create a single-tenant Entra app registration and grant **application** permissions with tenant admin consent. Use a short-lived app secret for the pilot and rotate/revoke it afterward. Required for the directory: `User.Read.All`. Grant only the signal families approved for the pilot:

| Signal | Application permission | Graph path |
| --- | --- | --- |
| User and account status | `User.Read.All` | `/users` |
| Directory role assignments | `RoleManagement.Read.Directory` | `/roleManagement/directory/roleAssignments` |
| MFA registration | `AuditLog.Read.All` | `/reports/authenticationMethods/userRegistrationDetails` |
| Sign-ins | `AuditLog.Read.All` | `/auditLogs/signIns` |
| Entra risky users | `IdentityRiskyUser.Read.All` + applicable Entra licence | `/identityProtection/riskyUsers` |
| Inbox metadata/headers | `Mail.ReadBasic.All` | `/users/{id}/mailFolders/inbox/messages/delta` |
| Security alerts | `SecurityAlert.Read.All` + provider licence | `/security/alerts_v2` |

Microsoft references: [app-only authentication](https://learn.microsoft.com/en-us/graph/auth-v2-service), [mail delta](https://learn.microsoft.com/en-us/graph/api/message-delta?view=graph-rest-1.0), [MFA registration](https://learn.microsoft.com/en-us/graph/api/authenticationmethodsroot-list-userregistrationdetails?view=graph-rest-1.0), [risky users](https://learn.microsoft.com/en-us/graph/api/riskyuser-list?view=graph-rest-1.0), [security alerts](https://learn.microsoft.com/en-us/graph/api/security-list-alerts_v2?view=graph-rest-1.0).

Restrict the mailbox scope using [Exchange Application RBAC](https://learn.microsoft.com/en-us/exchange/permissions-exo/application-rbac) for a pilot. The `Mail.ReadBasic.All` grant is broad unless scoped. The collector never requests subject, body, preview or attachment bytes. Graph may still return sensitive values in raw headers and alert evidence **in process memory**; the collector derives features and does not write those raw responses. Review this boundary with the company's security/privacy owner before authorizing access.

## 2. New-machine setup and check

Requirements: Git, Docker and OpenSSL. Docker must be running. No host Python, PostgreSQL or dashboard installation is needed.

```bash
git clone https://github.com/XeRat80/m365-risk-scoring.git
cd m365-risk-scoring
./scripts/setup-real-scan.sh
./scripts/real-scan.sh check TENANT_UUID CLIENT_UUID PILOT_USER_OBJECT_UUID
```

The `check` command prompts for the app secret without echoing it. It tests the directory and optional sources, including one mailbox, and prints source coverage. `HTTP 403` generally means missing consent, licence or access scope; it is not a zero-risk result. Do not put the secret on the command line, in `.env`, in GitHub, or in a shared chat.

## 3. Collect and inspect

```bash
./scripts/real-scan.sh scan TENANT_UUID CLIENT_UUID PILOT_USER_OBJECT_UUID pilot-01
python3 -m json.tool private/scans/pilot-01/manifest.json
```

After approving the pilot scope, an explicit full-tenant run is:

```bash
./scripts/real-scan.sh scan TENANT_UUID CLIENT_UUID all-users tenant-01
```

Files remain under `private/scans/RUN_NAME/` on that machine: `manifest.json` (coverage and failures), `user_features.jsonl` (pseudonymous per-user metadata features), and `mail_features.jsonl` (pseudonymous per-message model header features). `private/collector.key` keeps pseudonyms stable across scans; back it up in the company's secret store. All are ignored by Git. Treat them as confidential, even without names or content.

This is **collection and feature engineering**, not a live SOC score. It does not feed the PostgreSQL worker, train or validate a model, or certify phishing detection. SPF/DKIM/DMARC are marked unavailable because an untrusted message header is not a trusted transport verdict. For continuous SOC deployment, company OIDC, private database, approved model and worker/Graph integration still require tenant-specific validation. The local `scan_cli.py` command is a different path: it asks the installed API/worker to scan and then exports features from PostgreSQL.
