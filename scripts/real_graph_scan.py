"""Read-only, database-free Microsoft Graph collection on a company-owned machine.

Only derived features and source coverage are written. Raw Graph responses, mail
headers, addresses, IPs, message content, tokens and credentials are never saved.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import hashlib
import hmac
import json
import os
import stat
import sys
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from packages.ml.m365risk_ml.features import graph_message_features
from services.api.app.config import Settings
from services.api.app.connectors import RealGraphConnector


class ScanError(Exception):
    pass


def private_key(path: Path) -> bytes:
    if not path.is_file():
        raise ScanError(f"Missing private pseudonym key: {path}. Run ./scripts/setup-real-scan.sh")
    if os.name == "posix" and path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ScanError(f"Pseudonym key permissions are too broad: {path} (use chmod 600)")
    key = path.read_bytes().strip()
    if len(key) < 32:
        raise ScanError("Pseudonym key must contain at least 32 random bytes")
    return key


def pseudonym(key: bytes, kind: str, value: object) -> str:
    return hmac.new(key, f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()


def source_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code} (check Graph consent, licence, or query support)"
    if isinstance(exc, httpx.TransportError):
        return "network/TLS error (check Microsoft Graph connectivity)"
    return type(exc).__name__


async def optional_source(name: str, call: Any, coverage: dict[str, dict[str, Any]]) -> list[dict[str, Any]] | None:
    try:
        rows = await call()
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        coverage[name] = {"status": "unavailable", "reason": source_error(exc)}
        return None
    coverage[name] = {"status": "available", "records": len(rows)}
    return rows


def mail_features(message: dict[str, Any], user_id: str, key: bytes) -> dict[str, Any] | None:
    if "@removed" in message or not message.get("id") or not message.get("receivedDateTime"):
        return None
    # This function discards raw headers and addresses after deriving metadata.
    safe, model = graph_message_features(message, user_id, key.hex())
    return {
        "mail_id": pseudonym(key, "mail", message["id"]),
        "received_at": safe["received_at"],
        "external_sender": safe["external_sender"],
        "has_attachments": safe["has_attachments"],
        "reply_to_domain_mismatch": safe["reply_to_domain_mismatch"],
        "from_sender_mismatch": safe["from_sender_mismatch"],
        "sender_domain_hash": safe["sender_domain_hash"],
        "authentication_status": "unavailable_untrusted_header",
        "model_features": model,
    }


def derive_user_features(
    user_id: str,
    key: bytes,
    registration: dict[str, Any] | None,
    risky: dict[str, Any] | None,
    admin_ids: set[str] | None,
    sign_ins: list[dict[str, Any]] | None,
    alerts: list[dict[str, Any]] | None,
    mails: list[dict[str, Any]] | None,
    *,
    captured_at: str,
) -> dict[str, Any]:
    own_sign_ins = [row for row in sign_ins or [] if str(row.get("userId")) == user_id]
    own_alerts = []
    for alert in alerts or []:
        if any(
            isinstance(state, dict) and str(state.get("userId")) == user_id
            for state in alert.get("userStates") or []
        ):
            own_alerts.append(alert)
    countries = {
        str((row.get("location") or {}).get("countryOrRegion"))
        for row in own_sign_ins
        if isinstance(row.get("location"), dict)
        and (row.get("location") or {}).get("countryOrRegion")
    }
    failed = sum(
        isinstance(row.get("status"), dict)
        and int((row.get("status") or {}).get("errorCode") or 0) != 0
        for row in own_sign_ins
    )
    unmanaged = sum(
        isinstance(row.get("deviceDetail"), dict)
        and (row.get("deviceDetail") or {}).get("isManaged") is False
        for row in own_sign_ins
    )
    severity = Counter(
        str(row.get("severity") or "unknown").lower()
        for row in own_alerts
        if str(row.get("status") or "").lower() != "resolved"
    )
    return {
        "sample_id": pseudonym(key, "user", user_id),
        "captured_at": captured_at,
        "feature_version": "real-graph-collection-v1",
        "features": {
            "mfa_registered": registration.get("isMfaRegistered") if registration else None,
            "mfa_capable": registration.get("isMfaCapable") if registration else None,
            "entra_risk_level": risky.get("riskLevel") if risky else None,
            "has_active_directory_role": user_id in admin_ids if admin_ids is not None else None,
            "sign_in_count_30d": len(own_sign_ins) if sign_ins is not None else None,
            "failed_sign_in_count_30d": failed if sign_ins is not None else None,
            "distinct_sign_in_countries_30d": len(countries) if sign_ins is not None else None,
            "unmanaged_device_sign_in_count_30d": unmanaged if sign_ins is not None else None,
            "open_provider_alert_count_30d": sum(severity.values()) if alerts is not None else None,
            "open_provider_alerts_by_severity_30d": dict(severity) if alerts is not None else None,
            "mail_count": len(mails) if mails is not None else None,
            "mail_reply_to_mismatch_count": sum(bool(row["reply_to_domain_mismatch"]) for row in mails or []) if mails is not None else None,
            "mail_from_sender_mismatch_count": sum(bool(row["from_sender_mismatch"]) for row in mails or []) if mails is not None else None,
        },
    }


def write_private_json(path: Path, value: object) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def write_private_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


async def collect(args: argparse.Namespace, key: bytes, secret: str) -> dict[str, Any]:
    settings = Settings(
        _env_file=None,
        connector_mode="real",
        token_encryption_key=key.hex(),
        pseudonymization_key=key.hex(),
        metrics_key=key.hex(),
        graph_client_id=str(args.client_id),
        graph_client_secret=secret,
    )
    connector = RealGraphConnector(settings)
    tenant_id = uuid.UUID(args.tenant_id)
    coverage: dict[str, dict[str, Any]] = {}
    captured_at = datetime.now(UTC).isoformat()
    try:
        try:
            # Request only IDs and account state. The ordinary connector joins
            # roles and reads names/UPNs, neither needed in this local export.
            users = await connector._collection(
                "https://graph.microsoft.com/v1.0/users?$select=id,accountEnabled",
                tenant_id,
            )
        except (httpx.HTTPError, RuntimeError) as exc:
            raise ScanError(f"Directory collection failed: {source_error(exc)}") from exc
        coverage["users"] = {"status": "available", "records": len(users)}
        role_rows = await optional_source(
            "directory_roles",
            lambda: connector._collection(
                "https://graph.microsoft.com/v1.0/roleManagement/directory/roleAssignments"
                "?$select=principalId", tenant_id,
            ),
            coverage,
        )
        selected = [row for row in users if str(row.get("id")) == args.user_id] if args.user_id else users
        if args.user_id and not selected:
            raise ScanError("Requested user ID was not found in this tenant")
        if args.command == "check":
            selected = selected[:1]
        registrations = await optional_source(
            "mfa", lambda: connector.registration_details(tenant_id), coverage
        )
        risky_users = await optional_source(
            "risky_users", lambda: connector.risky_users(tenant_id), coverage
        )
        since = datetime.now(UTC) - timedelta(days=30)
        sign_ins = await optional_source(
            "sign_ins", lambda: connector.sign_ins(tenant_id, since), coverage
        )
        alerts = await optional_source(
            "security_alerts", lambda: connector.security_alerts(tenant_id, since), coverage
        )
        registration_by_id = {str(row.get("id")): row for row in registrations or []}
        risk_by_id = {str(row.get("id")): row for row in risky_users or []}
        admin_ids = (
            {str(row["principalId"]) for row in role_rows if row.get("principalId")}
            if role_rows is not None else None
        )
        user_rows: list[dict[str, Any]] = []
        mail_rows: list[dict[str, Any]] = []
        mailbox_failures = 0
        for index, user in enumerate(selected, start=1):
            user_id = str(user["id"])
            try:
                messages, _ = await connector.messages(tenant_id, user_id)
                safe_mails = [
                    safe for message in messages
                    if (safe := mail_features(message, user_id, key)) is not None
                ]
            except (httpx.HTTPError, RuntimeError, ValueError, KeyError) as exc:
                mailbox_failures += 1
                safe_mails = None
                print(f"Mailbox {index}/{len(selected)} unavailable: {source_error(exc)}", file=sys.stderr)
            if safe_mails is not None:
                mail_rows.extend({"sample_id": pseudonym(key, "user", user_id), **row} for row in safe_mails)
            user_rows.append(derive_user_features(
                user_id, key, registration_by_id.get(user_id), risk_by_id.get(user_id),
                admin_ids, sign_ins, alerts, safe_mails, captured_at=captured_at,
            ))
        coverage["mail"] = {
            "status": "available" if mailbox_failures == 0 else "partial_or_unavailable",
            "mailboxes_attempted": len(selected),
            "mailboxes_failed": mailbox_failures,
            "records": len(mail_rows),
            "authentication_verdicts": "unavailable: raw Authentication-Results is not trusted",
        }
        result: dict[str, Any] = {
            "schema": "real-graph-collection-v1",
            "captured_at": captured_at,
            "tenant_hash": pseudonym(key, "tenant", tenant_id),
            "mode": "check" if args.command == "check" else "collection",
            "scope": "one_user" if args.user_id else "all_users",
            "selected_users": len(selected),
            "check_mailbox_scope": "one mailbox only" if args.command == "check" else None,
            "source_coverage": coverage,
            "model_score_generated": False,
            "production_model_approved": False,
            "notes": [
                "Read-only Graph collection; not a SOC score or incident verdict.",
                "Unavailable sources are null, never assumed safe.",
                "No message body, subject, preview, attachment bytes, raw headers, raw IDs, or IPs are saved.",
            ],
        }
        if args.command == "scan":
            output = args.out
            if output.exists():
                raise ScanError(f"Output path already exists: {output}; choose a new private directory")
            output.mkdir(mode=0o700, parents=True)
            os.chmod(output, 0o700)
            write_private_jsonl(output / "user_features.jsonl", user_rows)
            write_private_jsonl(output / "mail_features.jsonl", mail_rows)
            write_private_json(output / "manifest.json", result)
        return result
    finally:
        await connector.aclose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Direct, read-only Microsoft Graph collection")
    parser.add_argument("command", choices=("check", "scan"))
    parser.add_argument("--tenant-id", required=True, help="Microsoft Entra tenant UUID")
    parser.add_argument("--client-id", required=True, help="Read-only application (client) UUID")
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--user-id", help="Pilot user object UUID")
    scope.add_argument("--all-users", action="store_true", help="Explicitly scan all tenant users")
    parser.add_argument("--key-file", type=Path, default=Path("private/collector.key"))
    parser.add_argument("--out", type=Path, help="New local private output directory (scan only)")
    args = parser.parse_args()
    if args.command == "scan" and args.out is None:
        parser.error("scan requires --out")
    if args.command == "check" and args.out is not None:
        parser.error("check does not write output; omit --out")
    try:
        uuid.UUID(args.tenant_id)
        uuid.UUID(args.client_id)
        if args.user_id:
            uuid.UUID(args.user_id)
        key = private_key(args.key_file)
        secret = os.environ.get("M365_GRAPH_CLIENT_SECRET") or getpass.getpass(
            "Microsoft Graph application secret (not stored): "
        )
        if not secret:
            raise ScanError("A Graph application secret is required")
        result = asyncio.run(collect(args, key, secret))
        print(json.dumps(result, indent=2))
        return 0
    except (ScanError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
