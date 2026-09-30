from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import httpx
import pytest

from services.api.app.models import (
    EmailFeature,
    RiskScore,
    SecurityAlertObservation,
    User,
    UserDailyFeature,
)
from services.worker.app import main as worker


class FakeConnector:
    async def users(self, _: uuid.UUID) -> list[dict[str, object]]:
        return [
            {
                "id": "user-001",
                "displayName": "Demo User",
                "userPrincipalName": "demo@example.test",
                "isAdmin": True,
            }
        ]

    async def registration_details(self, _: uuid.UUID) -> list[dict[str, object]]:
        return [{"id": "user-001", "isMfaRegistered": False}]

    async def risky_users(self, _: uuid.UUID) -> list[dict[str, object]]:
        return [{"id": "user-001", "riskLevel": "high"}]

    async def messages(
        self, _: uuid.UUID, user_id: str, delta_link: str | None
    ) -> tuple[list[dict[str, object]], str]:
        assert user_id == "user-001"
        assert delta_link is None
        return (
            [
                {
                    "id": "message-001",
                    "receivedDateTime": "2026-01-01T00:00:00Z",
                    "externalSender": True,
                    "recipientCount": 1,
                    "hasAttachments": False,
                    "importance": "high",
                    "authenticationResults": {"spf": "fail", "dkim": "fail", "dmarc": "fail"},
                    "replyToDomainMismatch": True,
                    "fromSenderMismatch": True,
                    "receivedHops": 10,
                }
            ],
            "http://mock/delta?token=1",
        )


class FakeSession:
    def __init__(self) -> None:
        self.users: dict[tuple[uuid.UUID, str], User] = {}
        self.emails: dict[tuple[uuid.UUID, str], EmailFeature] = {}
        self.daily: dict[tuple[uuid.UUID, str, object], UserDailyFeature] = {}
        self.scores: list[RiskScore] = []
        self.added: list[object] = []
        self.latest_score: RiskScore | None = None
        self.statements: list[object] = []
        self.alerts: dict[tuple[uuid.UUID, str], SecurityAlertObservation] = {}

    async def get(self, model: type[object], key: object) -> object | None:
        if model is SecurityAlertObservation:
            return self.alerts.get(key)  # type: ignore[arg-type]
        if model is User:
            return self.users.get(key)  # type: ignore[arg-type]
        if model is EmailFeature:
            return self.emails.get(key)  # type: ignore[arg-type]
        if model is UserDailyFeature:
            return self.daily.get(key)  # type: ignore[arg-type]
        return None

    async def scalar(self, _: object) -> object | None:
        return self.latest_score

    async def execute(self, statement: object) -> None:
        self.statements.append(statement)

    async def scalars(self, statement: object) -> list[object]:
        sql = str(statement)
        if "FROM email_features" in sql:
            return list(self.emails.values())
        if "FROM user_daily_features" in sql:
            return list(self.daily.values())
        if "FROM risk_scores" in sql:
            return list(self.scores)
        if "FROM security_alert_observations" in sql:
            return list(self.alerts.values())
        return []

    async def flush(self) -> None:
        return None

    async def delete(self, value: object) -> None:
        if value in self.added:
            self.added.remove(value)

    def add(self, value: object) -> None:
        self.added.append(value)
        if isinstance(value, SecurityAlertObservation):
            self.alerts[(value.tenant_id, value.id)] = value
        if isinstance(value, User):
            self.users[(value.tenant_id, value.id)] = value
        if isinstance(value, EmailFeature):
            self.emails[(value.tenant_id, value.id)] = value
        if isinstance(value, UserDailyFeature):
            self.daily[(value.tenant_id, value.user_id, value.day)] = value
        if isinstance(value, RiskScore):
            self.latest_score = value
            self.scores.append(value)


@pytest.mark.asyncio
async def test_worker_processes_metadata_only_and_updates_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid.UUID("00000000-0000-4000-8000-000000000001")
    job_id = uuid.uuid4()
    session = FakeSession()

    async def fake_tenant_session(_: uuid.UUID) -> AsyncIterator[FakeSession]:
        yield session

    complete = AsyncMock()
    monkeypatch.setattr(worker, "connector_for", lambda *_: FakeConnector())
    monkeypatch.setattr(worker, "tenant_session", fake_tenant_session)
    monkeypatch.setattr(worker, "complete_job", complete)
    await worker.process_job(tenant_id, job_id, {})
    stored_email = next(value for value in session.added if isinstance(value, EmailFeature))
    assert "subject" not in stored_email.features
    assert "body" not in stored_email.features
    assert sum(isinstance(value, UserDailyFeature) for value in session.added) == 90
    # The dated fixture produces 89 historical V1 records. V3 correctly refuses
    # to manufacture a current score when current-window source coverage is below
    # the minimum threshold.
    assert sum(isinstance(value, RiskScore) for value in session.added) == 89
    assert any("user_feature_windows_v2" in str(statement) for statement in session.statements)
    complete.assert_awaited_once()
    assert complete.await_args.args[2]["user-001"] == "http://mock/delta?token=1"


