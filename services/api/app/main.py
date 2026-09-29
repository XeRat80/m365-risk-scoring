from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode

import httpx
import jwt
import structlog
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from sqlalchemy import and_, delete, desc, func, or_, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.exceptions import HTTPException as StarletteHTTPException

from packages.ml.m365risk_ml.dataset_compat import dataset_preflight
from packages.ml.m365risk_ml.runtime import ModelRuntime
from packages.ml.m365risk_ml.v2 import V2_COMPONENT_NAMES

from .auth import Principal, bearer, current_principal, require_admin
from .config import get_settings
from .crypto import SecretCipher
from .database import AdminSessionLocal, admin_engine
from .dependencies import get_tenant_db
from .models import (
    AuditEvent,
    ConnectorConnection,
    EmailFeature,
    Feedback,
    ModelVersion,
    RiskScore,
    SecurityAlertObservation,
    SignInObservation,
    SimulationRun,
    SyncJob,
    User,
    UserDailyFeature,
    UserFeatureWindow,
)
from .observability import configure_logging, configure_tracing
from .schemas import (
    ConnectionResponse,
    CursorPage,
    DashboardSummary,
    DatasetPreflightRequest,
    DatasetPreflightResponse,
    FeedbackCreate,
    MailEventPage,
    MailEventResponse,
    ModelResponse,
    RiskCursorPage,
    RiskFactorResponse,
    RiskGraphEdge,
    RiskGraphNode,
    RiskScoreResponse,
    ScannedFeaturePage,
    ScannedFeatureRow,
    SimulationRunCreate,
    SimulationRunPage,
    SimulationRunResponse,
    SimulationStatus,
    SyncJobCursorPage,
    SyncJobResponse,
    TokenRequest,
    TokenResponse,
    UserRiskGraphV2,
    UserSummary,
)

settings = get_settings()
GRAPH_SCOPES = [
    "Mail.ReadBasic.All",
    "User.Read.All",
    "AuditLog.Read.All",
    "IdentityRiskyUser.Read.All",
    "RoleManagement.Read.Directory",
    "SecurityAlert.Read.All",
]
configure_logging()
app = FastAPI(title="M365 User Risk API", version="0.1.0")
configure_tracing(app, settings)
log = structlog.get_logger("m365risk.api")


def encode_cursor(*values: object) -> str:
    payload = json.dumps(values, separators=(",", ":"), default=str).encode()
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode()


def decode_cursor(value: str, expected: int) -> list[str]:
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded.encode()))
        if not isinstance(decoded, list) or len(decoded) != expected:
            raise ValueError("cursor shape")
        return [str(item) for item in decoded]
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid pagination cursor") from exc


def coerce_int(value: object, default: int) -> int:
    if isinstance(value, (int, float, str)):
        try:
            return int(value)
        except ValueError:
            return default
    return default


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3002",
        "http://127.0.0.1:3002",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
REQUESTS = Counter("m365risk_http_requests_total", "HTTP requests", ["method", "path", "status"])
LATENCY = Histogram("m365risk_http_request_seconds", "HTTP request latency", ["path"])


@app.middleware("http")
async def request_context(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id
    started = time.perf_counter()
    response = await call_next(request)
    route_path = str(getattr(request.scope.get("route"), "path", "unmatched"))
    duration = time.perf_counter() - started
    LATENCY.labels(route_path).observe(duration)
    response.headers["X-Request-ID"] = request_id
    REQUESTS.labels(request.method, route_path, response.status_code).inc()
    log.info(
        "http_request",
        method=request.method,
        path=route_path,
        status=response.status_code,
        request_id=request_id,
        duration_ms=round(duration * 1000, 2),
    )
    return response


def error_payload(request: Request, code: str, message: str) -> dict[str, str | None]:
    return {"code": code, "message": message, "request_id": getattr(request.state, "request_id", None)}


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    message = str(exc.detail) if not isinstance(exc.detail, dict) else "Request failed"
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(request, f"http_{exc.status_code}", message),
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, _: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=error_payload(request, "validation_error", "Request validation failed"),
    )


@app.exception_handler(Exception)
async def internal_error(request: Request, _: Exception) -> JSONResponse:
    log.exception(
        "unhandled_request_error",
        path=str(getattr(request.scope.get("route"), "path", "unmatched")),
        request_id=getattr(request.state, "request_id", None),
    )
    return JSONResponse(
        status_code=500,
        content=error_payload(
            request, "internal_error", "An unexpected server error occurred"
        ),
    )


@app.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
async def ready() -> dict[str, str]:
    try:
        async with admin_engine.connect() as connection:
            await connection.execute(text("select 1"))
        if settings.connector_mode == "mock" and settings.app_env != "test":
            async with httpx.AsyncClient(timeout=2) as client:
                response = await client.get(f"{settings.mock_graph_url}/health/live")
                response.raise_for_status()
        if settings.app_env == "production":
            ModelRuntime.load(Path(settings.model_dir), require_approved=True)
    except (OSError, RuntimeError, SQLAlchemyError, ValueError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=503, detail="A required dependency is not ready") from exc
    return {"status": "ready", "connector": settings.connector_mode}


@app.get("/metrics")
async def metrics(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> Response:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Metrics credential required")
    if not hmac.compare_digest(credentials.credentials, settings.metrics_key):
        current_principal(credentials)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/api/v1/auth/mock-token", response_model=TokenResponse)
async def mock_token(payload: TokenRequest) -> TokenResponse:
    if settings.connector_mode != "mock":
        raise HTTPException(status_code=404, detail="Mock login disabled")
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            f"{settings.mock_graph_url}/oauth2/v2.0/token",
            json=payload.model_dump(mode="json"),
            headers={"X-Mock-Admin": settings.mock_admin_secret},
        )
        response.raise_for_status()
        return TokenResponse.model_validate(response.json())


