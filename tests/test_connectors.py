from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import httpx
import pytest

from services.api.app.config import Settings
from services.api.app.connectors import MockGraphConnector, RealGraphConnector, connector_for

TENANT = uuid.UUID("00000000-0000-4000-8000-000000000001")


def connector_settings(**values: str) -> Settings:
    return Settings(
        token_encryption_key="unit-test-master-key-with-at-least-32-characters",  # noqa: S106
        mock_admin_secret="unit-test-mock-admin-secret",  # noqa: S106
        metrics_key="unit-test-metrics-key-long-enough",
        **values,
    )


@pytest.mark.asyncio
async def test_mock_connector_pages_collections_and_delta() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/v1.0/users":
            if request.url.params.get("page") == "2":
                return httpx.Response(200, json={"value": [{"id": "user-2"}]})
            return httpx.Response(
                200,
                json={"value": [{"id": "user-1"}], "@odata.nextLink": "http://mock/v1.0/users?page=2"},
            )
        return httpx.Response(
            200,
            json={"value": [{"id": "message-1"}], "@odata.deltaLink": "http://mock/delta?token=1"},
        )

    connector = MockGraphConnector(connector_settings(mock_graph_url="http://mock"))
    await connector.client.aclose()
    connector.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert [item["id"] for item in await connector.users(TENANT)] == ["user-1", "user-2"]
    messages, delta = await connector.messages(TENANT, "user-1")
    assert messages == [{"id": "message-1"}]
    assert delta == "http://mock/delta?token=1"
    assert all(request.headers["x-tenant-id"] == str(TENANT) for request in requests)
    message_request = next(request for request in requests if "messages/delta" in request.url.path)
    selected = message_request.url.params["$select"].split(",")
    assert "subject" not in selected
    assert "body" not in selected
    assert "internetMessageHeaders" in selected
    await connector.client.aclose()


@pytest.mark.asyncio
async def test_observation_connectors_use_bounded_privacy_safe_projections() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"value": []})

    connector = MockGraphConnector(connector_settings(mock_graph_url="http://mock"))
    await connector.client.aclose()
    connector.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    since = datetime(2026, 1, 1, tzinfo=UTC)
    assert await connector.sign_ins(TENANT, since) == []
    assert await connector.security_alerts(TENANT, since) == []
    sign_in_request, alert_request = requests
    assert sign_in_request.url.path == "/v1.0/auditLogs/signIns"
    assert "createdDateTime ge 2026-01-01T00:00:00Z" == sign_in_request.url.params["$filter"]
    assert "ipAddress" in sign_in_request.url.params["$select"]
    assert alert_request.url.path == "/v1.0/security/alerts_v2"
    assert "userStates" in alert_request.url.params["$select"]
    await connector.client.aclose()


@pytest.mark.asyncio
async def test_real_connector_acquires_and_caches_tenant_token() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=json.dumps({"access_token": "graph-token", "expires_in": 3600}))

    connector = RealGraphConnector(
        connector_settings(
            connector_mode="real",
            graph_client_id="client",
            graph_client_secret="secret",  # noqa: S106
        )
    )
    await connector.client.aclose()
    connector.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert (await connector.headers(TENANT))["Authorization"] == "Bearer graph-token"
    assert (await connector.headers(TENANT))["Authorization"] == "Bearer graph-token"
    assert calls == 1
    assert isinstance(connector_for(connector.settings), RealGraphConnector)
    await connector.client.aclose()


@pytest.mark.asyncio
async def test_real_connector_uses_tenant_credential_provider() -> None:
    posted: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        posted.append(request.content.decode())
        return httpx.Response(200, json={"access_token": "tenant-token", "expires_in": 3600})

    async def credentials(tenant_id: uuid.UUID) -> tuple[str, str]:
        assert tenant_id == TENANT
        return "stored-client", "decrypted-tenant-secret"

    settings = connector_settings(connector_mode="real")
    connector = RealGraphConnector(settings, credentials)
    await connector.client.aclose()
    connector.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert await connector.access_token(TENANT) == "tenant-token"
    assert "client_id=stored-client" in posted[0]
    assert "client_secret=decrypted-tenant-secret" in posted[0]
    assert isinstance(connector_for(settings, credentials), RealGraphConnector)
    await connector.client.aclose()


@pytest.mark.asyncio
async def test_retry_after_and_bounded_retry_are_honored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                429, headers={"Retry-After": "3"}, json={"error": "throttled"}
            )
        return httpx.Response(200, json={"value": []})

    sleep = AsyncMock()
    monkeypatch.setattr("services.api.app.connectors.asyncio.sleep", sleep)
    connector = MockGraphConnector(connector_settings(mock_graph_url="http://mock"))
    await connector.client.aclose()
    connector.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert await connector.users(TENANT) == []
    sleep.assert_awaited_once_with(3.0)
    assert calls == 2
    await connector.client.aclose()


@pytest.mark.asyncio
async def test_expired_delta_restarts_from_a_fresh_collection() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "expired" in str(request.url):
            return httpx.Response(410, json={"error": "syncStateNotFound"})
        return httpx.Response(200, json={"value": [], "@odata.deltaLink": "http://mock/fresh"})

    connector = MockGraphConnector(connector_settings(mock_graph_url="http://mock"))
    await connector.client.aclose()
    connector.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    messages, delta = await connector.messages(TENANT, "user-1", "http://mock/expired")
    assert messages == []
    assert delta == "http://mock/fresh"
    assert len(calls) == 2
    await connector.client.aclose()


@pytest.mark.asyncio
async def test_mock_delta_link_rebases_between_host_and_compose() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(
            200,
            json={"value": [], "@odata.deltaLink": "http://mock-graph:8081/delta?token=2"},
        )

    connector = MockGraphConnector(
        connector_settings(mock_graph_url="http://mock-graph:8081")
    )
    await connector.client.aclose()
    connector.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await connector.messages(
        TENANT,
        "user-1",
        "http://localhost:8081/v1.0/users/user-1/messages/delta?$deltatoken=1",
    )
    assert calls == [
        "http://mock-graph:8081/v1.0/users/user-1/messages/delta?$deltatoken=1"
    ]
    await connector.client.aclose()
