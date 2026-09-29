from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from packages.ml.m365risk_ml.features import (
    FEATURE_NAMES,
    corpus_rows,
    header_features,
    read_header_block,
)
from services.api.app.schemas import (
    AnalystFeedbackV1,
    EmailMetadataV1,
    MailEventResponse,
    RiskScoreV1,
    UserDailyFeaturesV1,
)


def test_header_parser_ignores_content_and_label_headers() -> None:
    first = b"""From: Alice <alice@example.com>\nTo: Bob <bob@example.net>\nDate: Tue, 1 Jan 2025 00:00:00 +0000\nMessage-ID: <safe@example.com>\nX-Spam-Flag: YES\nContent-Type: text/plain\n\nsecret body one"""
    second = first.replace(b"secret body one", b"a completely different body")
    assert header_features(first) == header_features(second)
    assert set(header_features(first)) == set(FEATURE_NAMES)


def test_private_content_is_not_part_of_metadata_contract() -> None:
    payload = {
        "id": "message-1",
        "user_id": "user-1",
        "received_at": "2025-01-01T00:00:00Z",
        "external_sender": True,
        "recipient_count": 1,
        "has_attachments": False,
        "importance": "normal",
        "authentication_results": {"spf": "pass"},
        "reply_to_domain_mismatch": False,
        "from_sender_mismatch": False,
        "received_hops": 3,
        "subject": "must never be accepted",
    }
    with pytest.raises(ValidationError):
        EmailMetadataV1.model_validate(payload)
    assert "feature_version" in UserDailyFeaturesV1.model_fields
    assert RiskScoreV1.model_fields["score"].metadata
    assert set(AnalystFeedbackV1.model_fields) >= {
        "tenant_id",
        "risk_id",
        "verdict",
        "actor",
        "created_at",
    }


def test_missing_and_malformed_headers_are_safe() -> None:
    features = header_features(b"From: malformed\nMessage-ID: no-angle-brackets\n\nignored")
    assert features["missing_date"] == 1
    assert features["malformed_message_id"] == 1


def test_mail_event_contract_exposes_only_safe_header_telemetry() -> None:
    safe = {
        "id": "message-hash",
        "user_id": "user-001",
        "received_at": "2025-01-01T00:00:00Z",
        "risk_probability": 0.75,
        "external_sender": True,
        "recipient_count": 1,
        "has_attachments": False,
        "importance": "normal",
        "authentication_results": {"spf": "fail", "dkim": "pass"},
        "reply_to_domain_mismatch": True,
        "from_sender_mismatch": False,
        "received_hops": 4,
        "sender_domain_hash": "pseudonymous-domain-hash",
    }
    event = MailEventResponse.model_validate(safe)
    assert event.sender_domain_hash == "pseudonymous-domain-hash"
    forbidden = {"subject", "body", "preview", "sender_address", "attachment_bytes"}
    assert forbidden.isdisjoint(MailEventResponse.model_fields)
    with pytest.raises(ValidationError):
        MailEventResponse.model_validate({**safe, "subject": "must not escape"})


def test_archive_reader_never_reads_message_body(tmp_path: Path) -> None:
    archive = tmp_path / "20030228_spam.tar.bz2"
    message = b"From: sender@example.com\nTo: user@example.test\n\nprivate body bytes"
    with tarfile.open(archive, "w:bz2") as handle:
        info = tarfile.TarInfo("spam/message-1")
        info.size = len(message)
        handle.addfile(info, io.BytesIO(message))
    rows = list(corpus_rows(archive))
    assert len(rows) == 1
    assert rows[0]["label"] == 1
    assert "body" not in rows[0]
    assert read_header_block(io.BytesIO(message)) == b"From: sender@example.com\nTo: user@example.test\n\n"


def test_oversized_header_is_rejected() -> None:
    with pytest.raises(ValueError, match="privacy limit"):
        read_header_block(io.BytesIO(b"X-Large: " + b"x" * 300), max_bytes=64)