@app.post("/api/v1/tenants/onboarding/start")
async def onboarding_start(principal: Principal = Depends(require_admin)) -> dict[str, str]:
    if settings.connector_mode == "mock":
        return {"mode": "mock", "status": "connected"}
    if not settings.graph_client_id:
        raise HTTPException(status_code=503, detail="Graph client ID is not configured")
    now = int(time.time())
    state = jwt.encode(
        {
            "iss": "m365-risk-api",
            "aud": "m365-risk-admin-consent",
            "sub": principal.subject,
            "tid": str(principal.tenant_id),
            "jti": str(uuid.uuid4()),
            "nonce": str(uuid.uuid4()),
            "iat": now,
            "exp": now + 600,
        },
        settings.token_encryption_key,
        algorithm="HS256",
    )
    query = urlencode(
        {
            "client_id": settings.graph_client_id,
            "redirect_uri": settings.graph_redirect_uri,
            "state": state,
        }
    )
    return {
        "mode": "real",
        "url": f"https://login.microsoftonline.com/organizations/v2.0/adminconsent?{query}",
    }


@app.get("/api/v1/tenants/onboarding/callback")
async def onboarding_callback(
    tenant: uuid.UUID,
    state: str,
    admin_consent: bool = False,
) -> dict[str, object]:
    if settings.connector_mode == "mock":
        raise HTTPException(status_code=404, detail="Real onboarding disabled")
    try:
        claims = jwt.decode(
            state,
            settings.token_encryption_key,
            algorithms=["HS256"],
            audience="m365-risk-admin-consent",
            issuer="m365-risk-api",
            options={
                "require": ["exp", "iat", "iss", "aud", "sub", "tid", "jti", "nonce"]
            },
        )
        if uuid.UUID(str(claims["tid"])) != tenant:
            raise ValueError("Tenant mismatch")
    except (jwt.PyJWTError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired onboarding state") from exc
    if not admin_consent:
        return {"adminConsent": False, "status": "denied"}
    if not settings.graph_client_id or not settings.graph_client_secret:
        raise HTTPException(status_code=503, detail="Graph credentials are not configured")
    async with AdminSessionLocal() as session, session.begin():
        used = await session.scalar(
            select(AuditEvent.id).where(AuditEvent.details["state_jti"].astext == str(claims["jti"]))
        )
        if used:
            raise HTTPException(status_code=409, detail="Onboarding state was already used")
        connection = await session.scalar(
            select(ConnectorConnection).where(ConnectorConnection.tenant_id == tenant).limit(1)
        )
        encrypted = SecretCipher(settings.token_encryption_key).encrypt(
            settings.graph_client_secret, str(tenant)
        )
        if connection:
            connection.client_id = settings.graph_client_id
            connection.encrypted_client_secret = encrypted
            connection.consent_status = "connected"
            connection.scopes = GRAPH_SCOPES
        else:
            session.add(
                ConnectorConnection(
                    tenant_id=tenant,
                    client_id=settings.graph_client_id,
                    encrypted_client_secret=encrypted,
                    consent_status="connected",
                    scopes=GRAPH_SCOPES,
                )
            )
        session.add(
            AuditEvent(
                tenant_id=tenant,
                actor=str(claims["sub"]),
                action="graph.admin_consent.accepted",
                details={"state_jti": str(claims["jti"])},
            )
        )
    return {"adminConsent": True, "status": "accepted"}


@app.get("/api/v1/tenants/connection", response_model=ConnectionResponse)
async def tenant_connection(
    db: AsyncSession = Depends(get_tenant_db),
) -> ConnectionResponse:
    if settings.connector_mode == "mock":
        return ConnectionResponse(
            mode="mock",
            status="connected",
            provider="mock_microsoft_graph",
            scopes=GRAPH_SCOPES,
        )
    connection = await db.scalar(
        select(ConnectorConnection).order_by(desc(ConnectorConnection.updated_at)).limit(1)
    )
    if not connection:
        return ConnectionResponse(
            mode="real",
            status="not_connected",
            provider="microsoft_graph",
            scopes=[],
        )
    return ConnectionResponse(
        mode="real",
        status=connection.consent_status,
        provider=connection.provider,
        scopes=connection.scopes,
        updated_at=connection.updated_at,
    )


@app.post("/api/v1/sync", response_model=SyncJobResponse)
async def start_sync(
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_tenant_db),
) -> SyncJob:
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency-Key required")
    existing = await db.scalar(
        select(SyncJob)
        .where(SyncJob.checkpoint["idempotency_key"].astext == idempotency_key)
        .order_by(desc(SyncJob.created_at))
        .limit(1)
    )
    if existing:
        return existing
    job = SyncJob(tenant_id=principal.tenant_id, checkpoint={"idempotency_key": idempotency_key})
    db.add(job)
    await db.flush()
    await db.refresh(job)
    return job


