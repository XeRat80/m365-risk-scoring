from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from services.api.app.models import SyncJob
from services.api.app.schemas import (
    MailObservationV2,
    SignInObservationV1,
    SyncJobCursorPage,
    UserFeatureWindowV2,
)


def test_sync_job_cursor_serializes_orm_rows() -> None:
    now = datetime.now(UTC)
    job = SyncJob(
        tenant_id=uuid.uuid4(),
        id=uuid.uuid4(),
        status="running",
        attempt=1,
        checkpoint={},
        created_at=now,
        next_attempt_at=now,
    )
    page = SyncJobCursorPage(items=[job], next_cursor=None)
    assert page.items[0].id == job.id
    assert page.items[0].status == "running"


def test_v2_mail_allows_unknown_authentication_without_marking_it_safe() -> None:
    mail = MailObservationV2(
        id="message-1",
        user_id="user-1",
        received_at=datetime.now(UTC),
        authentication_results={"spf": None, "dkim": None, "dmarc": None},
        auth_integrity=None,
        auth_availability="unavailable",
        sender_context=0.1,
        external_sender=True,
        reply_to_domain_mismatch=False,
        from_sender_mismatch=False,
        received_hops=2,
        recipient_count=1,
        sender_domain_hash="hash",
    )
    assert mail.auth_integrity is None
    assert mail.auth_availability == "unavailable"


def test_v2_contracts_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SignInObservationV1(
            id="sign-in-1",
            user_id="user-1",
            created_at=datetime.now(UTC),
            successful=True,
            is_interactive=True,
            unexpected_plaintext_ip="203.0.113.1",  # type: ignore[call-arg]
        )


def test_v2_window_preserves_unavailable_components() -> None:
    window = UserFeatureWindowV2(
        user_id="user-1",
        window_end=datetime.now(UTC),
        score=None,
        level="insufficient_data",
        components={"endpoint_threat": None},
        features={},
        availability={"endpoint_threat": "unavailable"},
        evidence={},
        calculated_at=datetime.now(UTC),
    )
    assert window.components["endpoint_threat"] is None
