from __future__ import annotations

import abc
import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from .config import Settings


class GraphThrottled(RuntimeError):
    def __init__(self, retry_after: float) -> None:
        super().__init__(f"Microsoft Graph throttled the request for {retry_after} seconds")
        self.retry_after = retry_after


class GraphDeltaExpired(RuntimeError):
    pass


class GraphConnector(abc.ABC):
    @abc.abstractmethod
    async def users(self, tenant_id: uuid.UUID) -> list[dict[str, Any]]: ...

    @abc.abstractmethod
    async def registration_details(self, tenant_id: uuid.UUID) -> list[dict[str, Any]]: ...

    @abc.abstractmethod
    async def risky_users(self, tenant_id: uuid.UUID) -> list[dict[str, Any]]: ...

    @abc.abstractmethod
    async def messages(
        self, tenant_id: uuid.UUID, user_id: str, delta_link: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]: ...

    async def sign_ins(
        self, tenant_id: uuid.UUID, since: datetime
    ) -> list[dict[str, Any]]:
        """Optional identity telemetry; older/test connectors may return no observations."""
        return []

    async def security_alerts(
        self, tenant_id: uuid.UUID, since: datetime
    ) -> list[dict[str, Any]]:
        """Optional Defender telemetry; absence must be represented as unavailable."""
        return []


