from __future__ import annotations

import uuid
from datetime import UTC, datetime

from services.api.app.main import scanned_feature_row
from services.api.app.models import UserFeatureWindow


def test_scanned_export_contains_only_whitelisted_derived_values() -> None:
    tenant_id = uuid.uuid4()
    window = UserFeatureWindow(
        tenant_id=tenant_id,
        user_id="private-graph-user-id",
        window_end=datetime(2026, 9, 29, tzinfo=UTC),
        score=90,
        level="critical",
        components={"email_threat": 0.8, "identity_compromise": None},
        features={"email_top3": 0.7, "subject": "must not leave the database"},
        availability={"email_threat": "available", "identity_compromise": "unavailable"},
        evidence={"raw_header": "must not leave the database"},
        feature_version="UserFeatureWindowV2",
        model_version="test-model",
    )
    exported = scanned_feature_row(window, tenant_id).model_dump(mode="json")
    text = str(exported)
    assert "private-graph-user-id" not in text
    assert "must not leave" not in text
    assert "score" not in exported  # An existing score is not a training label.
    assert exported["components"]["email_threat"] == 0.8
    assert exported["availability"]["identity_compromise"] == "unavailable"
    assert exported["features"]["email_top3"] == 0.7
    assert exported["subject_key"] != exported["sample_id"]
    assert scanned_feature_row(window, tenant_id).sample_id == exported["sample_id"]
