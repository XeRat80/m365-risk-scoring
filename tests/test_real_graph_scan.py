from __future__ import annotations

import json
import uuid
from argparse import Namespace
from pathlib import Path

import httpx
import pytest

from scripts import real_graph_scan

TENANT = "00000000-0000-4000-8000-000000000001"
USER = "10000000-0000-4000-8000-000000000001"


def test_derived_mail_features_never_persist_raw_headers_or_addresses() -> None:
    message = {
        "id": "private-message-id",
        "receivedDateTime": "2026-09-30T12:00:00Z",
        "from": {"emailAddress": {"address": "secret.sender@outside.example"}},
        "sender": {"emailAddress": {"address": "secret.sender@outside.example"}},
        "toRecipients": [{"emailAddress": {"address": "employee@company.example"}}],
        "internetMessageHeaders": [
            {"name": "Reply-To", "value": "private-reply@other.example"},
            {"name": "Subject", "value": "private subject"},
            {"name": "Authentication-Results", "value": "spf=pass"},
        ],
    }
    result = real_graph_scan.mail_features(message, USER, b"a" * 32)
    assert result is not None
    serialized = json.dumps(result)
    assert "private" not in serialized
    assert "outside.example" not in serialized
    assert "company.example" not in serialized
    assert result["reply_to_domain_mismatch"] is True
    assert result["authentication_status"] == "unavailable_untrusted_header"


def test_normalized_provider_alert_is_counted_for_affected_user() -> None:
    row = real_graph_scan.derive_user_features(
        USER, b"a" * 32, None, None, None, None,
        [{"id": "alert-1", "severity": "high", "status": "new",
          "userStates": [{"userId": USER}]}],
        None, captured_at="2026-09-30T12:00:00Z",
    )
    assert row["features"]["open_provider_alert_count_30d"] == 1
    assert row["features"]["open_provider_alerts_by_severity_30d"] == {"high": 1}


@pytest.mark.asyncio
async def test_direct_collection_reports_missing_sources_without_safe_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    requested_urls: list[str] = []

    class FakeConnector:
        base_url = "https://graph.microsoft.com"

        def __init__(self, _settings: object) -> None:
            pass

        async def _collection(self, url: str, _tenant: uuid.UUID) -> list[dict[str, object]]:
            requested_urls.append(url)
            if "roleAssignments" in url:
                raise httpx.HTTPStatusError(
                    "forbidden", request=httpx.Request("GET", url),
                    response=httpx.Response(403),
                )
            if "riskyUsers" in url:
                raise httpx.HTTPStatusError(
                    "forbidden", request=httpx.Request("GET", url),
                    response=httpx.Response(403),
                )
            return []

        async def _get(self, url: str, _tenant: uuid.UUID) -> dict[str, object]:
            requested_urls.append(url)
            if "/users/" in url:
                return {"id": USER}
            return {"id": USER, "isMfaRegistered": True, "isMfaCapable": True}

        async def registration_details(self, _tenant: uuid.UUID) -> list[dict[str, object]]:
            return [{"id": USER, "isMfaRegistered": True, "isMfaCapable": True}]

        async def risky_users(self, _tenant: uuid.UUID) -> list[dict[str, object]]:
            raise httpx.HTTPStatusError(
                "forbidden", request=httpx.Request("GET", "https://graph.microsoft.com/risk"),
                response=httpx.Response(403),
            )

        async def sign_ins(self, _tenant: uuid.UUID, _since: object) -> list[dict[str, object]]:
            return []

        async def security_alerts(self, _tenant: uuid.UUID, _since: object) -> list[dict[str, object]]:
            return []

        async def messages(self, _tenant: uuid.UUID, _user: str) -> tuple[list[dict[str, object]], str]:
            return [], "delta"

        async def aclose(self) -> None:
            pass

    monkeypatch.setattr(real_graph_scan, "RealGraphConnector", FakeConnector)
    output = tmp_path / "new-run"
    args = Namespace(
        command="scan", tenant_id=TENANT, client_id=TENANT, user_id=USER, out=output,
    )
    result = await real_graph_scan.collect(args, b"a" * 32, "not-saved")
    assert result["source_coverage"]["risky_users"]["status"] == "unavailable"
    assert result["source_coverage"]["directory_roles"]["status"] == "unavailable"
    assert result["source_coverage"]["security_alerts"]["status"] == "not_collected_pilot_scope"
    assert result["model_score_generated"] is False
    row = json.loads((output / "user_features.jsonl").read_text())
    assert row["features"]["entra_risk_level"] is None
    assert row["features"]["has_active_directory_role"] is None
    assert row["features"]["mfa_registered"] is True
    assert USER not in (output / "user_features.jsonl").read_text()
    assert not (output / "mail_features.jsonl").read_text()
    assert not any("/security/alerts_v2" in url or "/users?" in url for url in requested_urls)
    assert any("userId+eq" in url for url in requested_urls)