class HttpGraphConnector(GraphConnector):
    base_url: str

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = httpx.AsyncClient(timeout=20)

    async def headers(self, tenant_id: uuid.UUID) -> dict[str, str]:
        raise NotImplementedError

    async def aclose(self) -> None:
        await self.client.aclose()

    async def _get(self, url: str, tenant_id: uuid.UUID) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                response = await self.client.get(url, headers=await self.headers(tenant_id))
                if response.status_code == 429:
                    try:
                        retry_after = max(0.0, float(response.headers.get("Retry-After", "1")))
                    except ValueError:
                        retry_after = 1.0
                    raise GraphThrottled(retry_after)
                if response.status_code == 410:
                    raise GraphDeltaExpired("Graph delta token expired")
                if response.status_code >= 500:
                    response.raise_for_status()
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise RuntimeError("Graph response must be a JSON object")
                return payload
            except GraphDeltaExpired:
                raise
            except (httpx.TransportError, httpx.HTTPStatusError, GraphThrottled) as exc:
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                    raise
                last_error = exc
                if attempt == 4:
                    raise
                exponential = min(8.0, 0.5 * (2**attempt))
                retry_after = exc.retry_after if isinstance(exc, GraphThrottled) else 0.0
                await asyncio.sleep(max(exponential, retry_after))
        raise RuntimeError("Graph retry loop exited unexpectedly") from last_error

    async def _collection(self, url: str, tenant_id: uuid.UUID) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        next_link: object | None = None
        for _ in range(1000):
            payload = await self._get(url, tenant_id)
            items.extend(payload.get("value", []))
            next_link = payload.get("@odata.nextLink")
            if not next_link:
                break
            url = str(next_link)
        if next_link:
            raise RuntimeError("Graph collection paging exceeded the safety limit")
        return items

    async def users(self, tenant_id: uuid.UUID) -> list[dict[str, Any]]:
        return await self._collection(
            f"{self.base_url}/v1.0/users?$select=id,displayName,userPrincipalName,accountEnabled", tenant_id
        )

    async def registration_details(self, tenant_id: uuid.UUID) -> list[dict[str, Any]]:
        return await self._collection(
            f"{self.base_url}/v1.0/reports/authenticationMethods/userRegistrationDetails"
            "?$select=id,isMfaRegistered,isMfaCapable",
            tenant_id,
        )

    async def risky_users(self, tenant_id: uuid.UUID) -> list[dict[str, Any]]:
        return await self._collection(
            f"{self.base_url}/v1.0/identityProtection/riskyUsers?$select=id,riskLevel,riskState", tenant_id
        )

    async def sign_ins(
        self, tenant_id: uuid.UUID, since: datetime
    ) -> list[dict[str, Any]]:
        timestamp = quote(since.isoformat().replace("+00:00", "Z"), safe="-:TZ")
        return await self._collection(
            f"{self.base_url}/v1.0/auditLogs/signIns"
            f"?$filter=createdDateTime%20ge%20{timestamp}"
            "&$select=id,userId,createdDateTime,status,isInteractive,location,ipAddress,"
            "deviceDetail,appId,riskLevelDuringSignIn&$top=999",
            tenant_id,
        )

    async def security_alerts(
        self, tenant_id: uuid.UUID, since: datetime
    ) -> list[dict[str, Any]]:
        timestamp = quote(since.isoformat().replace("+00:00", "Z"), safe="-:TZ")
        return await self._collection(
            f"{self.base_url}/v1.0/security/alerts_v2"
            f"?$filter=createdDateTime%20ge%20{timestamp}"
            "&$select=id,createdDateTime,severity,status,serviceSource,category,"
            "userStates,deviceEvidence&$top=999",
            tenant_id,
        )

    async def messages(
        self, tenant_id: uuid.UUID, user_id: str, delta_link: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        url = delta_link or (
            f"{self.base_url}/v1.0/users/{user_id}/mailFolders/inbox/messages/delta"
            "?$select=id,receivedDateTime,sender,from,toRecipients,ccRecipients,hasAttachments,"
            "importance,internetMessageHeaders&$top=100"
        )
        collected: list[dict[str, Any]] = []
        final_delta: str | None = None
        next_link: object | None = None
        for _ in range(1000):
            try:
                payload = await self._get(url, tenant_id)
            except GraphDeltaExpired:
                if delta_link:
                    return await self.messages(tenant_id, user_id, None)
                raise
            collected.extend(payload.get("value", []))
            next_link = payload.get("@odata.nextLink")
            final_delta = payload.get("@odata.deltaLink", final_delta)
            if not next_link:
                break
            url = str(next_link)
        if next_link:
            raise RuntimeError("Graph message paging exceeded the safety limit")
        return collected, final_delta


class MockGraphConnector(HttpGraphConnector):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.base_url = settings.mock_graph_url

    async def headers(self, tenant_id: uuid.UUID) -> dict[str, str]:
        return {"X-Tenant-ID": str(tenant_id), "X-Mock-Admin": self.settings.mock_admin_secret}

    async def risky_users(self, tenant_id: uuid.UUID) -> list[dict[str, Any]]:
        try:
            return await super().risky_users(tenant_id)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403 and "P2" in exc.response.text:
                return []
            raise

    async def messages(
        self, tenant_id: uuid.UUID, user_id: str, delta_link: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        if delta_link:
            configured = urlsplit(self.base_url)
            checkpoint = urlsplit(delta_link)
            delta_link = urlunsplit(
                (
                    configured.scheme,
                    configured.netloc,
                    checkpoint.path,
                    checkpoint.query,
                    checkpoint.fragment,
                )
            )
        return await super().messages(tenant_id, user_id, delta_link)


class RealGraphConnector(HttpGraphConnector):
    async def _get(self, url: str, tenant_id: uuid.UUID) -> dict[str, Any]:
        parsed = urlsplit(url)
        if (parsed.scheme, parsed.netloc) != ("https", "graph.microsoft.com"):
            raise RuntimeError("Rejected Graph continuation URL outside Microsoft Graph")
        return await super()._get(url, tenant_id)

    async def security_alerts(
        self, tenant_id: uuid.UUID, since: datetime
    ) -> list[dict[str, Any]]:
        timestamp = quote(since.isoformat().replace("+00:00", "Z"), safe="-:TZ")
        rows = await self._collection(
            f"{self.base_url}/v1.0/security/alerts_v2"
            f"?$filter=lastUpdateDateTime%20ge%20{timestamp}"
            "&$top=100",
            tenant_id,
        )
        # Translate v2 evidence into the worker's metadata contract. Never retain
        # evidence payloads (which can contain message subjects or other content).
        normalized: list[dict[str, Any]] = []
        for row in rows:
            users: set[str] = set()
            devices: list[dict[str, str]] = []
            for evidence in row.get("evidence") or []:
                if not isinstance(evidence, dict):
                    continue
                account = evidence.get("userAccount")
                if isinstance(account, dict) and account.get("azureAdUserId"):
                    users.add(str(account["azureAdUserId"]))
                if evidence.get("deviceDnsName"):
                    devices.append({"deviceDnsName": str(evidence["deviceDnsName"])})
            normalized.append({
                **{key: row.get(key) for key in (
                    "id", "createdDateTime", "lastUpdateDateTime", "severity",
                    "status", "serviceSource", "category",
                )},
                "userStates": [{"userId": user} for user in sorted(users)],
                "deviceEvidence": devices,
            })
        return normalized

    def __init__(
        self,
        settings: Settings,
        credential_provider: Callable[[uuid.UUID], Awaitable[tuple[str, str]]] | None = None,
    ) -> None:
        super().__init__(settings)
        self.base_url = "https://graph.microsoft.com"
        self._tokens: dict[uuid.UUID, tuple[str, float]] = {}
        self.credential_provider = credential_provider

    async def access_token(self, tenant_id: uuid.UUID) -> str:
        cached = self._tokens.get(tenant_id)
        if cached and cached[1] > time.time() + 60:
            return cached[0]
        client_id: str | None
        client_secret: str | None
        if self.credential_provider:
            client_id, client_secret = await self.credential_provider(tenant_id)
        else:
            client_id = self.settings.graph_client_id
            client_secret = self.settings.graph_client_secret
        if not client_id or not client_secret:
            raise RuntimeError("Connected Graph credentials are not available for this tenant")
        response = await self.client.post(
            f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
                "scope": "https://graph.microsoft.com/.default",
            },
        )
        response.raise_for_status()
        payload = response.json()
        token = str(payload["access_token"])
        self._tokens[tenant_id] = (token, time.time() + int(payload.get("expires_in", 3600)))
        return token

    async def headers(self, tenant_id: uuid.UUID) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {await self.access_token(tenant_id)}",
            "Prefer": 'IdType="ImmutableId"',
        }

    async def users(self, tenant_id: uuid.UUID) -> list[dict[str, Any]]:
        users = await super().users(tenant_id)
        roles = await self._collection(
            f"{self.base_url}/v1.0/directoryRoles?$select=id,displayName", tenant_id
        )
        privileged: set[str] = set()
        for role in roles:
            role_id = str(role["id"])
            members = await self._collection(
                f"{self.base_url}/v1.0/directoryRoles/{role_id}/members?$select=id",
                tenant_id,
            )
            privileged.update(str(member["id"]) for member in members)
        for user in users:
            user["isAdmin"] = str(user["id"]) in privileged
        return users

    # Optional-source HTTP errors must reach the worker. Returning [] here would
    # turn a 403 or missing licence into an apparently healthy zero-risk result.


def connector_for(
    settings: Settings,
    credential_provider: Callable[[uuid.UUID], Awaitable[tuple[str, str]]] | None = None,
) -> GraphConnector:
    if settings.connector_mode == "mock":
        return MockGraphConnector(settings)
    return RealGraphConnector(settings, credential_provider)
