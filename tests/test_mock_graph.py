from __future__ import annotations

from fastapi.testclient import TestClient

from services.mock_graph.app.main import TENANTS, app, state

ADMIN = {"X-Mock-Admin": "unit-test-mock-admin-secret"}


def test_signed_token_and_stable_delta_flow() -> None:
    state.reset()
    with TestClient(app) as client:
        token = client.post(
            "/oauth2/v2.0/token",
            headers=ADMIN,
            json={"tenant_id": str(TENANTS[0]), "role": "admin"},
        )
        assert token.status_code == 200
        assert token.json()["access_token"].count(".") == 2
        headers = {**ADMIN, "X-Tenant-ID": str(TENANTS[0])}
        page = client.get("/v1.0/users/user-001/mailFolders/inbox/messages/delta", headers=headers)
        assert page.status_code == 200
        payload = page.json()
        assert "value" in payload
        assert "@odata.deltaLink" in payload or "@odata.nextLink" in payload


def test_fault_controls_cover_expired_delta_and_revoked_consent() -> None:
    state.reset()
    with TestClient(app) as client:
        headers = {**ADMIN, "X-Tenant-ID": str(TENANTS[0])}
        assert client.post("/__admin/faults/expired-delta/start", headers=ADMIN).status_code == 200
        expired = client.get(
            "/v1.0/users/user-001/mailFolders/inbox/messages/delta?$deltatoken=1",
            headers=headers,
        )
        assert expired.status_code == 410
        state.reset()
        assert client.post("/__admin/faults/revoked-consent/start", headers=ADMIN).status_code == 200
        assert client.get("/v1.0/users", headers=headers).status_code == 403


def test_optional_p2_and_mailbox_failure_modes() -> None:
    state.reset()
    with TestClient(app) as client:
        headers = {**ADMIN, "X-Tenant-ID": str(TENANTS[0])}
        assert client.post("/__admin/faults/missing-p2/start", headers=ADMIN).status_code == 200
        risky = client.get("/v1.0/identityProtection/riskyUsers", headers=headers)
        assert risky.status_code == 403
        assert "P2" in risky.text
        state.reset()
        assert client.post("/__admin/faults/unavailable-mailbox/start", headers=ADMIN).status_code == 200
        unavailable = client.get(
            "/v1.0/users/user-099/mailFolders/inbox/messages/delta", headers=headers
        )
        assert unavailable.status_code == 404
        state.reset()
        assert client.post("/__admin/faults/partial-failure/start", headers=ADMIN).status_code == 200
        partial = client.get(
            "/v1.0/users/user-100/mailFolders/inbox/messages/delta", headers=headers
        )
        assert partial.status_code == 503


def test_scenario_start_is_idempotent_and_recovery_restores_signals() -> None:
    state.reset()
    with TestClient(app) as client:
        path = "/__admin/scenarios/account-takeover/start?idempotency_key=stable-key"
        first = client.post(path, headers=ADMIN).json()
        generated = first["generated_messages"]
        second = client.post(path, headers=ADMIN).json()
        assert second["generated_messages"] == generated
        assert state.risks[(TENANTS[0], "user-001")] == "high"
        recovered = client.post(
            "/__admin/scenarios/recovery/start?idempotency_key=recovery-key", headers=ADMIN
        )
        assert recovered.status_code == 200
        assert state.risks[(TENANTS[0], "user-001")] == "none"
        assert state.registration[(TENANTS[0], "user-001")] is True


def test_scenario_fault_pause_and_reset_are_tenant_isolated() -> None:
    state.reset()
    tenant_a, tenant_b = TENANTS
    with TestClient(app) as client:
        tenant_a_query = f"tenant_id={tenant_a}"
        started = client.post(
            "/__admin/scenarios/account-takeover/start"
            f"?idempotency_key=tenant-a-attack&{tenant_a_query}",
            headers=ADMIN,
        )
        assert started.status_code == 200
        assert started.json()["scenario"] == "account-takeover"
        tenant_b_status = client.get(
            f"/__admin/status?tenant_id={tenant_b}", headers=ADMIN
        )
        assert tenant_b_status.json()["scenario"] == "normal"
        assert state.risks[(tenant_b, "user-001")] == "none"

        client.post(
            f"/__admin/faults/revoked-consent/start?{tenant_a_query}",
            headers=ADMIN,
        )
        headers_a = {**ADMIN, "X-Tenant-ID": str(tenant_a)}
        headers_b = {**ADMIN, "X-Tenant-ID": str(tenant_b)}
        assert client.get("/v1.0/users", headers=headers_a).status_code == 403
        assert client.get("/v1.0/users", headers=headers_b).status_code == 200

        client.post(f"/__admin/stop?{tenant_a_query}", headers=ADMIN)
        assert client.get(
            f"/__admin/status?tenant_id={tenant_a}", headers=ADMIN
        ).json()["paused"] is True
        assert client.get(
            f"/__admin/status?tenant_id={tenant_b}", headers=ADMIN
        ).json()["paused"] is False

        client.post(f"/__admin/reset?{tenant_a_query}", headers=ADMIN)
        assert client.get("/v1.0/users", headers=headers_a).status_code == 200
        assert client.get("/v1.0/users", headers=headers_b).status_code == 200
        assert state.risks[(tenant_a, "user-001")] == "none"
