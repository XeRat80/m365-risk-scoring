from __future__ import annotations

import uuid
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import Header
from sqlalchemy import select, text

from services.api.app.auth import Principal, current_principal
from services.api.app.database import AdminSessionLocal, admin_engine, engine, tenant_session
from services.api.app.main import app
from services.api.app.models import AuditEvent, SecurityAlertObservation
from services.worker.app.main import tenant_pseudonym_key, upsert_alert_observation


@pytest.mark.integration
@pytest.mark.asyncio
async def test_alert_closure_is_tenant_scoped_and_survives_provider_refresh() -> None:
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    provider_a = f"provider-{uuid.uuid4()}"
    provider_b = f"provider-{uuid.uuid4()}"
    key_a = tenant_pseudonym_key(tenant_a)
    key_b = tenant_pseudonym_key(tenant_b)
    occurred = datetime.now(UTC).isoformat()

    async def principal(x_test_tenant: str = Header(...)) -> Principal:
        return Principal(tenant_id=uuid.UUID(x_test_tenant), subject="analyst-integration", role="analyst")

    async with AdminSessionLocal() as session, session.begin():
        await session.execute(
            text("INSERT INTO tenants(id,name) VALUES (:a,'Alert test A'),(:b,'Alert test B')"),
            {"a": tenant_a, "b": tenant_b},
        )
    app.dependency_overrides[current_principal] = principal
    try:
        async for session in tenant_session(tenant_a):
            await upsert_alert_observation(session, tenant_a, {
                "id": provider_a, "createdDateTime": occurred,
                "severity": "high", "status": "new",
            }, None, key_a)
        async for session in tenant_session(tenant_b):
            await upsert_alert_observation(session, tenant_b, {
                "id": provider_b, "createdDateTime": occurred,
                "severity": "medium", "status": "new",
            }, None, key_b)

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            a_headers = {"X-Test-Tenant": str(tenant_a)}
            b_headers = {"X-Test-Tenant": str(tenant_b)}
            a_list = await client.get("/api/v1/alerts?soc_status=open", headers=a_headers)
            b_list = await client.get("/api/v1/alerts?soc_status=open", headers=b_headers)
            assert a_list.status_code == b_list.status_code == 200
            a_ids = {item["id"] for item in a_list.json()["items"]}
            b_ids = {item["id"] for item in b_list.json()["items"]}
            assert len(a_ids) == len(b_ids) == 1
            assert a_ids.isdisjoint(b_ids)
            alert_a = next(iter(a_ids))
            denied = await client.post(
                f"/api/v1/alerts/{alert_a}/close", headers=b_headers,
                json={"reason": "resolved"},
            )
            assert denied.status_code == 404
            closed = await client.post(
                f"/api/v1/alerts/{alert_a}/close", headers=a_headers,
                json={"reason": "false_positive"},
            )
            assert closed.status_code == 200
            assert closed.json()["soc_status"] == "closed"
            assert closed.json()["provider_status"] == "new"
            assert closed.json()["closure"]["actor"] == "analyst-integration"
            repeat = await client.post(
                f"/api/v1/alerts/{alert_a}/close", headers=a_headers,
                json={"reason": "accepted_risk"},
            )
            assert repeat.status_code == 200
            assert repeat.json()["closure"]["reason"] == "false_positive"

            async for session in tenant_session(tenant_a):
                await upsert_alert_observation(session, tenant_a, {
                    "id": provider_a, "createdDateTime": occurred,
                    "severity": "low", "status": "resolved",
                }, None, key_a)
            after = await client.get("/api/v1/alerts?soc_status=closed", headers=a_headers)
            assert after.status_code == 200
            assert after.json()["items"][0]["provider_status"] == "resolved"
            assert after.json()["items"][0]["closure"]["reason"] == "false_positive"

        async with AdminSessionLocal() as session:
            alert = await session.get(SecurityAlertObservation, (tenant_a, alert_a))
            assert alert is not None and alert.status == "resolved"
            audit = list(await session.scalars(select(AuditEvent).where(
                AuditEvent.tenant_id == tenant_a, AuditEvent.action == "alert.closed",
            )))
            assert len(audit) == 1
    finally:
        app.dependency_overrides.pop(current_principal, None)
        async with AdminSessionLocal() as session, session.begin():
            await session.execute(
                text("DELETE FROM tenants WHERE id IN (:a,:b)"),
                {"a": tenant_a, "b": tenant_b},
            )
        await engine.dispose()
        await admin_engine.dispose()
