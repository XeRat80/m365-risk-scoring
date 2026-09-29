from __future__ import annotations

import uuid
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import delete

from services.api.app.auth import Principal
from services.api.app.database import AdminSessionLocal, admin_engine
from services.api.app.main import (
    app,
    decode_cursor,
    encode_cursor,
    onboarding_callback,
    onboarding_start,
    settings,
    to_risk,
)
from services.api.app.models import AuditEvent, ConnectorConnection, RiskFactor, RiskScore


def test_health_metrics_and_error_envelope() -> None:
    with TestClient(app) as client:
        live = client.get("/health/live", headers={"X-Request-ID": "request-123"})
        assert live.status_code == 200
        assert live.headers["X-Request-ID"] == "request-123"
        denied = client.get("/metrics")
        assert denied.json() == {
            "code": "http_401",
            "message": "Metrics credential required",
            "request_id": denied.json()["request_id"],
        }
        protected_metrics = client.get(
            "/metrics", headers={"Authorization": f"Bearer {settings.metrics_key}"}
        )
        assert protected_metrics.status_code == 200
        assert "m365risk_http_requests_total" in protected_metrics.text


def test_validation_errors_do_not_expose_internal_details() -> None:
    with TestClient(app) as client:
        response = client.post("/api/v1/auth/mock-token", json={"tenant_id": "not-a-uuid"})
        assert response.status_code == 422
        assert response.json()["code"] == "validation_error"
        assert response.json()["message"] == "Request validation failed"
        missing = client.get("/does-not-exist")
        assert missing.status_code == 404
        assert missing.json()["code"] == "http_404"


def test_cursor_contract_and_recommended_actions_are_stable() -> None:
    cursor = encode_cursor("user-001", "2026-01-01T00:00:00+00:00")
    assert decode_cursor(cursor, 2) == ["user-001", "2026-01-01T00:00:00+00:00"]
    with pytest.raises(HTTPException) as invalid:
        decode_cursor("not-base64", 2)
    assert invalid.value.status_code == 400
    score = RiskScore(
        tenant_id=uuid.uuid4(),
        id=uuid.uuid4(),
        user_id="user-001",
        score=88,
        level="critical",
        model_version="test-model",
        calculated_at=datetime.now(UTC),
    )
    score.factors = [
        RiskFactor(tenant_id=score.tenant_id, name="MFA posture", contribution=15),
        RiskFactor(tenant_id=score.tenant_id, name="Email threat", contribution=35),
        RiskFactor(tenant_id=score.tenant_id, name="Entra risk", contribution=20),
    ]
    response = to_risk(score)
    assert response.recommended_actions == [
        "Review recent sign-in and mailbox activity",
        "Require MFA registration",
        "Verify recent external communications",
        "Review Microsoft Entra risky-user evidence",
    ]


@pytest.mark.asyncio
async def test_real_onboarding_state_is_signed_and_tenant_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid.UUID("00000000-0000-4000-8000-000000000001")
    monkeypatch.setattr(settings, "connector_mode", "real")
    principal = Principal(tenant_id=tenant_id, subject="admin-user", role="admin")

    monkeypatch.setattr(settings, "graph_client_id", None)
    with pytest.raises(HTTPException) as missing_client:
        await onboarding_start(principal)
    assert missing_client.value.status_code == 503

    monkeypatch.setattr(settings, "graph_client_id", "graph-client-id")
    started = await onboarding_start(principal)
    state = parse_qs(urlparse(started["url"]).query)["state"][0]
    assert started["mode"] == "real"
    assert await onboarding_callback(tenant_id, state, False) == {
        "adminConsent": False,
        "status": "denied",
    }

    with pytest.raises(HTTPException) as exc_info:
        await onboarding_callback(
            uuid.UUID("00000000-0000-4000-8000-000000000002"), state, False
        )
    assert exc_info.value.status_code == 401


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_onboarding_state_cannot_be_replayed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid.UUID("00000000-0000-4000-8000-000000000001")
    monkeypatch.setattr(settings, "connector_mode", "real")
    monkeypatch.setattr(settings, "graph_client_id", "graph-client-id")
    monkeypatch.setattr(settings, "graph_client_secret", "graph-client-secret")
    principal = Principal(tenant_id=tenant_id, subject="admin-user", role="admin")
    started = await onboarding_start(principal)
    state = parse_qs(urlparse(started["url"]).query)["state"][0]
    state_jti = str(
        jwt.decode(
            state,
            settings.token_encryption_key,
            algorithms=["HS256"],
            audience="m365-risk-admin-consent",
            issuer="m365-risk-api",
        )["jti"]
    )
    try:
        accepted = await onboarding_callback(tenant_id, state, True)
        assert accepted == {"adminConsent": True, "status": "accepted"}
        with pytest.raises(HTTPException) as replayed:
            await onboarding_callback(tenant_id, state, True)
        assert replayed.value.status_code == 409
    finally:
        async with AdminSessionLocal() as session, session.begin():
            await session.execute(
                delete(AuditEvent).where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.details["state_jti"].astext == state_jti,
                )
            )
            await session.execute(
                delete(ConnectorConnection).where(
                    ConnectorConnection.tenant_id == tenant_id
                )
            )
        await admin_engine.dispose()