@pytest.mark.asyncio
async def test_worker_does_not_persist_unchanged_scores(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid.UUID("00000000-0000-4000-8000-000000000001")
    session = FakeSession()

    async def fake_tenant_session(_: uuid.UUID) -> AsyncIterator[FakeSession]:
        yield session

    monkeypatch.setattr(worker, "connector_for", lambda *_: FakeConnector())
    monkeypatch.setattr(worker, "tenant_session", fake_tenant_session)
    monkeypatch.setattr(worker, "complete_job", AsyncMock())
    await worker.process_job(tenant_id, uuid.uuid4(), {})
    email_count = len(session.emails)
    session.added.clear()
    await worker.process_job(tenant_id, uuid.uuid4(), {})
    assert not any(isinstance(value, RiskScore) for value in session.added)
    assert len(session.emails) == email_count


@pytest.mark.asyncio
async def test_worker_refreshes_existing_alert_between_cycles(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession()
    tenant_id = uuid.UUID("00000000-0000-4000-8000-000000000001")

    class AlertConnector(FakeConnector):
        alert_status = "new"
        severity = "medium"

        async def security_alerts(self, _: uuid.UUID, since: datetime) -> list[dict[str, object]]:
            return [{"id": "alert-1", "createdDateTime": datetime.now(UTC).isoformat(),
                     "status": self.alert_status, "severity": self.severity,
                     "userStates": [{"userId": "user-001"}]}]

    connector = AlertConnector()

    async def fake_session(_: uuid.UUID) -> AsyncIterator[FakeSession]:
        yield session

    monkeypatch.setattr(worker, "connector_for", lambda *_: connector)
    monkeypatch.setattr(worker, "tenant_session", fake_session)
    monkeypatch.setattr(worker, "complete_job", AsyncMock())
    await worker.process_job(tenant_id, uuid.uuid4(), {})
    assert len(session.alerts) == 1
    connector.severity = "high"
    next(iter(session.alerts.values())).details = {"soc_closure": {"reason": "accepted_risk"}}
    await worker.process_job(tenant_id, uuid.uuid4(), {})
    assert next(iter(session.alerts.values())).severity == "high"
    connector.alert_status = "resolved"
    await worker.process_job(tenant_id, uuid.uuid4(), {})
    assert len(session.alerts) == 1
    assert next(iter(session.alerts.values())).status == "resolved"
    assert next(iter(session.alerts.values())).details["soc_closure"] == {"reason": "accepted_risk"}


class PartialConnector(FakeConnector):
    async def users(self, _: uuid.UUID) -> list[dict[str, object]]:
        return [
            {
                "id": user_id,
                "displayName": user_id,
                "userPrincipalName": f"{user_id}@example.test",
                "isAdmin": False,
            }
            for user_id in ("user-001", "user-002")
        ]

    async def registration_details(self, _: uuid.UUID) -> list[dict[str, object]]:
        return []

    async def risky_users(self, _: uuid.UUID) -> list[dict[str, object]]:
        return []

    async def messages(
        self, _: uuid.UUID, user_id: str, delta_link: str | None
    ) -> tuple[list[dict[str, object]], str]:
        if user_id == "user-001":
            raise httpx.HTTPStatusError(
                "mailbox unavailable",
                request=httpx.Request("GET", "https://graph.test/messages"),
                response=httpx.Response(503),
            )
        return [], "https://graph.test/delta?user=user-002"


@pytest.mark.asyncio
async def test_worker_preserves_successful_checkpoints_during_partial_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid.UUID("00000000-0000-4000-8000-000000000001")
    session = FakeSession()

    async def fake_tenant_session(_: uuid.UUID) -> AsyncIterator[FakeSession]:
        yield session

    complete = AsyncMock()
    monkeypatch.setattr(worker, "tenant_session", fake_tenant_session)
    monkeypatch.setattr(worker, "complete_job", complete)
    await worker.process_job_with_connector(
        PartialConnector(), tenant_id, uuid.uuid4(), {}
    )
    checkpoint = complete.await_args.args[2]
    assert checkpoint["user-002"] == "https://graph.test/delta?user=user-002"
    assert "user-001" not in checkpoint
    assert "Partial mailbox failures" in complete.await_args.args[3]
