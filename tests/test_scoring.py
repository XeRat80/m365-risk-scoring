from __future__ import annotations

from packages.ml.m365risk_ml.scoring import (
    HYBRID_WEIGHTS,
    email_threat_score,
    hybrid_user_score,
    precision_guarded_email_probability,
)


def test_pdf_weights_are_normalized() -> None:
    assert HYBRID_WEIGHTS == {
        "email": 0.35,
        "behaviour": 0.20,
        "entra": 0.20,
        "posture": 0.15,
        "privilege": 0.10,
    }
    assert sum(HYBRID_WEIGHTS.values()) == 1


def test_high_risk_metadata_increases_score_and_explains_it() -> None:
    probability, factors = email_threat_score(
        {
            "authenticationResults": {"spf": "fail", "dkim": "fail", "dmarc": "fail"},
            "replyToDomainMismatch": True,
            "externalSender": True,
            "receivedHops": 10,
        }
    )
    assert probability > 0.9
    assert "SPF fail" in factors
    result = hybrid_user_score(
        email=probability,
        behaviour=1,
        entra_level="high",
        mfa_registered=False,
        is_admin=True,
    )
    assert result.score >= 90
    assert result.level == "critical"
    assert result.factors[0][1] > 0


def test_scores_are_clamped() -> None:
    result = hybrid_user_score(
        email=9,
        behaviour=-4,
        entra_level="unknown",
        mfa_registered=True,
        is_admin=False,
    )
    assert 0 <= result.score <= 100


def test_fully_authenticated_aligned_mail_stays_below_alert_range() -> None:
    guarded = precision_guarded_email_probability(
        0.92,
        {
            "authenticationResults": {"spf": "pass", "dkim": "pass", "dmarc": "pass"},
            "replyToDomainMismatch": False,
            "fromSenderMismatch": False,
            "externalSender": True,
        },
    )
    assert guarded == 0.20


def test_explicit_authentication_failure_cannot_be_diluted_by_model() -> None:
    guarded = precision_guarded_email_probability(
        0.05,
        {
            "authenticationResults": {"spf": "fail", "dkim": "fail", "dmarc": "fail"},
            "replyToDomainMismatch": True,
            "fromSenderMismatch": True,
            "externalSender": True,
        },
    )
    assert guarded >= 0.9


def test_privilege_only_amplifies_existing_risk() -> None:
    healthy_admin = hybrid_user_score(
        email=0,
        behaviour=0,
        entra_level="none",
        mfa_registered=True,
        is_admin=True,
    )
    risky_admin = hybrid_user_score(
        email=1,
        behaviour=1,
        entra_level="high",
        mfa_registered=False,
        is_admin=True,
    )
    assert healthy_admin.score == 0
    assert healthy_admin.components["privilege"] == 0
    assert risky_admin.components["privilege"] > 0
