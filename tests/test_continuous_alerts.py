import uuid
from datetime import UTC, datetime

import httpx
import pytest

from services.api.app.config import Settings
from services.api.app.connectors import RealGraphConnector

TENANT = uuid.UUID("00000000-0000-4000-8000-000000000001")


def connector_settings(**values: str) -> Settings:
    return Settings(token_encryption_key="test-encryption-key-with-at-least-32-characters", **values)  # noqa: S106


@pytest.mark.asyncio
async def test_real_alerts_normalize_v2_evidence_and_discard_content() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "login.microsoftonline.com":
            return httpx.Response(200, json={"access_token": "test", "expires_in": 3600})
        return httpx.Response(200, json={"value": [{
            "id": "alert-1", "severity": "high", "status": "new",
            "createdDateTime": "2026-01-01T00:00:00Z",
            "evidence": [
                {"userAccount": {"azureAdUserId": "employee-1"}},
                {"subject": "sensitive", "deviceDnsName": "device-1"},
            ],
        }]})

    connector = RealGraphConnector(connector_settings(
        graph_client_id="test", graph_client_secret="test",  # noqa: S106
    ))
    await connector.client.aclose()
    connector.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        rows = await connector.security_alerts(TENANT, datetime(2026, 1, 1, tzinfo=UTC))
        assert rows[0]["userStates"] == [{"userId": "employee-1"}]
        assert rows[0]["deviceEvidence"] == [{"deviceDnsName": "device-1"}]
        assert "evidence" not in rows[0]
        assert "sensitive" not in str(rows)
        request = requests[-1]
        assert request.url.params["$filter"].startswith("lastUpdateDateTime ge")
        assert "userStates" not in request.url.params["$select"]
    finally:
        await connector.aclose()


@pytest.mark.asyncio
async def test_real_connector_rejects_foreign_continuation_before_credentials() -> None:
    connector = RealGraphConnector(connector_settings())
    try:
        with pytest.raises(RuntimeError, match="continuation URL"):
            await connector._get("https://other.example/next", TENANT)
    finally:
        await connector.aclose()