@app.get("/api/v1/sync/jobs", response_model=SyncJobCursorPage)
async def sync_jobs(
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_tenant_db),
) -> SyncJobCursorPage:
    query = select(SyncJob).order_by(desc(SyncJob.created_at), desc(SyncJob.id))
    if cursor:
        created_raw, id_raw = decode_cursor(cursor, 2)
        try:
            created = datetime.fromisoformat(created_raw)
            job_id = uuid.UUID(id_raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid pagination cursor") from exc
        query = query.where(
            or_(
                SyncJob.created_at < created,
                and_(SyncJob.created_at == created, SyncJob.id < job_id),
            )
        )
    rows = list(await db.scalars(query.limit(limit + 1)))
    next_cursor = (
        encode_cursor(rows[limit - 1].created_at, rows[limit - 1].id)
        if len(rows) > limit
        else None
    )
    return SyncJobCursorPage(items=rows[:limit], next_cursor=next_cursor)


async def latest_scores(db: AsyncSession) -> dict[str, RiskScore]:
    result = await db.scalars(
        select(RiskScore)
        .distinct(RiskScore.user_id)
        .order_by(RiskScore.user_id, desc(RiskScore.calculated_at))
    )
    return {score.user_id: score for score in result}


@app.get("/api/v1/users", response_model=CursorPage)
async def users(
    level: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_tenant_db),
) -> CursorPage:
    ranked = (
        select(
            RiskScore.tenant_id.label("tenant_id"),
            RiskScore.user_id.label("user_id"),
            RiskScore.score.label("score"),
            RiskScore.level.label("level"),
            RiskScore.calculated_at.label("calculated_at"),
            func.row_number()
            .over(
                partition_by=(RiskScore.tenant_id, RiskScore.user_id),
                order_by=RiskScore.calculated_at.desc(),
            )
            .label("position"),
        )
        .subquery()
    )
    query = (
        select(User, ranked.c.score, ranked.c.level, ranked.c.calculated_at)
        .outerjoin(
            ranked,
            and_(
                ranked.c.tenant_id == User.tenant_id,
                ranked.c.user_id == User.id,
                ranked.c.position == 1,
            ),
        )
        .order_by(User.id)
        .limit(limit + 1)
    )
    if cursor:
        (user_cursor,) = decode_cursor(cursor, 1)
        query = query.where(User.id > user_cursor)
    if level:
        if level not in {"critical", "high", "medium", "low"}:
            raise HTTPException(status_code=422, detail="Unknown risk level")
        query = query.where(func.coalesce(ranked.c.level, "low") == level)
    all_users = list((await db.execute(query)).all())
    items = [
        UserSummary(
            id=user.id,
            display_name=user.display_name,
            is_admin=user.is_admin,
            is_mfa_registered=user.is_mfa_registered,
            is_mfa_capable=user.is_mfa_capable,
            entra_risk_level=user.entra_risk_level,
            score=score or 0,
            level=risk_level or "low",
            calculated_at=calculated_at,
        )
        for user, score, risk_level, calculated_at in all_users[:limit]
    ]
    next_cursor = encode_cursor(all_users[limit - 1][0].id) if len(all_users) > limit else None
    return CursorPage(items=items, next_cursor=next_cursor)


def to_risk(score: RiskScore) -> RiskScoreResponse:
    actions = ["Review recent sign-in and mailbox activity"]
    factor_names = " ".join(factor.name.lower() for factor in score.factors)
    if "mfa" in factor_names:
        actions.append("Require MFA registration")
    if "email" in factor_names or "communication" in factor_names:
        actions.append("Verify recent external communications")
    if "entra" in factor_names:
        actions.append("Review Microsoft Entra risky-user evidence")
    return RiskScoreResponse(
        id=score.id,
        user_id=score.user_id,
        score=score.score,
        level=score.level,
        calculated_at=score.calculated_at,
        model_version=score.model_version,
        factors=[RiskFactorResponse(name=f.name, contribution=f.contribution) for f in score.factors],
        recommended_actions=actions,
    )


@app.get("/api/v1/users/{user_id}/risk", response_model=RiskScoreResponse)
async def user_risk(user_id: str, db: AsyncSession = Depends(get_tenant_db)) -> RiskScoreResponse:
    score = await db.scalar(
        select(RiskScore)
        .options(selectinload(RiskScore.factors))
        .where(RiskScore.user_id == user_id)
        .order_by(desc(RiskScore.calculated_at))
        .limit(1)
    )
    if not score:
        raise HTTPException(status_code=404, detail="Risk score not found")
    return to_risk(score)


