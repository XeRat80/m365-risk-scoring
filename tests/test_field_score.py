from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from packages.ml.m365risk_ml.features import FEATURE_NAMES
from scripts.field_features import canonical_from_graph
from scripts.field_score import score_scan


def test_canonical_identity_uses_baseline_and_never_scores_utc_hour() -> None:
    now = datetime(2026, 10, 1, 12, tzinfo=UTC)
    events = [
        {
            "userId": "user-a", "createdDateTime": (now - timedelta(days=day)).isoformat(),
            "status": {"errorCode": 0}, "location": {"countryOrRegion": "TN"},
            "deviceDetail": {"deviceId": "known"}, "ipAddress": "192.0.2.10", "appId": "app-a",
        }
        for day in range(1, 9)
    ]
    events.append({
        "userId": "user-a", "createdDateTime": (now - timedelta(hours=1)).isoformat(),
        "status": {"errorCode": 50126}, "location": {"countryOrRegion": "FR"},
        "deviceDetail": {"deviceId": "new"}, "ipAddress": "198.51.100.1", "appId": "app-b",
    })
    row = canonical_from_graph(
        user_id="user-a", key=b"k" * 32,
        registration={"isMfaRegistered": True, "isMfaCapable": True},
        risky=None, admin_ids=set(), sign_ins=events, alerts=None, captured_at=now,
    )
    assert row["baseline_days"] == 7
    assert row["identity_features"]["time"] is None
    assert row["canonical"]["identity_compromise"]["value"] > 0.9
    assert row["canonical"]["endpoint_threat"]["availability"] == "unavailable"
    serialized = json.dumps(row)
    assert "192.0.2.10" not in serialized
    assert "198.51.100.1" not in serialized


def test_offline_field_score_has_model_and_explicit_coverage(tmp_path: Path) -> None:
    scan = tmp_path / "pilot"
    scan.mkdir()
    now = datetime(2026, 10, 1, 12, tzinfo=UTC)
    (scan / "manifest.json").write_text(json.dumps({
        "schema": "real-graph-collection-v1", "mode": "collection", "selected_users": 1,
        "source_coverage": {"security_alerts": {"status": "not_collected_pilot_scope"}},
    }))
    (scan / "canonical_features.jsonl").write_text(json.dumps({
        "sample_id": "pseudonymous-user", "window_end": now.isoformat(),
        "canonical": {
            "identity_compromise": {"value": 1.0, "availability": "available", "explanation": "test"},
            "mfa_exposure": {"value": 0.0, "availability": "available", "explanation": "test"},
            "privilege_exposure": {"value": 0.0, "availability": "available", "explanation": "test"},
            "endpoint_threat": {"value": None, "availability": "unavailable", "explanation": "pilot"},
        },
    }) + "\n")
    (scan / "mail_features.jsonl").write_text(json.dumps({
        "sample_id": "pseudonymous-user", "received_at": now.isoformat(),
        "reply_to_domain_mismatch": True, "from_sender_mismatch": False,
        "external_sender": True,
        "model_features": {name: 0.0 for name in FEATURE_NAMES},
    }) + "\n")
    report = score_scan(scan, Path("bundles/field-research"))
    assert report["users"] == 1
    assert report["scored_users"] == 1
    assert report["email_model_approved"] is False
    result = json.loads((scan / "scores.jsonl").read_text())
    assert result["score"] is not None
    assert result["availability"]["endpoint_threat"] == "unavailable"
    assert result["email_model"]["reviewed_mails_30d"] == 1
