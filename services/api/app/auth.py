from __future__ import annotations

import uuid
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from .config import get_settings

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    tenant_id: uuid.UUID
    subject: str
    role: str


def current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> Principal:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Bearer token required")
    settings = get_settings()
    try:
        jwks = PyJWKClient(
            settings.oidc_jwks_url
            or f"{settings.oidc_issuer}/.well-known/jwks.json"
        )
        key = jwks.get_signing_key_from_jwt(credentials.credentials)
        claims = jwt.decode(
            credentials.credentials,
            key.key,
            algorithms=["RS256"],
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer,
            options={"require": ["exp", "iat", "iss", "aud", "sub", "tid"]},
        )
        claimed_role = claims.get("role")
        if not claimed_role:
            roles = claims.get("roles", [])
            if not isinstance(roles, list):
                raise ValueError("roles claim must be an array")
            if settings.oidc_admin_role in roles:
                claimed_role = "admin"
            elif settings.oidc_analyst_role in roles:
                claimed_role = "analyst"
            else:
                raise ValueError("An API analyst or administrator role is required")
        role = str(claimed_role)
        if role not in {"admin", "analyst"}:
            raise ValueError("unsupported role")
        return Principal(
            tenant_id=uuid.UUID(claims["tid"]),
            subject=str(claims["sub"]),
            role=role,
        )
    except (jwt.PyJWTError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid access token") from exc


def require_admin(principal: Principal = Depends(current_principal)) -> Principal:
    if principal.role != "admin":
        raise HTTPException(status_code=403, detail="Administrator role required")
    return principal