@app.get("/api/v1/users/{user_id}/risk-graph", response_model=UserRiskGraphV2)
async def user_risk_graph(
    user_id: str,
    db: AsyncSession = Depends(get_tenant_db),
) -> UserRiskGraphV2:
    # The tenant dependency has already established RLS, so the user ID cannot cross tenants.
    user = await db.scalar(select(User).where(User.id == user_id).limit(1))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    window = await db.scalar(
        select(UserFeatureWindow)
        .where(UserFeatureWindow.user_id == user_id)
        .order_by(desc(UserFeatureWindow.window_end))
        .limit(1)
    )
    if not window:
        raise HTTPException(status_code=404, detail="V2 feature window not found")

    evidence = window.evidence or {}

    def evidence_ids(name: str) -> list[str]:
        values = evidence.get(name, [])
        return [str(value) for value in values][:50] if isinstance(values, list) else []

    mail_ids = evidence_ids("email_observation_ids")
    sign_in_ids = evidence_ids("sign_in_observation_ids")
    alert_ids = evidence_ids("security_alert_ids")
    mails = (
        list(await db.scalars(select(EmailFeature).where(EmailFeature.id.in_(mail_ids))))
        if mail_ids
        else []
    )
    sign_ins = (
        list(
            await db.scalars(
                select(SignInObservation).where(SignInObservation.id.in_(sign_in_ids))
            )
        )
        if sign_in_ids
        else []
    )
    alerts = (
        list(
            await db.scalars(
                select(SecurityAlertObservation).where(
                    SecurityAlertObservation.id.in_(alert_ids)
                )
            )
        )
        if alert_ids
        else []
    )

    employee_node = f"employee:{user.id}"
    nodes = [
        RiskGraphNode(
            id=employee_node,
            kind="employee",
            label=user.display_name,
            metadata={"user_id": user.id},
        )
    ]
    edges: list[RiskGraphEdge] = []
    observation_feature_edges: list[tuple[str, str]] = []
    for mail in mails:
        node_id = f"mail:{mail.id}"
        nodes.append(
            RiskGraphNode(
                id=node_id,
                kind="observation",
                label="Mail header observation",
                value=round(float(mail.risk_probability), 4),
                observed_at=mail.received_at,
                metadata={"source": "Microsoft Graph mail headers"},
            )
        )
        edges.append(RiskGraphEdge(source=employee_node, target=node_id, relation="HAS_OBSERVATION"))
        observation_feature_edges.append((node_id, "feature:email_top3"))
    for sign_in in sign_ins:
        node_id = f"signin:{sign_in.id}"
        nodes.append(
            RiskGraphNode(
                id=node_id,
                kind="observation",
                label="Sign-in observation",
                value="success" if sign_in.successful else "failed",
                observed_at=sign_in.created_at,
                metadata={
                    "country": sign_in.country or "unknown",
                    "managed": sign_in.is_managed if sign_in.is_managed is not None else "unknown",
                },
            )
        )
        edges.append(RiskGraphEdge(source=employee_node, target=node_id, relation="HAS_OBSERVATION"))
        for name in ("time", "location", "network", "device", "auth", "app"):
            observation_feature_edges.append((node_id, f"feature:identity_{name}"))
    for alert in alerts:
        node_id = f"alert:{alert.id}"
        nodes.append(
            RiskGraphNode(
                id=node_id,
                kind="observation",
                label="Security alert observation",
                value=alert.severity,
                observed_at=alert.created_at,
                metadata={"source": alert.source, "category": alert.category or "unknown"},
            )
        )
        edges.append(RiskGraphEdge(source=employee_node, target=node_id, relation="HAS_OBSERVATION"))
        observation_feature_edges.append((node_id, "feature:endpoint_alert"))

    canonical_features = dict(window.features or {})
    canonical_features.update(
        {
            "mfa_posture": window.components.get("mfa_exposure"),
            "privilege_role": window.components.get("privilege_exposure"),
            "endpoint_alert": window.components.get("endpoint_threat"),
        }
    )
    feature_to_component = {
        "email_top3": "email_threat",
        "identity_time": "identity_compromise",
        "identity_location": "identity_compromise",
        "identity_network": "identity_compromise",
        "identity_device": "identity_compromise",
        "identity_auth": "identity_compromise",
        "identity_app": "identity_compromise",
        "mfa_posture": "mfa_exposure",
        "privilege_role": "privilege_exposure",
        "endpoint_alert": "endpoint_threat",
    }
    for name, value in canonical_features.items():
        component_name = feature_to_component.get(name)
        if not component_name:
            continue
        status = window.availability.get(component_name, "unavailable")
        nodes.append(
            RiskGraphNode(
                id=f"feature:{name}",
                kind="feature",
                label=name.replace("_", " ").title(),
                status=status,
                value=value,
            )
        )
        edges.append(
            RiskGraphEdge(
                source=f"feature:{name}",
                target=f"component:{component_name}",
                relation="CONTRIBUTES_TO",
            )
        )
    feature_ids = {node.id for node in nodes if node.kind == "feature"}
    edges.extend(
        RiskGraphEdge(source=source, target=target, relation="DERIVES")
        for source, target in observation_feature_edges
        if target in feature_ids
    )
    for name, value in window.components.items():
        nodes.append(
            RiskGraphNode(
                id=f"component:{name}",
                kind="component",
                label=name.replace("_", " ").title(),
                status=window.availability.get(name, "unavailable"),
                value=value,
            )
        )
    return UserRiskGraphV2(
        user_id=user_id,
        feature_version=window.feature_version,
        model_version=window.model_version,
        calculated_at=window.calculated_at,
        score=window.score,
        level=window.level,
        components=window.components,
        coverage=window.availability,
        nodes=nodes,
        edges=edges,
    )


