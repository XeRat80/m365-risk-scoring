from __future__ import annotations

import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from services.api.app import auth


class StaticJwks:
    def __init__(self, _: str, key: object) -> None:
        self.key = key

    def get_signing_key_from_jwt(self, _: str) -> StaticJwks:
        return self


def token(
    key: object,
    *,
    audience: str = "m365-risk-api",
    issuer: str = "http://localhost:8081",
    tenant: str | None = "00000000-0000-4000-8000-000000000001",
    role: str | None = "analyst",
    roles: list[str] | None = None,
) -> str:
    now = int(time.time())
    claims = {
            "iss": issuer,
            "aud": audience,
            "sub": "analyst-1",
            "iat": now,
            "exp": now + 300,
        }
    if role is not None:
        claims["role"] = role
    if roles is not None:
        claims["roles"] = roles
    if tenant is not None:
        claims["tid"] = tenant
    return jwt.encode(
        claims,
        key,
        algorithm="RS256",
    )


def test_validated_claims_are_the_only_tenant_source(monkeypatch: pytest.MonkeyPatch) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(auth, "PyJWKClient", lambda url: StaticJwks(url, key.public_key()))
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token(key))
    principal = auth.current_principal(credentials)
    assert principal.tenant_id == uuid.UUID("00000000-0000-4000-8000-000000000001")
    assert principal.subject == "analyst-1"
    with pytest.raises(HTTPException) as denied:
        auth.require_admin(principal)
    assert denied.value.status_code == 403


def test_wrong_audience_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(auth, "PyJWKClient", lambda url: StaticJwks(url, key.public_key()))
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token(key, audience="wrong"))
    with pytest.raises(HTTPException) as denied:
        auth.current_principal(credentials)
    assert denied.value.status_code == 401


def test_standard_oidc_roles_array_maps_to_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(auth, "PyJWKClient", lambda url: StaticJwks(url, key.public_key()))
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer",
        credentials=token(key, role=None, roles=["M365Risk.Admin"]),
    )
    principal = auth.current_principal(credentials)
    assert principal.role == "admin"
    assert auth.require_admin(principal) is principal


@pytest.mark.parametrize(
    ("kwargs", "different_signing_key"),
    [
        ({"issuer": "https://attacker.invalid"}, False),
        ({"tenant": None}, False),
        ({"tenant": "not-a-uuid"}, False),
        ({}, True),
    ],
)
def test_wrong_issuer_signature_and_tenant_claims_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, str | None],
    different_signing_key: bool,
) -> None:
    signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwks_key = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048)
        if different_signing_key
        else signing_key
    )
    monkeypatch.setattr(
        auth, "PyJWKClient", lambda url: StaticJwks(url, jwks_key.public_key())
    )
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials=token(signing_key, **kwargs)
    )
    with pytest.raises(HTTPException) as denied:
        auth.current_principal(credentials)
    assert denied.value.status_code == 401
