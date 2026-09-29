from __future__ import annotations

from datetime import UTC, datetime

import pytest

from packages.ml.m365risk_ml.v2 import (
    CanonicalSignal,
    auth_integrity,
    component_feature_vector,
    identity_compromise,
    local_identity_anomaly,
    score_components,
    sender_context,
    sign_in_window_signals,
    top_k_mean,
)


def test_compauth_takes_precedence_over_lower_level_authentication() -> None:
    signal = auth_integrity({"compauth": "pass", "dmarc": "fail", "dkim": "fail", "spf": "fail"})
    assert signal.value == 0
    assert signal.availability == "available"
    assert "Composite" in signal.explanation


def test_dmarc_takes_precedence_and_unknown_is_not_safe() -> None:
    assert auth_integrity({"dmarc": "fail", "dkim": "pass", "spf": "pass"}).value == 1
    missing = auth_integrity({})
    assert missing.value is None
    assert missing.availability == "unavailable"


def test_sender_context_does_not_include_authentication_alignment() -> None:
    signal = sender_context(
        external_sender=True,
        reply_to_domain_mismatch=True,
        from_sender_mismatch=False,
    )
    assert signal.value == pytest.approx(0.45)
    assert "DMARC" not in signal.explanation


def test_external_sender_alone_is_not_threat_evidence() -> None:
    signal = sender_context(
        external_sender=True,
        reply_to_domain_mismatch=False,
        from_sender_mismatch=False,
    )
    assert signal.value == 0


def test_top_k_mean_is_one_stable_daily_email_input() -> None:
    result = top_k_mean([0.1, 0.2, 0.8, 0.9], k=3)
    assert result.value == pytest.approx((0.9 + 0.8 + 0.2) / 3)
    assert top_k_mean([]).value is None


def test_identity_fusion_uses_max_instead_of_double_counting() -> None:
    local = local_identity_anomaly({"network": 0.7, "device": 0.3}, history_days=30)
    provider = CanonicalSignal(0.65, "available", "provider")
    combined = identity_compromise(local, provider)
    assert local.value == pytest.approx(0.79)
    assert combined.value == pytest.approx(0.79)
    assert combined.value != pytest.approx(0.79 + 0.65)


def test_insufficient_history_is_not_converted_to_zero() -> None:
    local = local_identity_anomaly({"network": 1.0}, history_days=2)
    combined = identity_compromise(local, CanonicalSignal(None, "unavailable", "missing"))
    assert combined.value is None
    assert combined.availability == "insufficient_history"


def test_v2_score_requires_minimum_coverage_and_reweights_available_components() -> None:
    incomplete = score_components(
        {
            "email_threat": CanonicalSignal(1.0, "available", "email"),
            "identity_compromise": CanonicalSignal(None, "unavailable", "identity"),
            "mfa_exposure": CanonicalSignal(None, "unavailable", "mfa"),
            "privilege_exposure": CanonicalSignal(None, "unavailable", "privilege"),
            "endpoint_threat": CanonicalSignal(None, "unavailable", "endpoint"),
        }
    )
    assert incomplete.score is None
    assert incomplete.level == "insufficient_data"

    covered = score_components(
        {
            "email_threat": CanonicalSignal(0.6, "available", "email"),
            "identity_compromise": CanonicalSignal(0.6, "available", "identity"),
            "mfa_exposure": CanonicalSignal(0.6, "available", "mfa"),
            "privilege_exposure": CanonicalSignal(0.6, "available", "privilege"),
            "endpoint_threat": CanonicalSignal(None, "unavailable", "endpoint"),
        }
    )
    assert covered.score == 65
    assert sum(value or 0 for value in covered.contributions.values()) == pytest.approx(65.4)


def test_privilege_cannot_create_risk_without_threat_evidence() -> None:
    result = score_components(
        {
            "email_threat": CanonicalSignal(0.0, "available", "safe"),
            "identity_compromise": CanonicalSignal(0.0, "available", "safe"),
            "mfa_exposure": CanonicalSignal(0.0, "available", "safe"),
            "privilege_exposure": CanonicalSignal(1.0, "available", "admin"),
            "endpoint_threat": CanonicalSignal(0.0, "available", "safe"),
        }
    )
    assert result.score == 0
    assert result.level == "low"


def test_component_vector_distinguishes_safe_zero_from_missing_evidence() -> None:
    vector = component_feature_vector(
        {
            "email_threat": CanonicalSignal(0.0, "available", "safe"),
            "identity_compromise": CanonicalSignal(None, "unavailable", "missing"),
            "mfa_exposure": CanonicalSignal(None, "insufficient_history", "not enough history"),
            "privilege_exposure": CanonicalSignal(0.7, "available", "admin"),
            "endpoint_threat": CanonicalSignal(None, "unavailable", "not licensed"),
        }
    )
    assert vector["email_threat__value"] == 0
    assert vector["email_threat__available"] == 1
    assert vector["identity_compromise__value"] == 0
    assert vector["identity_compromise__available"] == 0
    assert vector["mfa_exposure__insufficient_history"] == 1


def test_sign_in_features_use_distinct_dimensions() -> None:
    signals = sign_in_window_signals(
        [
            {
                "created_at": datetime(2026, 1, 1, 2, tzinfo=UTC),
                "country": "FR",
                "network_hash": "new-network",
                "device_hash": "known-device",
                "app_hash": "new-app",
                "successful": False,
            }
        ],
        known_countries={"TN"},
        known_networks={"known-network"},
        known_devices={"known-device"},
        known_apps={"known-app"},
    )
    assert signals == {
        "time": 1.0,
        "location": 1.0,
        "network": 1.0,
        "device": 0.0,
        "auth": 1.0,
        "app": 1.0,
    }