@app.get("/api/v1/users/{user_id}/risk-history", response_model=RiskCursorPage)
async def risk_history(
    user_id: str,
    cursor: str | None = None,
    limit: int = Query(default=100, ge=1, le=365),
    db: AsyncSession = Depends(get_tenant_db),
) -> RiskCursorPage:
    query = (
        select(RiskScore)
        .options(selectinload(RiskScore.factors))
        .where(RiskScore.user_id == user_id)
        .order_by(desc(RiskScore.calculated_at), desc(RiskScore.id))
    )
    if cursor:
        calculated_raw, id_raw = decode_cursor(cursor, 2)
        try:
            calculated = datetime.fromisoformat(calculated_raw)
            risk_id = uuid.UUID(id_raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid pagination cursor") from exc
        query = query.where(
            or_(
                RiskScore.calculated_at < calculated,
                and_(RiskScore.calculated_at == calculated, RiskScore.id < risk_id),
            )
        )
    rows = list(await db.scalars(query.limit(limit + 1)))
    next_cursor = (
        encode_cursor(rows[limit - 1].calculated_at, rows[limit - 1].id)
        if len(rows) > limit
        else None
    )
    return RiskCursorPage(
        items=[to_risk(score) for score in rows[:limit]], next_cursor=next_cursor
    )


@app.get("/api/v1/risks", response_model=RiskCursorPage)
async def risks(
    cursor: str | None = None,
    limit: int = Query(default=100, ge=1, le=100),
    db: AsyncSession = Depends(get_tenant_db),
) -> RiskCursorPage:
    query = (
        select(RiskScore)
        .options(selectinload(RiskScore.factors))
        .order_by(desc(RiskScore.calculated_at), desc(RiskScore.id))
    )
    if cursor:
        calculated_raw, id_raw = decode_cursor(cursor, 2)
        try:
            calculated = datetime.fromisoformat(calculated_raw)
            risk_id = uuid.UUID(id_raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid pagination cursor") from exc
        query = query.where(
            or_(
                RiskScore.calculated_at < calculated,
                and_(RiskScore.calculated_at == calculated, RiskScore.id < risk_id),
            )
        )
    rows = list(await db.scalars(query.limit(limit + 1)))
    next_cursor = (
        encode_cursor(rows[limit - 1].calculated_at, rows[limit - 1].id)
        if len(rows) > limit
        else None
    )
    return RiskCursorPage(
        items=[to_risk(score) for score in rows[:limit]], next_cursor=next_cursor
    )


@app.post("/api/v1/risks/{risk_id}/feedback", status_code=201)
async def create_feedback(
    risk_id: uuid.UUID,
    payload: FeedbackCreate,
    principal: Principal = Depends(current_principal),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict[str, str]:
    if not await db.scalar(select(RiskScore.id).where(RiskScore.id == risk_id)):
        raise HTTPException(status_code=404, detail="Risk score not found")
    db.add(
        Feedback(
            tenant_id=principal.tenant_id,
            risk_id=risk_id,
            verdict=payload.verdict,
            comment=payload.comment,
            actor=principal.subject,
        )
    )
    db.add(
        AuditEvent(
            tenant_id=principal.tenant_id,
            actor=principal.subject,
            action="risk.feedback.created",
            details={"risk_id": str(risk_id), "verdict": payload.verdict},
        )
    )
    return {"status": "recorded"}


@app.get("/api/v1/dashboard/summary", response_model=DashboardSummary)
async def dashboard_summary(db: AsyncSession = Depends(get_tenant_db)) -> DashboardSummary:
    count = int(await db.scalar(select(func.count()).select_from(User)) or 0)
    scores = list((await latest_scores(db)).values())
    levels = {level: sum(item.level == level for item in scores) for level in ("critical", "high", "medium", "low")}
    average = sum(item.score for item in scores) / len(scores) if scores else 0.0
    last_sync = await db.scalar(select(func.max(SyncJob.completed_at)))
    return DashboardSummary(users=count, average_score=round(average, 1), last_sync_at=last_sync, **levels)


@app.get("/api/v1/mail/events", response_model=MailEventPage)
async def recent_mail_events(
    limit: int = Query(default=24, ge=1, le=50),
    db: AsyncSession = Depends(get_tenant_db),
) -> MailEventPage:
    """Return recent content-free mail telemetry for the verified tenant."""
    rows = list(
        await db.scalars(
            select(EmailFeature)
            .order_by(desc(EmailFeature.received_at), desc(EmailFeature.id))
            .limit(limit)
        )
    )
    items: list[MailEventResponse] = []
    for row in rows:
        features = row.features or {}
        auth = features.get("authentication_results", {})
        importance = features.get("importance", "normal")
        if importance not in {"low", "normal", "high"}:
            importance = "normal"
        items.append(
            MailEventResponse(
                id=row.id,
                user_id=row.user_id,
                received_at=row.received_at,
                risk_probability=float(row.risk_probability),
                external_sender=bool(features.get("external_sender", False)),
                recipient_count=max(1, coerce_int(features.get("recipient_count"), 1)),
                has_attachments=bool(features.get("has_attachments", False)),
                importance=importance,
                authentication_results={
                    str(key).lower(): str(value).lower()
                    for key, value in auth.items()
                }
                if isinstance(auth, dict)
                else {},
                reply_to_domain_mismatch=bool(
                    features.get("reply_to_domain_mismatch", False)
                ),
                from_sender_mismatch=bool(
                    features.get("from_sender_mismatch", False)
                ),
                received_hops=max(0, coerce_int(features.get("received_hops"), 0)),
                sender_domain_hash=str(features.get("sender_domain_hash", "unknown")),
            )
        )
    return MailEventPage(items=items)


@app.post("/api/v1/datasets/preflight", response_model=DatasetPreflightResponse)
async def preflight_dataset(
    payload: DatasetPreflightRequest,
    _: Principal = Depends(current_principal),
) -> DatasetPreflightResponse:
    report = dataset_preflight(
        payload.columns,
        dataset_kind=payload.dataset_kind,
        source_category=payload.source_category,
        labelled=payload.labelled,
    )
    return DatasetPreflightResponse(**report.__dict__)


SCANNED_FEATURE_NAMES = (
    "email_top3",
    "identity_time",
    "identity_location",
    "identity_network",
    "identity_device",
    "identity_auth",
    "identity_app",
)


def scanned_feature_row(window: UserFeatureWindow, tenant_id: uuid.UUID) -> ScannedFeatureRow:
    """Whitelist derived values; never export raw evidence or Graph identifiers."""
    secret = settings.pseudonymization_key.encode()

    def digest(value: str) -> str:
        return hmac.new(secret, value.encode(), hashlib.sha256).hexdigest()

    subject_key = digest(f"scanned-subject-v1:{tenant_id}:{window.user_id}")
    sample_id = digest(f"scanned-window-v1:{tenant_id}:{window.user_id}:{window.window_end.isoformat()}")
    components = window.components or {}
    features = window.features or {}
    availability = window.availability or {}
    return ScannedFeatureRow(
        sample_id=sample_id,
        subject_key=subject_key,
        window_end=window.window_end,
        feature_version=window.feature_version,
        model_version=window.model_version,
        components={name: components.get(name) for name in V2_COMPONENT_NAMES},
        features={name: features.get(name) for name in SCANNED_FEATURE_NAMES},
        availability={
            name: availability.get(name, "unavailable") for name in V2_COMPONENT_NAMES
        },
    )


@app.get("/api/v1/datasets/scanned", response_model=ScannedFeaturePage)
async def scanned_features(
    cursor: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_tenant_db),
) -> ScannedFeaturePage:
    """Page through stored V2 windows for a private, label-free training export."""
    query = select(UserFeatureWindow).order_by(
        UserFeatureWindow.user_id, UserFeatureWindow.window_end
    )
    if cursor:
        user_id, window_raw = decode_cursor(cursor, 2)
        try:
            window_end = datetime.fromisoformat(window_raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid pagination cursor") from exc
        query = query.where(
            or_(
                UserFeatureWindow.user_id > user_id,
                and_(
                    UserFeatureWindow.user_id == user_id,
                    UserFeatureWindow.window_end > window_end,
                ),
            )
        )
    windows = list(await db.scalars(query.limit(limit + 1)))
    next_cursor = (
        encode_cursor(windows[limit - 1].user_id, windows[limit - 1].window_end)
        if len(windows) > limit
        else None
    )
    return ScannedFeaturePage(
        items=[scanned_feature_row(window, principal.tenant_id) for window in windows[:limit]],
        next_cursor=next_cursor,
        source_category="generated" if settings.connector_mode == "mock" else "real_unlabelled",
    )


@app.get("/api/v1/datasets/scanned/subjects/{user_id}", response_model=ScannedFeatureRow)
async def scanned_subject_sample(
    user_id: str,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_tenant_db),
) -> ScannedFeatureRow:
    """Resolve a known local user to a sample ID for private analyst labelling."""
    window = await db.scalar(
        select(UserFeatureWindow)
        .where(UserFeatureWindow.user_id == user_id)
        .order_by(desc(UserFeatureWindow.window_end))
        .limit(1)
    )
    if not window:
        raise HTTPException(status_code=404, detail="Feature window not found")
    return scanned_feature_row(window, principal.tenant_id)


@app.get("/api/v1/models/current", response_model=ModelResponse)
async def current_model(db: AsyncSession = Depends(get_tenant_db)) -> ModelResponse:
    model = await db.scalar(select(ModelVersion).order_by(desc(ModelVersion.created_at)).limit(1))
    if model:
        return ModelResponse(version=model.version, approved=model.approved, feature_version=model.feature_version, metrics=model.metrics)
    manifest = Path(settings.model_dir) / "manifest.json"
    if manifest.exists():
        data = json.loads(manifest.read_text())
        return ModelResponse(version=data["version"], approved=data["approved"], feature_version=data["feature_version"], metrics=data.get("metrics", {}))
    raise HTTPException(status_code=404, detail="No model available")


async def simulator_request(
    method: str, path: str, params: dict[str, str] | None = None
) -> dict[str, object]:
    if settings.connector_mode != "mock":
        raise HTTPException(status_code=404, detail="Simulator disabled")
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.request(
            method,
            f"{settings.mock_graph_url}/__admin/{path}",
            params=params,
            headers={"X-Mock-Admin": settings.mock_admin_secret},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Simulator response must be a JSON object")
        return payload


SIMULATION_EXPECTATIONS = {
    "credential-phishing": "High-risk mail headers",
    "domain-spoofing": "Sender-domain impersonation",
    "executive-impersonation": "Executive sender mismatch",
    "account-takeover": "Identity anomaly or Defender alert",
    "mfa-removal": "MFA posture degradation",
    "entra-escalation": "Entra risky-user escalation",
}


async def simulation_run_payload(
    run: SimulationRun,
    db: AsyncSession,
) -> dict[str, object]:
    user = await db.scalar(select(User).where(User.id == run.target_user_id).limit(1))
    if not user:
        raise HTTPException(status_code=404, detail="Simulation target no longer exists")
    job = await db.scalar(
        select(SyncJob)
        .where(SyncJob.checkpoint["simulation_run_id"].astext == str(run.id))
        .order_by(desc(SyncJob.created_at))
        .limit(1)
    )
    window = await db.scalar(
        select(UserFeatureWindow)
        .where(UserFeatureWindow.user_id == run.target_user_id)
        .order_by(desc(UserFeatureWindow.calculated_at))
        .limit(1)
    )
    fresh_window = bool(window and window.calculated_at >= run.created_at)
    mail_count = int(
        await db.scalar(
            select(func.count(EmailFeature.id)).where(
                EmailFeature.user_id == run.target_user_id,
                EmailFeature.received_at >= run.created_at,
            )
        )
        or 0
    )
    high_risk_mail = int(
        await db.scalar(
            select(func.count(EmailFeature.id)).where(
                EmailFeature.user_id == run.target_user_id,
                EmailFeature.received_at >= run.created_at,
                EmailFeature.risk_probability >= 0.70,
            )
        )
        or 0
    )
    sign_in_count = int(
        await db.scalar(
            select(func.count(SignInObservation.id)).where(
                SignInObservation.user_id == run.target_user_id,
                SignInObservation.created_at >= run.created_at,
            )
        )
        or 0
    )
    alert_count = int(
        await db.scalar(
            select(func.count(SecurityAlertObservation.id)).where(
                SecurityAlertObservation.user_id == run.target_user_id,
                SecurityAlertObservation.created_at >= run.created_at,
            )
        )
        or 0
    )
    components = dict(window.components or {}) if fresh_window and window else {}

    def component_value(name: str) -> float:
        value = components.get(name)
        if isinstance(value, (int, float, str)):
            try:
                return float(value)
            except ValueError:
                return 0.0
        return 0.0

    if run.scenario in {
        "credential-phishing",
        "domain-spoofing",
        "executive-impersonation",
    }:
        detected = high_risk_mail > 0 and component_value("email_threat") >= 0.70
    elif run.scenario == "account-takeover":
        detected = alert_count > 0 or component_value("identity_compromise") >= 0.65
    elif run.scenario == "mfa-removal":
        detected = not user.is_mfa_registered and component_value("mfa_exposure") >= 0.80
    else:
        detected = user.entra_risk_level == "high" and component_value("identity_compromise") >= 0.65

    # A scheduler job can ingest the evidence before the dedicated run job is
    # claimed. A fresh feature window is therefore also proof that connector
    # synchronization completed for this target.
    sync_done = bool((job and job.status == "completed") or fresh_window)
    sync_failed = bool(job and job.status == "dead")
    if run.status == "reset":
        status = "reset"
    elif detected:
        status = "detected"
    elif sync_done and fresh_window:
        status = "missed"
    elif sync_done:
        status = "evaluating"
    else:
        status = "syncing"

    now = datetime.now(UTC)
    terminal = status in {"detected", "missed", "reset"}
    fresh_score = window.score if fresh_window and window else run.current_score
    if run.status != status or run.detected != detected or run.current_score != fresh_score:
        run.status = status
        run.detected = detected
        run.current_score = fresh_score
        run.updated_at = now
        if terminal and run.completed_at is None:
            run.completed_at = now

    score_delta = (
        run.current_score - run.baseline_score
        if run.current_score is not None and run.baseline_score is not None
        else None
    )

    def stage_status(done: bool, active: bool = False, failed: bool = False) -> str:
        if failed:
            return "failed"
        if done:
            return "done"
        if active:
            return "active"
        return "pending"

    stages = [
        {"key": "injected", "label": "Scenario injection", "status": "done", "detail": f"Targeted {run.target_user_id}"},
        {"key": "connector", "label": "Mock Graph", "status": "done", "detail": "Evidence exposed through Graph-compatible endpoints"},
        {
            "key": "synchronized",
            "label": "Connector sync",
            "status": stage_status(sync_done, bool(job and job.status in {"queued", "running", "retrying"}), sync_failed),
            "detail": f"Sync job: {job.status if job else 'queued'}",
        },
        {
            "key": "features",
            "label": "Feature extraction",
            "status": stage_status(fresh_window, sync_done and not fresh_window),
            "detail": f"{mail_count} mail, {sign_in_count} sign-in, {alert_count} alert observations",
        },
        {
            "key": "scored",
            "label": "Risk scoring",
            "status": stage_status(fresh_window, sync_done and not fresh_window),
            "detail": f"Canonical score: {window.score if fresh_window and window and window.score is not None else 'pending'}",
        },
        {
            "key": "alert",
            "label": "SOC detection",
            "status": stage_status(detected, failed=status == "missed"),
            "detail": "Expected signal detected" if detected else ("Expected signal was not detected" if status == "missed" else "Waiting for scoring evidence"),
        },
    ]
    return {
        "id": run.id,
        "scenario": run.scenario,
        "target_user_id": run.target_user_id,
        "target_display_name": user.display_name,
        "status": status,
        "detected": detected,
        "expected_signal": SIMULATION_EXPECTATIONS[run.scenario],
        "baseline_score": run.baseline_score,
        "current_score": run.current_score,
        "score_delta": score_delta,
        "components": components,
        "measurements": {
            "mail_observations": mail_count,
            "high_risk_mail": high_risk_mail,
            "sign_in_observations": sign_in_count,
            "security_alerts": alert_count,
            "mfa_registered": user.is_mfa_registered,
            "entra_risk_level": user.entra_risk_level,
            "sync_status": job.status if job else "queued",
        },
        "stages": stages,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "completed_at": run.completed_at,
    }


@app.post("/api/v1/simulation-runs", response_model=SimulationRunResponse)
async def create_simulation_run(
    payload: SimulationRunCreate,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict[str, object]:
    if settings.connector_mode != "mock":
        raise HTTPException(status_code=404, detail="Simulator disabled")
    user = await db.scalar(select(User).where(User.id == payload.target_user_id).limit(1))
    if not user:
        raise HTTPException(status_code=404, detail="Target user not found")
    baseline = await db.scalar(
        select(UserFeatureWindow)
        .where(UserFeatureWindow.user_id == payload.target_user_id)
        .order_by(desc(UserFeatureWindow.calculated_at))
        .limit(1)
    )
    run = SimulationRun(
        tenant_id=principal.tenant_id,
        target_user_id=payload.target_user_id,
        scenario=payload.scenario,
        status="queued",
        baseline_score=baseline.score if baseline else None,
        current_score=baseline.score if baseline else None,
        details={"source": "separate-simulator"},
    )
    db.add(run)
    await db.flush()
    idempotency_key = str(run.id)
    await simulator_request(
        "POST",
        f"scenarios/{payload.scenario}/start",
        {
            "idempotency_key": idempotency_key,
            "tenant_id": str(principal.tenant_id),
            "target_user_id": payload.target_user_id,
            "simulation_run_id": str(run.id),
        },
    )
    previous = await db.scalar(
        select(SyncJob)
        .where(SyncJob.status == "completed")
        .order_by(desc(SyncJob.created_at))
        .limit(1)
    )
    checkpoint = {
        key: value
        for key, value in dict(previous.checkpoint or {}).items()
        if key.startswith("user-")
    } if previous else {}
    checkpoint["simulation_run_id"] = str(run.id)
    db.add(SyncJob(tenant_id=principal.tenant_id, checkpoint=checkpoint))
    run.status = "syncing"
    run.updated_at = datetime.now(UTC)
    await db.flush()
    return await simulation_run_payload(run, db)


@app.get("/api/v1/simulation-runs", response_model=SimulationRunPage)
async def list_simulation_runs(
    limit: int = Query(default=20, ge=1, le=100),
    _: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict[str, object]:
    runs = list(
        await db.scalars(
            select(SimulationRun).order_by(desc(SimulationRun.created_at)).limit(limit)
        )
    )
    return {"items": [await simulation_run_payload(run, db) for run in runs]}


@app.get("/api/v1/simulation-runs/{run_id}", response_model=SimulationRunResponse)
async def get_simulation_run(
    run_id: uuid.UUID,
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict[str, object]:
    run = await db.get(SimulationRun, (principal.tenant_id, run_id))
    if not run:
        raise HTTPException(status_code=404, detail="Simulation run not found")
    return await simulation_run_payload(run, db)


@app.get("/api/v1/simulations/status", response_model=SimulationStatus)
async def simulation_status(
    principal: Principal = Depends(current_principal),
) -> dict[str, object]:
    return await simulator_request(
        "GET", "status", {"tenant_id": str(principal.tenant_id)}
    )


@app.post("/api/v1/simulations/scenarios/{scenario}/start", response_model=SimulationStatus)
async def simulation_start(
    scenario: str,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict[str, object]:
    allowed = {"normal", "credential-phishing", "domain-spoofing", "executive-impersonation", "account-takeover", "mfa-removal", "entra-escalation", "throttling", "recovery"}
    if scenario not in allowed:
        raise HTTPException(status_code=422, detail="Unknown scenario")
    result = await simulator_request(
        "POST",
        f"scenarios/{scenario}/start",
        {"idempotency_key": idempotency_key, "tenant_id": str(principal.tenant_id)},
    )
    # Scenario starts must not depend on the periodic scheduler: enqueue a delta
    # sync immediately so the dashboard can meet its ten-second freshness SLO.
    existing = await db.scalar(
        select(SyncJob.id)
        .where(SyncJob.checkpoint["scenario_idempotency_key"].astext == idempotency_key)
        .limit(1)
    )
    if not existing:
        previous = await db.scalar(
            select(SyncJob)
            .where(SyncJob.status == "completed")
            .order_by(desc(SyncJob.created_at))
            .limit(1)
        )
        checkpoint = {
            key: value
            for key, value in dict(previous.checkpoint or {}).items()
            if key.startswith("user-")
        } if previous else {}
        checkpoint["scenario_idempotency_key"] = idempotency_key
        db.add(SyncJob(tenant_id=principal.tenant_id, checkpoint=checkpoint))
    return result


@app.post("/api/v1/simulations/faults/{fault}/start")
async def simulation_fault_start(
    fault: str,
    principal: Principal = Depends(require_admin),
) -> dict[str, object]:
    allowed = {"expired-delta", "revoked-consent", "partial-failure", "missing-p2", "unavailable-mailbox"}
    if fault not in allowed:
        raise HTTPException(status_code=422, detail="Unknown simulator fault")
    return await simulator_request(
        "POST", f"faults/{fault}/start", {"tenant_id": str(principal.tenant_id)}
    )


@app.post("/api/v1/simulations/stop", response_model=SimulationStatus)
async def simulation_stop(
    principal: Principal = Depends(require_admin),
) -> dict[str, object]:
    return await simulator_request(
        "POST", "stop", {"tenant_id": str(principal.tenant_id)}
    )


@app.post("/api/v1/simulations/reset", response_model=SimulationStatus)
async def simulation_reset(
    principal: Principal = Depends(require_admin),
    db: AsyncSession = Depends(get_tenant_db),
) -> dict[str, object]:
    result = await simulator_request(
        "POST", "reset", {"tenant_id": str(principal.tenant_id)}
    )
    # Serialize with the worker so reset is deterministic even when a sync is active.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:tenant, 0))"),
        {"tenant": str(principal.tenant_id)},
    )
    await db.execute(delete(EmailFeature))
    await db.execute(delete(SignInObservation))
    await db.execute(delete(SecurityAlertObservation))
    await db.execute(delete(UserDailyFeature))
    await db.execute(delete(UserFeatureWindow))
    await db.execute(delete(RiskScore))
    await db.execute(delete(SyncJob))
    await db.execute(
        update(SimulationRun)
        .where(SimulationRun.status.notin_(["detected", "missed", "reset"]))
        .values(
            status="reset",
            detected=False,
            updated_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
        )
    )
    db.add(SyncJob(tenant_id=principal.tenant_id, checkpoint={}))
    db.add(
        AuditEvent(
            tenant_id=principal.tenant_id,
            actor=principal.subject,
            action="simulation.reset",
            details={"scope": "current_tenant"},
        )
    )
    return result
