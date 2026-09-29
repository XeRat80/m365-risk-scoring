from __future__ import annotations

import asyncio
import base64
import random
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel

from services.api.app.config import get_settings

settings = get_settings()
TENANTS = (
    uuid.UUID("00000000-0000-4000-8000-000000000001"),
    uuid.UUID("00000000-0000-4000-8000-000000000002"),
)
SCENARIOS = {"normal", "credential-phishing", "domain-spoofing", "executive-impersonation", "account-takeover", "mfa-removal", "entra-escalation", "throttling", "recovery"}
MAIL_SCENARIOS = {"credential-phishing", "domain-spoofing", "executive-impersonation"}
private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
public_numbers = private_key.public_key().public_numbers()
KID = "local-m365-risk-key"


def b64int(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


class State:
    def __init__(self) -> None:
        self.rng: dict[uuid.UUID, random.Random] = {}
        self.scenarios: dict[uuid.UUID, str] = {}
        self.active: dict[uuid.UUID, bool] = {}
        self.paused: dict[uuid.UUID, bool] = {}
        self.generated: dict[uuid.UUID, int] = {}
        self.target_users: dict[uuid.UUID, str | None] = {}
        self.simulation_runs: dict[uuid.UUID, uuid.UUID | None] = {}
        self.messages: dict[tuple[uuid.UUID, str], list[dict[str, Any]]] = {}
        self.users: dict[uuid.UUID, list[dict[str, Any]]] = {}
        self.sign_ins: dict[uuid.UUID, list[dict[str, Any]]] = {}
        self.security_alerts: dict[uuid.UUID, list[dict[str, Any]]] = {}
        self.registration: dict[tuple[uuid.UUID, str], bool] = {}
        self.capability: dict[tuple[uuid.UUID, str], bool] = {}
        self.risks: dict[tuple[uuid.UUID, str], str] = {}
        self.idempotency: set[tuple[uuid.UUID, str]] = set()
        self.consent_revoked: dict[uuid.UUID, bool] = {}
        self.expire_deltas: dict[uuid.UUID, bool] = {}
        self.partial_failure: dict[uuid.UUID, bool] = {}
        self.p2_available: dict[uuid.UUID, bool] = {}
        self.unavailable_mailbox: dict[uuid.UUID, str | None] = {}
        self.reset()

    def reset(self, target_tenant: uuid.UUID | None = None) -> None:
        tenants = TENANTS if target_tenant is None else (target_tenant,)
        for tenant in tenants:
            if tenant not in TENANTS:
                raise ValueError("Unknown tenant")
            self.rng[tenant] = random.Random(365 + TENANTS.index(tenant))
            self.scenarios[tenant] = "normal"
            self.active[tenant] = True
            self.paused[tenant] = False
            self.generated[tenant] = 0
            self.target_users[tenant] = None
            self.simulation_runs[tenant] = None
            self.consent_revoked[tenant] = False
            self.expire_deltas[tenant] = False
            self.partial_failure[tenant] = False
            self.p2_available[tenant] = True
            self.unavailable_mailbox[tenant] = None
            self.sign_ins[tenant] = []
            self.security_alerts[tenant] = []
            self.idempotency = {
                item for item in self.idempotency if item[0] != tenant
            }
            for collection in (
                self.messages,
                self.registration,
                self.capability,
                self.risks,
            ):
                for key in [item for item in collection if item[0] == tenant]:
                    del collection[key]
            tenant_users = []
            for number in range(1, 101):
                user_id = f"user-{number:03d}"
                tenant_users.append(
                    {
                        "id": user_id,
                        "displayName": f"User {number:03d}",
                        "userPrincipalName": f"user{number:03d}@tenant{str(tenant)[-1]}.example",
                        "isAdmin": number <= 5,
                    }
                )
                self.registration[(tenant, user_id)] = True
                self.capability[(tenant, user_id)] = True
                self.risks[(tenant, user_id)] = "none"
                self.messages[(tenant, user_id)] = []
                for day in range(14, 0, -1):
                    created_at = datetime.now(UTC) - timedelta(days=day, hours=number % 3)
                    self.sign_ins[tenant].append(
                        {
                            "id": f"signin-{user_id}-{day:02d}",
                            "userId": user_id,
                            "createdDateTime": created_at.isoformat().replace("+00:00", "Z"),
                            "status": {"errorCode": 0},
                            "isInteractive": True,
                            "location": {"city": "Tunis", "countryOrRegion": "TN"},
                            "ipAddress": f"10.{number % 250}.{day}.10",
                            "deviceDetail": {
                                "deviceId": f"device-{user_id}",
                                "isManaged": True,
                                "isCompliant": True,
                            },
                            "appId": "office-web",
                            "riskLevelDuringSignIn": "none",
                        }
                    )
                # One healthy daily message provides a stable history without
                # manufacturing abnormal volume. A current observation makes the
                # clean tenant immediately scoreable after reset.
                for day in range(7, 0, -1):
                    self.add_message(
                        tenant,
                        user_id,
                        "normal",
                        datetime.now(UTC) - timedelta(days=day, hours=number % 18),
                    )
                self.add_message(
                    tenant,
                    user_id,
                    "normal",
                    datetime.now(UTC) - timedelta(minutes=number),
                )
            self.users[tenant] = tenant_users

    def add_account_takeover_evidence(self, tenant: uuid.UUID, user_id: str) -> None:
        observed = datetime.now(UTC)
        self.sign_ins[tenant].append(
            {
                "id": f"signin-takeover-{len(self.sign_ins[tenant]) + 1}",
                "userId": user_id,
                "createdDateTime": observed.replace(hour=2).isoformat().replace("+00:00", "Z"),
                "status": {"errorCode": 50126},
                "isInteractive": True,
                "location": {"city": "Unknown", "countryOrRegion": "RU"},
                "ipAddress": "203.0.113.42",
                "deviceDetail": {
                    "deviceId": "unmanaged-device",
                    "isManaged": False,
                    "isCompliant": False,
                },
                "appId": "unknown-oauth-app",
                "riskLevelDuringSignIn": "high",
            }
        )
        self.security_alerts[tenant].append(
            {
                "id": f"alert-{len(self.security_alerts[tenant]) + 1}",
                "createdDateTime": observed.isoformat().replace("+00:00", "Z"),
                "severity": "high",
                "status": "new",
                "serviceSource": "microsoftDefenderForEndpoint",
                "category": "SuspiciousActivity",
                "userStates": [{"userId": user_id}],
                "deviceEvidence": [{"deviceDnsName": "unmanaged-device"}],
            }
        )

    def add_message(self, tenant: uuid.UUID, user_id: str, scenario: str, received: datetime | None = None) -> None:
        rng = self.rng[tenant]
        malicious = scenario != "normal" and rng.random() < 0.85
        message_id = f"msg-{self.generated[tenant] + 1:09d}"
        tenant_domain = f"tenant{str(tenant)[-1]}.example"
        recipient_address = f"{user_id}@{tenant_domain}"
        external = malicious or rng.random() < 0.28
        if scenario == "domain-spoofing" and malicious:
            from_address = f"executive@{tenant_domain}"
            sender_address = "relay@spoofed-domain.example"
        elif scenario == "account-takeover" and malicious:
            from_address = f"colleague@{tenant_domain}"
            sender_address = from_address
        elif external:
            from_address = "sender@partner.example"
            sender_address = from_address
        else:
            from_address = f"colleague@{tenant_domain}"
            sender_address = from_address
        reply_address = (
            "capture@credential-review.example"
            if malicious and scenario in {"credential-phishing", "domain-spoofing"}
            else from_address
        )
        auth = {
            "spf": "fail" if malicious else "pass",
            "dkim": "fail" if malicious and scenario != "account-takeover" else "pass",
            "dmarc": "fail" if malicious else "pass",
        }
        received_at = received or datetime.now(UTC)
        hops = rng.randint(2, 10 if malicious else 6)
        internet_headers = [
            {"name": "Message-ID", "value": f"<{message_id}@{sender_address.split('@')[-1]}>"},
            {"name": "Date", "value": received_at.strftime("%a, %d %b %Y %H:%M:%S +0000")},
            {"name": "From", "value": from_address},
            {"name": "Return-Path", "value": f"<{sender_address}>"},
            {"name": "Reply-To", "value": reply_address},
            {"name": "Content-Type", "value": "multipart/alternative" if malicious else "text/plain"},
            {"name": "Authentication-Results", "value": "; ".join(f"{k}={v}" for k, v in auth.items())},
            *(
                {"name": "Received", "value": f"by relay-{number}.example"}
                for number in range(hops)
            ),
        ]
        message = {
            "id": message_id,
            "receivedDateTime": received_at.isoformat().replace("+00:00", "Z"),
            "sender": {"emailAddress": {"address": sender_address}},
            "from": {"emailAddress": {"address": from_address}},
            "toRecipients": [{"emailAddress": {"address": recipient_address}}],
            "ccRecipients": [],
            "externalSender": external,
            "recipientCount": rng.randint(1, 4),
            "hasAttachments": rng.random() < (0.45 if malicious else 0.12),
            "importance": "high" if malicious and rng.random() < 0.4 else "normal",
            "authenticationResults": auth,
            "replyToDomainMismatch": malicious and scenario in {"credential-phishing", "domain-spoofing"},
            "fromSenderMismatch": malicious and scenario in {"domain-spoofing", "executive-impersonation"},
            "receivedHops": hops,
            "internetMessageHeaders": internet_headers,
        }
        self.messages[(tenant, user_id)].append(message)
        self.generated[tenant] += 1


state = State()


async def generator() -> None:
    while True:
        for tenant in TENANTS:
            if state.active[tenant] and not state.paused[tenant]:
                target = state.rng[tenant].choice(state.users[tenant])["id"]
                # Background traffic stays healthy. An attack only affects the selected
                # employee through the explicit scenario injection below.
                state.add_message(tenant, target, "normal")
        # Normal background activity is deliberately low-volume. Scenarios still
        # inject their targeted evidence immediately.
        await asyncio.sleep(600)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    task = asyncio.create_task(generator())
    yield
    task.cancel()


app = FastAPI(title="Mock Microsoft Graph", version="0.1.0", lifespan=lifespan)


def require_admin(x_mock_admin: str | None = Header(default=None)) -> None:
    if settings.connector_mode != "mock":
        raise HTTPException(status_code=404, detail="Simulator disabled")
    if x_mock_admin != settings.mock_admin_secret:
        raise HTTPException(status_code=403, detail="Mock administrator secret required")


def tenant(x_tenant_id: str | None = Header(default=None)) -> uuid.UUID:
    try:
        value = uuid.UUID(x_tenant_id or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="X-Tenant-ID required") from exc
    if value not in TENANTS:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return value


@app.get("/health/live")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/.well-known/openid-configuration")
async def oidc() -> dict[str, str]:
    return {
        "issuer": settings.oidc_issuer,
        "jwks_uri": f"{settings.oidc_issuer}/.well-known/jwks.json",
        "token_endpoint": f"{settings.oidc_issuer}/oauth2/v2.0/token",
    }


@app.get("/.well-known/jwks.json")
async def jwks() -> dict[str, object]:
    return {"keys": [{"kty": "RSA", "kid": KID, "use": "sig", "alg": "RS256", "n": b64int(public_numbers.n), "e": b64int(public_numbers.e)}]}


class TokenBody(BaseModel):
    tenant_id: uuid.UUID
    role: str = "analyst"


@app.post("/oauth2/v2.0/token")
async def token_endpoint(
    payload: TokenBody,
    x_mock_admin: str | None = Header(default=None, alias="X-Mock-Admin"),
) -> dict[str, object]:
    require_admin(x_mock_admin)
    if payload.tenant_id not in TENANTS or payload.role not in {"analyst", "admin"}:
        raise HTTPException(status_code=422, detail="Invalid tenant or role")
    now = int(time.time())
    token = jwt.encode(
        {"iss": settings.oidc_issuer, "aud": settings.oidc_audience, "sub": f"local-{payload.role}", "tid": str(payload.tenant_id), "role": payload.role, "iat": now, "exp": now + 3600},
        private_key,
        algorithm="RS256",
        headers={"kid": KID},
    )
    return {"access_token": token, "token_type": "bearer", "expires_in": 3600}


@app.get("/v1.0/users")
async def list_users(x_tenant_id: str | None = Header(default=None), x_mock_admin: str | None = Header(default=None)) -> dict[str, object]:
    require_admin(x_mock_admin)
    tenant_id = tenant(x_tenant_id)
    if state.consent_revoked[tenant_id]:
        raise HTTPException(status_code=403, detail="Admin consent revoked")
    return {"value": state.users[tenant_id]}


@app.get("/v1.0/reports/authenticationMethods/userRegistrationDetails")
async def registrations(x_tenant_id: str | None = Header(default=None), x_mock_admin: str | None = Header(default=None)) -> dict[str, object]:
    require_admin(x_mock_admin)
    tenant_id = tenant(x_tenant_id)
    if state.consent_revoked[tenant_id]:
        raise HTTPException(status_code=403, detail="Admin consent revoked")
    return {
        "value": [
            {
                "id": user["id"],
                "isMfaRegistered": state.registration[(tenant_id, user["id"])],
                "isMfaCapable": state.capability[(tenant_id, user["id"])],
            }
            for user in state.users[tenant_id]
        ]
    }


@app.get("/v1.0/identityProtection/riskyUsers")
async def risky_users(x_tenant_id: str | None = Header(default=None), x_mock_admin: str | None = Header(default=None)) -> dict[str, object]:
    require_admin(x_mock_admin)
    tenant_id = tenant(x_tenant_id)
    if state.consent_revoked[tenant_id]:
        raise HTTPException(status_code=403, detail="Admin consent revoked")
    if not state.p2_available[tenant_id]:
        raise HTTPException(status_code=403, detail="Microsoft Entra ID P2 is unavailable")
    return {"value": [{"id": user["id"], "riskLevel": state.risks[(tenant_id, user["id"])], "riskState": "atRisk"} for user in state.users[tenant_id]]}


@app.get("/v1.0/auditLogs/signIns")
async def sign_ins(
    x_tenant_id: str | None = Header(default=None),
    x_mock_admin: str | None = Header(default=None),
) -> dict[str, object]:
    require_admin(x_mock_admin)
    tenant_id = tenant(x_tenant_id)
    if state.consent_revoked[tenant_id]:
        raise HTTPException(status_code=403, detail="Admin consent revoked")
    return {"value": state.sign_ins[tenant_id]}


@app.get("/v1.0/security/alerts_v2")
async def security_alerts(
    x_tenant_id: str | None = Header(default=None),
    x_mock_admin: str | None = Header(default=None),
) -> dict[str, object]:
    require_admin(x_mock_admin)
    tenant_id = tenant(x_tenant_id)
    if state.consent_revoked[tenant_id]:
        raise HTTPException(status_code=403, detail="Admin consent revoked")
    return {"value": state.security_alerts[tenant_id]}


@app.get("/v1.0/users/{user_id}/mailFolders/inbox/messages/delta")
async def message_delta(
    request: Request,
    user_id: str,
    x_tenant_id: str | None = Header(default=None),
    x_mock_admin: str | None = Header(default=None),
    skiptoken: int = Query(default=0, alias="$skiptoken"),
    deltatoken: int | None = Query(default=None, alias="$deltatoken"),
    page_size: int = Query(default=100, alias="$top", ge=1, le=1000),
) -> dict[str, object]:
    require_admin(x_mock_admin)
    tenant_id = tenant(x_tenant_id)
    if state.partial_failure[tenant_id] and user_id == "user-100":
        raise HTTPException(status_code=503, detail="Simulated mailbox partial failure")
    if state.unavailable_mailbox[tenant_id] == user_id:
        raise HTTPException(status_code=404, detail="Mailbox is unavailable")
    if state.consent_revoked[tenant_id]:
        raise HTTPException(status_code=403, detail="Admin consent revoked")
    if state.scenarios[tenant_id] == "throttling" and state.rng[tenant_id].random() < 0.35:
        raise HTTPException(status_code=429, detail="Simulated throttling", headers={"Retry-After": "1"})
    messages = state.messages.get((tenant_id, user_id))
    if messages is None:
        raise HTTPException(status_code=404, detail="Mailbox not found")
    if deltatoken is not None and (
        state.expire_deltas[tenant_id] or deltatoken > len(messages)
    ):
        raise HTTPException(status_code=410, detail="Delta token expired")
    start = deltatoken if deltatoken is not None else skiptoken
    page = messages[start : start + page_size]
    base = str(request.url).split("?")[0]
    payload: dict[str, object] = {"value": page}
    next_index = start + len(page)
    if next_index < len(messages):
        payload["@odata.nextLink"] = f"{base}?$skiptoken={next_index}"
    else:
        payload["@odata.deltaLink"] = f"{base}?$deltatoken={len(messages)}"
    return payload


def status(tenant_id: uuid.UUID = TENANTS[0]) -> dict[str, object]:
    return {
        "active": state.active[tenant_id],
        "scenario": state.scenarios[tenant_id],
        "paused": state.paused[tenant_id],
        "generated_messages": state.generated[tenant_id],
        "target_user_id": state.target_users[tenant_id],
        "simulation_run_id": state.simulation_runs[tenant_id],
    }


@app.get("/__admin/status")
async def admin_status(
    tenant_id: uuid.UUID = TENANTS[0],
    x_mock_admin: str | None = Header(default=None),
) -> dict[str, object]:
    require_admin(x_mock_admin)
    if tenant_id not in TENANTS:
        raise HTTPException(status_code=404, detail="Unknown tenant")
    return status(tenant_id)


@app.post("/__admin/scenarios/{scenario}/start")
async def start_scenario(
    scenario: str,
    idempotency_key: str,
    tenant_id: uuid.UUID | None = None,
    target_user_id: str = "user-001",
    simulation_run_id: uuid.UUID | None = None,
    x_mock_admin: str | None = Header(default=None),
) -> dict[str, object]:
    require_admin(x_mock_admin)
    if scenario not in SCENARIOS:
        raise HTTPException(status_code=422, detail="Unknown scenario")
    target_tenant = tenant_id or TENANTS[0]
    if target_tenant not in TENANTS:
        raise HTTPException(status_code=404, detail="Unknown tenant")
    idempotency = (target_tenant, idempotency_key)
    if idempotency in state.idempotency:
        return status(target_tenant)
    state.idempotency.add(idempotency)
    state.scenarios[target_tenant] = scenario
    state.active[target_tenant] = True
    state.paused[target_tenant] = False
    if target_user_id not in {str(user["id"]) for user in state.users[target_tenant]}:
        raise HTTPException(status_code=404, detail="Target user not found")
    target_user = target_user_id
    state.target_users[target_tenant] = target_user
    state.simulation_runs[target_tenant] = simulation_run_id
    if scenario == "mfa-removal":
        state.registration[(target_tenant, target_user)] = False
    if scenario == "entra-escalation":
        state.risks[(target_tenant, target_user)] = "high"
    if scenario == "account-takeover":
        state.risks[(target_tenant, target_user)] = "high"
        state.add_account_takeover_evidence(target_tenant, target_user)
    if scenario == "recovery":
        state.registration[(target_tenant, target_user)] = True
        state.risks[(target_tenant, target_user)] = "none"
        state.scenarios[target_tenant] = "normal"
        state.consent_revoked[target_tenant] = False
        state.expire_deltas[target_tenant] = False
        state.partial_failure[target_tenant] = False
        state.p2_available[target_tenant] = True
        state.unavailable_mailbox[target_tenant] = None
    injected_scenario = scenario if scenario in MAIL_SCENARIOS else "normal"
    for _ in range(30 if scenario in MAIL_SCENARIOS else 5):
        state.add_message(target_tenant, target_user, injected_scenario)
    return status(target_tenant)


@app.post("/__admin/stop")
async def stop(
    tenant_id: uuid.UUID = TENANTS[0],
    x_mock_admin: str | None = Header(default=None),
) -> dict[str, object]:
    require_admin(x_mock_admin)
    if tenant_id not in TENANTS:
        raise HTTPException(status_code=404, detail="Unknown tenant")
    state.paused[tenant_id] = True
    return status(tenant_id)


@app.post("/__admin/reset")
async def reset(
    tenant_id: uuid.UUID | None = None,
    x_mock_admin: str | None = Header(default=None),
) -> dict[str, object]:
    require_admin(x_mock_admin)
    target_tenant = tenant_id or TENANTS[0]
    if target_tenant not in TENANTS:
        raise HTTPException(status_code=404, detail="Unknown tenant")
    state.reset(target_tenant)
    return status(target_tenant)


@app.post("/__admin/faults/{fault}/start")
async def start_fault(
    fault: str,
    tenant_id: uuid.UUID = TENANTS[0],
    x_mock_admin: str | None = Header(default=None),
) -> dict[str, object]:
    require_admin(x_mock_admin)
    if tenant_id not in TENANTS:
        raise HTTPException(status_code=404, detail="Unknown tenant")
    if fault == "expired-delta":
        state.expire_deltas[tenant_id] = True
    elif fault == "revoked-consent":
        state.consent_revoked[tenant_id] = True
    elif fault == "partial-failure":
        state.partial_failure[tenant_id] = True
    elif fault == "missing-p2":
        state.p2_available[tenant_id] = False
    elif fault == "unavailable-mailbox":
        state.unavailable_mailbox[tenant_id] = "user-099"
    else:
        raise HTTPException(status_code=422, detail="Unknown fault")
    return {**status(tenant_id), "fault": fault}


@app.post("/__admin/messages/{user_id}/delete")
async def delete_message(
    user_id: str,
    x_tenant_id: str | None = Header(default=None),
    x_mock_admin: str | None = Header(default=None),
) -> dict[str, object]:
    require_admin(x_mock_admin)
    tenant_id = tenant(x_tenant_id)
    messages = state.messages.get((tenant_id, user_id))
    if not messages:
        raise HTTPException(status_code=404, detail="Message not found")
    deleted_id = str(messages[-1]["id"])
    messages.append({"id": deleted_id, "@removed": {"reason": "deleted"}})
    return {"deleted": deleted_id}


@app.post("/__admin/burst")
async def burst(
    count: int = Query(ge=1, le=5000),
    scenario: str = "credential-phishing",
    x_tenant_id: str | None = Header(default=None),
    x_mock_admin: str | None = Header(default=None),
) -> dict[str, object]:
    require_admin(x_mock_admin)
    tenant_id = tenant(x_tenant_id)
    if scenario not in SCENARIOS:
        raise HTTPException(status_code=422, detail="Unknown scenario")
    for _ in range(count):
        state.add_message(tenant_id, "user-001", scenario)
    return {"generated": count, **status(tenant_id)}
