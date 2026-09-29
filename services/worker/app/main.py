from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import statistics
import uuid
from datetime import UTC, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path

import httpx
import structlog
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from packages.ml.m365risk_ml.features import graph_message_features
from packages.ml.m365risk_ml.runtime import ModelRuntime
from packages.ml.m365risk_ml.scoring import hybrid_user_score
from packages.ml.m365risk_ml.v2 import (
    auth_integrity,
    endpoint_threat,
    identity_compromise,
    local_identity_anomaly,
    mfa_exposure,
    privilege_exposure,
    provider_identity_risk,
    score_components,
    sender_context,
    sign_in_window_signals,
    top_k_mean,
)
from services.api.app.config import get_settings
from services.api.app.connectors import (
    GraphConnector,
    GraphDeltaExpired,
    GraphThrottled,
    connector_for,
)
from services.api.app.crypto import SecretCipher
from services.api.app.database import AdminSessionLocal, tenant_session
from services.api.app.models import (
    ConnectorConnection,
    EmailFeature,
    RiskFactor,
    RiskScore,
    SecurityAlertObservation,
    SignInObservation,
    SyncJob,
    Tenant,
    User,
    UserDailyFeature,
    UserFeatureWindow,
)
from services.api.app.observability import (
    configure_logging,
    configure_worker_tracing,
    redacted_tenant,
)
from services.api.app.schemas import (
    EmailMetadataV1,
    SecurityAlertObservationV1,
    SignInObservationV1,
)

settings = get_settings()
configure_logging()
log = structlog.get_logger("m365risk.worker")
tracer = configure_worker_tracing(settings)


def tenant_pseudonym_key(tenant_id: uuid.UUID) -> str:
    return hmac.new(
        settings.pseudonymization_key.encode(),
        f"pseudonym-v1:{tenant_id}".encode(),
        hashlib.sha256,
    ).hexdigest()


def pseudonym(key: str, namespace: str, value: object) -> str:
    return hmac.new(
        key.encode(), f"{namespace}:{value}".encode(), hashlib.sha256
    ).hexdigest()


def graph_datetime(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def network_bucket(value: object) -> str | None:
    """Return a coarse network prefix; the caller hashes it before persistence."""
    try:
        address = ipaddress.ip_address(str(value))
    except ValueError:
        return None
    prefix = 24 if address.version == 4 else 48
    return str(ipaddress.ip_network(f"{address}/{prefix}", strict=False))


def alert_user_ids(alert: dict[str, object]) -> set[str]:
    users = alert.get("userStates") or []
    if not isinstance(users, list):
        return set()
    return {
        str(item.get("userId"))
        for item in users
        if isinstance(item, dict) and item.get("userId")
    }


@lru_cache(maxsize=1)
def model_runtime() -> ModelRuntime:
    return ModelRuntime.load(
        Path(settings.model_dir), require_approved=settings.app_env == "production"
    )


async def claim_job() -> tuple[uuid.UUID, uuid.UUID, dict[str, object]] | None:
    async with AdminSessionLocal() as session, session.begin():
        row = (
            await session.execute(
                text(
                    """
                    SELECT tenant_id, id, checkpoint FROM sync_jobs
                    WHERE status IN ('queued', 'retrying')
                      AND next_attempt_at <= now()
                      AND NOT EXISTS (
                        SELECT 1 FROM sync_jobs running
                        WHERE running.tenant_id = sync_jobs.tenant_id
                          AND running.status = 'running'
                      )
                    ORDER BY created_at
                    FOR UPDATE SKIP LOCKED LIMIT 1
                    """
                )
            )
        ).first()
        if not row:
            return None
        await session.execute(
            text("UPDATE sync_jobs SET status='running', started_at=now(), attempt=attempt+1 WHERE tenant_id=:tenant AND id=:id"),
            {"tenant": row.tenant_id, "id": row.id},
        )
        return row.tenant_id, row.id, dict(row.checkpoint or {})


async def complete_job(tenant_id: uuid.UUID, job_id: uuid.UUID, checkpoint: dict[str, object], error: str | None = None) -> None:
    async with AdminSessionLocal() as session, session.begin():
        await session.execute(
            text(
                """UPDATE sync_jobs
                   SET status = CASE WHEN :has_error AND attempt < 5 THEN 'retrying'
                                     WHEN :has_error THEN 'dead' ELSE 'completed' END,
                       completed_at = CASE WHEN :has_error AND attempt < 5 THEN NULL ELSE now() END,
                       started_at = CASE WHEN :has_error AND attempt < 5 THEN NULL ELSE started_at END,
                       next_attempt_at = CASE
                         WHEN :has_error AND attempt < 5
                           THEN now() + ((LEAST(60, POWER(2, attempt)))::text || ' seconds')::interval
                         ELSE now()
                       END,
                       checkpoint=CAST(:checkpoint AS jsonb), error=:error
                   WHERE tenant_id=:tenant AND id=:id"""
            ),
            {"has_error": error is not None, "checkpoint": json.dumps(checkpoint), "error": error, "tenant": tenant_id, "id": job_id},
        )


async def process_job(tenant_id: uuid.UUID, job_id: uuid.UUID, checkpoint: dict[str, object]) -> None:
    connector = connector_for(settings, tenant_graph_credentials)
    try:
        await process_job_with_connector(connector, tenant_id, job_id, checkpoint)
    finally:
        close = getattr(connector, "aclose", None)
        if close:
            await close()


async def tenant_graph_credentials(tenant_id: uuid.UUID) -> tuple[str, str]:
    """Load only this tenant's authenticated, encrypted Graph application secret."""
    async with AdminSessionLocal() as session:
        connection = await session.scalar(
            select(ConnectorConnection).where(
                ConnectorConnection.tenant_id == tenant_id,
                ConnectorConnection.consent_status == "connected",
            )
        )
    if not connection:
        raise RuntimeError("Tenant has not completed Microsoft Graph admin consent")
    secret = SecretCipher(settings.token_encryption_key).decrypt(
        connection.encrypted_client_secret, str(tenant_id)
    )
    return connection.client_id, secret


async def process_job_with_connector(
    connector: GraphConnector,
    tenant_id: uuid.UUID,
    job_id: uuid.UUID,
    checkpoint: dict[str, object],
) -> None:
    runtime = model_runtime()
    users = await connector.users(tenant_id)
    registrations = {item["id"]: item for item in await connector.registration_details(tenant_id)}
    risky_source_available = True
    try:
        risky = {item["id"]: item for item in await connector.risky_users(tenant_id)}
    except (httpx.HTTPError, GraphDeltaExpired, GraphThrottled):
        risky = {}
        risky_source_available = False
        log.warning("risky_user_source_unavailable", tenant=redacted_tenant(tenant_id))
    observation_since = datetime.now(UTC) - timedelta(days=30)
    sign_in_source_available = True
    alert_source_available = True
    try:
        sign_in_fetch = getattr(connector, "sign_ins", None)
        if sign_in_fetch is None:
            raise AttributeError("sign-in connector unavailable")
        raw_sign_ins = await sign_in_fetch(tenant_id, observation_since)
    except (AttributeError, httpx.HTTPError, GraphDeltaExpired, GraphThrottled):
        raw_sign_ins = []
        sign_in_source_available = False
        log.warning("sign_in_source_unavailable", tenant=redacted_tenant(tenant_id))
    try:
        alert_fetch = getattr(connector, "security_alerts", None)
        if alert_fetch is None:
            raise AttributeError("security-alert connector unavailable")
        raw_alerts = await alert_fetch(tenant_id, observation_since)
    except (AttributeError, httpx.HTTPError, GraphDeltaExpired, GraphThrottled):
        raw_alerts = []
        alert_source_available = False
        log.warning("security_alert_source_unavailable", tenant=redacted_tenant(tenant_id))
    new_checkpoint = dict(checkpoint)
    tenant_key = tenant_pseudonym_key(tenant_id)
    mailbox_failures: list[str] = []
    for item in users:
        async for session in tenant_session(tenant_id):
            user_id = str(item["id"])
            registration = registrations.get(user_id, {})
            risk = risky.get(user_id, {})
            user = await session.get(User, (tenant_id, user_id))
            if not user:
                user = User(
                    tenant_id=tenant_id,
                    id=user_id,
                    display_name=str(item.get("displayName", user_id)),
                    principal_hash=pseudonym(
                        tenant_key, "principal", item.get("userPrincipalName", user_id)
                    ),
                )
                session.add(user)
            user.is_admin = bool(item.get("isAdmin"))
            user.is_mfa_registered = bool(registration.get("isMfaRegistered", True))
            user.is_mfa_capable = bool(registration.get("isMfaCapable", True))
            user.entra_risk_level = str(risk.get("riskLevel", "none")) if risky_source_available else "unknown"
            user_sign_ins = [event for event in raw_sign_ins if str(event.get("userId")) == user_id]
            user_alerts = [event for event in raw_alerts if user_id in alert_user_ids(event)]
            for event in user_sign_ins:
                event_id = pseudonym(tenant_key, "sign-in", event.get("id", ""))
                if await session.get(SignInObservation, (tenant_id, event_id)):
                    continue
                location = event.get("location") if isinstance(event.get("location"), dict) else {}
                device = (
                    event.get("deviceDetail")
                    if isinstance(event.get("deviceDetail"), dict)
                    else {}
                )
                status = event.get("status") if isinstance(event.get("status"), dict) else {}
                prefix = network_bucket(event.get("ipAddress"))
                sign_in_observation = SignInObservationV1(
                    id=event_id,
                    user_id=user_id,
                    created_at=graph_datetime(event.get("createdDateTime")),
                    successful=int(status.get("errorCode", 0)) == 0,
                    is_interactive=bool(event.get("isInteractive", True)),
                    country=str(location.get("countryOrRegion") or "") or None,
                    city=str(location.get("city") or "") or None,
                    network_hash=(
                        pseudonym(tenant_key, "network-prefix", prefix) if prefix else None
                    ),
                    device_hash=(
                        pseudonym(tenant_key, "device", device.get("deviceId"))
                        if device.get("deviceId")
                        else None
                    ),
                    app_hash=(
                        pseudonym(tenant_key, "application", event.get("appId"))
                        if event.get("appId")
                        else None
                    ),
                    is_managed=device.get("isManaged"),
                    is_compliant=device.get("isCompliant"),
                    risk_level=str(event.get("riskLevelDuringSignIn") or "unknown").lower(),
                )
                session.add(
                    SignInObservation(
                        tenant_id=tenant_id,
                        **sign_in_observation.model_dump(exclude={"risk_level"}),
                        features={"risk_level": sign_in_observation.risk_level},
                    )
                )
            for event in user_alerts:
                event_id = pseudonym(tenant_key, "security-alert", event.get("id", ""))
                if await session.get(SecurityAlertObservation, (tenant_id, event_id)):
                    continue
                devices = event.get("deviceEvidence") or []
                first_device = devices[0] if isinstance(devices, list) and devices else {}
                device_name = (
                    first_device.get("deviceDnsName")
                    if isinstance(first_device, dict)
                    else None
                )
                alert_observation = SecurityAlertObservationV1(
                    id=event_id,
                    user_id=user_id,
                    created_at=graph_datetime(event.get("createdDateTime")),
                    severity=str(event.get("severity") or "unknown").lower(),
                    status=str(event.get("status") or "unknown"),
                    source=str(event.get("serviceSource") or "unknown"),
                    category=str(event.get("category") or "") or None,
                    device_hash=(
                        pseudonym(tenant_key, "device", device_name) if device_name else None
                    ),
                )
                session.add(
                    SecurityAlertObservation(
                        tenant_id=tenant_id,
                        **alert_observation.model_dump(),
                        details={},
                    )
                )
            delta_link = str(new_checkpoint.get(user_id)) if new_checkpoint.get(user_id) else None
            try:
                messages, next_delta = await connector.messages(
                    tenant_id, user_id, delta_link
                )
            except (httpx.HTTPError, GraphDeltaExpired, GraphThrottled) as exc:
                mailbox_failures.append(f"{user_id}: {type(exc).__name__}")
                log.warning(
                    "mailbox_sync_deferred",
                    tenant=redacted_tenant(tenant_id),
                    job_id=str(job_id),
                    user_hash=pseudonym(tenant_key, "user", user_id)[:12],
                    error_type=type(exc).__name__,
                )
                continue
            for message in messages:
                if "@removed" in message:
                    message_hash = pseudonym(tenant_key, "message", message["id"])
                    existing = await session.get(EmailFeature, (tenant_id, message_hash))
                    if existing:
                        await session.delete(existing)
                    continue
                safe, model_features = graph_message_features(message, user_id, tenant_key)
                metadata = EmailMetadataV1.model_validate(safe)
                fallback = {
                    "authenticationResults": metadata.authentication_results,
                    "replyToDomainMismatch": metadata.reply_to_domain_mismatch,
                    "fromSenderMismatch": metadata.from_sender_mismatch,
                    "receivedHops": metadata.received_hops,
                    "externalSender": metadata.external_sender,
                }
                probability = runtime.predict(model_features, fallback)
                existing = await session.get(EmailFeature, (tenant_id, metadata.id))
                if not existing:
                    session.add(
                        EmailFeature(
                            tenant_id=tenant_id,
                            id=metadata.id,
                            user_id=user_id,
                            received_at=metadata.received_at,
                            risk_probability=probability,
                            features={
                                **metadata.model_dump(
                                    mode="json", exclude={"id", "user_id", "received_at"}
                                ),
                                "model_features": model_features,
                            },
                        )
                    )
            if next_delta:
                new_checkpoint[user_id] = next_delta
            await session.flush()
            now = datetime.now(UTC)
            today = now.date()
            first_day = today - timedelta(days=89)
            all_email = list(
                await session.scalars(
                    select(EmailFeature).where(
                        EmailFeature.user_id == user_id,
                        EmailFeature.received_at
                        >= datetime.combine(first_day, time.min, tzinfo=UTC),
                    )
                )
            )
            existing_daily = list(
                await session.scalars(
                    select(UserDailyFeature).where(
                        UserDailyFeature.user_id == user_id,
                        UserDailyFeature.day >= first_day,
                    )
                )
            )
            existing_scores = list(
                await session.scalars(
                    select(RiskScore)
                    .where(
                        RiskScore.user_id == user_id,
                        RiskScore.calculated_at
                        >= datetime.combine(first_day, time.min, tzinfo=UTC),
                    )
                    .order_by(RiskScore.calculated_at)
                )
            )
            email_by_day: dict[object, list[EmailFeature]] = {}
            for email in all_email:
                email_by_day.setdefault(email.received_at.date(), []).append(email)
            daily_by_day = {item.day: item for item in existing_daily}
            score_by_day = {item.calculated_at.date(): item for item in existing_scores}
            rolling_counts: list[int] = []
            rolling_domains: list[set[str]] = []
            threshold = runtime.thresholds.get("email_probability", 0.5)
            for offset in range(90):
                day = first_day + timedelta(days=offset)
                day_email = email_by_day.get(day, [])
                current_count = len(day_email)
                baseline_counts = rolling_counts[-30:]
                if baseline_counts:
                    median = statistics.median(baseline_counts)
                    mad = statistics.median(abs(value - median) for value in baseline_counts)
                    robust_z = abs(current_count - median) / max(1.0, 1.4826 * mad)
                    # Normal day-to-day volume variation is not compromise evidence.
                    # Only deviations beyond three robust standard deviations enter
                    # the legacy communication-behaviour component.
                    behaviour = min(1.0, max(0.0, robust_z - 3.0) / 3.0)
                else:
                    behaviour = 0.0
                probabilities = [email.risk_probability for email in day_email]
                email_max = max(probabilities, default=0.05)
                email_mean = sum(probabilities) / len(probabilities) if probabilities else 0.05
                external_ratio = (
                    sum(bool(email.features.get("external_sender")) for email in day_email)
                    / max(1, current_count)
                )
                suspicious_count = sum(
                    email.risk_probability >= threshold for email in day_email
                )
                current_domains = {
                    str(email.features.get("sender_domain_hash"))
                    for email in day_email
                    if email.features.get("sender_domain_hash")
                }
                historical_domains = set().union(*rolling_domains[-30:]) if rolling_domains else set()
                novelty = len(current_domains - historical_domains) / max(1, len(current_domains))
                daily = daily_by_day.get(day)
                is_new_daily = daily is None
                if not daily:
                    daily = UserDailyFeature(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        day=day,
                        emails_received=current_count,
                        email_risk_mean=email_mean,
                        email_risk_max=email_max,
                        behaviour_anomaly_score=behaviour,
                    )
                    session.add(daily)
                    daily_by_day[day] = daily
                daily_changed = is_new_daily or any(
                    (
                        daily.emails_received != current_count,
                        daily.email_risk_mean != email_mean,
                        daily.email_risk_max != email_max,
                        daily.behaviour_anomaly_score != behaviour,
                        daily.external_sender_ratio != external_ratio,
                        daily.suspicious_header_count != suspicious_count,
                        daily.sender_domain_novelty != novelty,
                        daily.feature_version != "UserDailyFeaturesV1",
                    )
                )
                if daily_changed:
                    daily.emails_received = current_count
                    daily.email_risk_mean = email_mean
                    daily.email_risk_max = email_max
                    daily.behaviour_anomaly_score = behaviour
                    daily.external_sender_ratio = external_ratio
                    daily.suspicious_header_count = suspicious_count
                    daily.sender_domain_novelty = novelty
                    daily.feature_version = "UserDailyFeaturesV1"
                    daily.calculated_at = now
                scored = hybrid_user_score(
                    email=email_max,
                    behaviour=behaviour,
                    entra_level=user.entra_risk_level,
                    mfa_registered=user.is_mfa_registered,
                    is_admin=user.is_admin,
                    weights=runtime.weights,
                )
                previous_score = score_by_day.get(day)
                should_append = not previous_score or (
                    day == today
                    and (
                        previous_score.score != scored.score
                        or previous_score.level != scored.level
                        or previous_score.components != scored.components
                    )
                )
                # Historical V1 records remain available for comparison, but the
                # current product score is written from the canonical V3 window
                # below. Writing both for today made the dashboard nondeterministic.
                if should_append and day != today:
                    calculated_at = (
                        now
                        if day == today
                        else datetime.combine(day, time.max, tzinfo=UTC)
                    )
                    score = RiskScore(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        score=scored.score,
                        level=scored.level,
                        components=scored.components,
                        model_version=runtime.version,
                        calculated_at=calculated_at,
                    )
                    score.factors = [
                        RiskFactor(
                            tenant_id=tenant_id,
                            name=name,
                            contribution=contribution,
                        )
                        for name, contribution in scored.factors
                    ]
                    session.add(score)
                    score_by_day[day] = score
                rolling_counts.append(current_count)
                rolling_domains.append(current_domains)

            stored_sign_ins = list(
                await session.scalars(
                    select(SignInObservation).where(
                        SignInObservation.user_id == user_id,
                        SignInObservation.created_at >= observation_since,
                    )
                )
            )
            stored_alerts = list(
                await session.scalars(
                    select(SecurityAlertObservation).where(
                        SecurityAlertObservation.user_id == user_id,
                        SecurityAlertObservation.created_at >= observation_since,
                    )
                )
            )
            recent_cutoff = now - timedelta(hours=24)
            baseline_sign_ins = [
                event for event in stored_sign_ins if event.created_at < recent_cutoff
            ]
            recent_sign_ins = [
                event for event in stored_sign_ins if event.created_at >= recent_cutoff
            ]
            known_countries = {event.country for event in baseline_sign_ins if event.country}
            known_networks = {
                event.network_hash for event in baseline_sign_ins if event.network_hash
            }
            known_devices = {
                event.device_hash for event in baseline_sign_ins if event.device_hash
            }
            known_apps = {event.app_hash for event in baseline_sign_ins if event.app_hash}
            sign_in_feature_values = sign_in_window_signals(
                [
                    {
                        "created_at": event.created_at,
                        "country": event.country,
                        "network_hash": event.network_hash,
                        "device_hash": event.device_hash,
                        "app_hash": event.app_hash,
                        "successful": event.successful,
                    }
                    for event in recent_sign_ins
                ],
                known_countries=known_countries,
                known_networks=known_networks,
                known_devices=known_devices,
                known_apps=known_apps,
            )
            history_days = len({event.created_at.date() for event in baseline_sign_ins})
            local_identity = local_identity_anomaly(sign_in_feature_values, history_days)
            if not sign_in_source_available:
                local_identity = local_identity_anomaly({}, 30)
            provider_identity = provider_identity_risk(
                str(risk.get("riskLevel")) if risk.get("riskLevel") is not None else None
            )
            identity = identity_compromise(local_identity, provider_identity)

            today_email = email_by_day.get(today, [])
            canonical_email_values: list[float] = []
            auth_explanations: list[str] = []
            for email in today_email:
                authentication = email.features.get("authentication_results")
                auth = auth_integrity(
                    authentication if isinstance(authentication, dict) else None
                )
                sender = sender_context(
                    external_sender=bool(email.features.get("external_sender")),
                    reply_to_domain_mismatch=bool(
                        email.features.get("reply_to_domain_mismatch")
                    ),
                    from_sender_mismatch=bool(email.features.get("from_sender_mismatch")),
                )
                if auth.value is None:
                    canonical_email_values.append(sender.value or 0.0)
                else:
                    canonical_email_values.append(
                        min(1.0, 0.75 * auth.value + 0.25 * (sender.value or 0.0))
                    )
                auth_explanations.append(auth.explanation)
            email_component = top_k_mean(canonical_email_values)
            endpoint_component = endpoint_threat(
                [alert.severity for alert in stored_alerts] if alert_source_available else None
            )
            components = {
                "email_threat": email_component,
                "identity_compromise": identity,
                "mfa_exposure": mfa_exposure(
                    bool(registration.get("isMfaRegistered"))
                    if "isMfaRegistered" in registration
                    else None,
                    bool(registration.get("isMfaCapable"))
                    if "isMfaCapable" in registration
                    else None,
                ),
                "privilege_exposure": privilege_exposure(
                    bool(item.get("isAdmin")) if "isAdmin" in item else None
                ),
                "endpoint_threat": endpoint_component,
            }
            v2_score = score_components(components)
            window_end = datetime.combine(today, time.max, tzinfo=UTC)
            window_values = {
                "score": v2_score.score,
                "level": v2_score.level,
                "components": v2_score.components,
                "features": {
                    "email_top3": email_component.value,
                    **{f"identity_{key}": value for key, value in sign_in_feature_values.items()},
                },
                "availability": v2_score.coverage,
                "evidence": {
                    "email_observation_ids": [email.id for email in today_email],
                    "sign_in_observation_ids": [event.id for event in recent_sign_ins],
                    "security_alert_ids": [alert.id for alert in stored_alerts],
                    "explanations": {
                        "email_auth": auth_explanations,
                        "identity": identity.explanation,
                        "mfa": components["mfa_exposure"].explanation,
                        "privilege": components["privilege_exposure"].explanation,
                        "endpoint": endpoint_component.explanation,
                    },
                },
                "feature_version": "UserFeatureWindowV2",
                "model_version": runtime.version,
                "calculated_at": now,
            }
            await session.execute(
                pg_insert(UserFeatureWindow)
                .values(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    window_end=window_end,
                    **window_values,
                )
                .on_conflict_do_update(
                    index_elements=[
                        UserFeatureWindow.tenant_id,
                        UserFeatureWindow.user_id,
                        UserFeatureWindow.window_end,
                    ],
                    set_=window_values,
                )
            )
            if v2_score.score is not None:
                latest_current = next(
                    (
                        risk
                        for risk in reversed(existing_scores)
                        if risk.calculated_at.date() == today
                        and risk.model_version == runtime.version
                    ),
                    None,
                )
                v3_components = {
                    name: float(value or 0.0)
                    for name, value in v2_score.contributions.items()
                }
                if (
                    latest_current is None
                    or latest_current.score != v2_score.score
                    or latest_current.level != v2_score.level
                    or latest_current.components != v3_components
                ):
                    factor_names = {
                        "email_threat": "Suspicious mail authentication and header metadata",
                        "identity_compromise": "Identity compromise evidence",
                        "mfa_exposure": "MFA posture exposure",
                        "privilege_exposure": "Privileged impact amplification",
                        "endpoint_threat": "Endpoint security alert",
                    }
                    current_score = RiskScore(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        score=v2_score.score,
                        level=v2_score.level,
                        components=v3_components,
                        model_version=runtime.version,
                        calculated_at=now,
                    )
                    current_score.factors = [
                        RiskFactor(
                            tenant_id=tenant_id,
                            name=factor_names[name],
                            contribution=round(float(value), 2),
                        )
                        for name, value in v2_score.contributions.items()
                        if value is not None and float(value) >= 1.0
                    ]
                    session.add(current_score)
                    existing_scores.append(current_score)
            user.last_seen_at = now
    if mailbox_failures:
        error = "Partial mailbox failures: " + ", ".join(mailbox_failures)
        await complete_job(tenant_id, job_id, new_checkpoint, error[:2000])
        log.warning(
            "sync_partially_completed",
            tenant=redacted_tenant(tenant_id),
            job_id=str(job_id),
            failed_mailboxes=len(mailbox_failures),
            model_version=runtime.version,
        )
        return
    await complete_job(tenant_id, job_id, new_checkpoint)
    log.info(
        "sync_completed",
        tenant=redacted_tenant(tenant_id),
        job_id=str(job_id),
        model_version=runtime.version,
    )


async def ensure_jobs() -> None:
    async with AdminSessionLocal() as session, session.begin():
        await session.execute(
            text(
                """UPDATE sync_jobs SET status='queued', started_at=NULL,
                       error='Recovered after worker timeout'
                   WHERE status='running' AND started_at < now() - interval '60 seconds'"""
            )
        )
        await session.execute(text("DELETE FROM email_features WHERE received_at < now() - interval '180 days'"))
        await session.execute(text("DELETE FROM risk_scores WHERE calculated_at < now() - interval '365 days'"))
        await session.execute(text("DELETE FROM user_daily_features WHERE day < current_date - 365"))
        await session.execute(text("DELETE FROM feedback WHERE created_at < now() - interval '365 days'"))
        await session.execute(text("DELETE FROM audit_events WHERE created_at < now() - interval '365 days'"))
        await session.execute(
            delete(SignInObservation).where(
                SignInObservation.created_at < datetime.now(UTC) - timedelta(days=180)
            )
        )
        await session.execute(
            delete(SecurityAlertObservation).where(
                SecurityAlertObservation.created_at < datetime.now(UTC) - timedelta(days=365)
            )
        )
        await session.execute(
            delete(UserFeatureWindow).where(
                UserFeatureWindow.window_end < datetime.now(UTC) - timedelta(days=365)
            )
        )
        await session.execute(
            text(
                "DELETE FROM sync_jobs WHERE status IN ('completed', 'dead') "
                "AND created_at < now() - interval '365 days'"
            )
        )
        tenant_ids = list(await session.scalars(select(Tenant.id)))
        for tenant_id in tenant_ids:
            active = await session.scalar(
                select(SyncJob.id)
                .where(
                    SyncJob.tenant_id == tenant_id,
                    SyncJob.status.in_(["queued", "running", "retrying"]),
                )
                .limit(1)
            )
            if not active:
                previous = await session.scalar(
                    select(SyncJob).where(SyncJob.tenant_id == tenant_id).order_by(SyncJob.created_at.desc()).limit(1)
                )
                if (
                    previous
                    and previous.completed_at
                    and previous.completed_at > datetime.now(UTC) - timedelta(seconds=settings.sync_interval_seconds)
                ):
                    continue
                session.add(SyncJob(tenant_id=tenant_id, checkpoint=previous.checkpoint if previous else {}))


async def run() -> None:
    while True:
        await ensure_jobs()
        claimed = await claim_job()
        if not claimed:
            await asyncio.sleep(settings.sync_interval_seconds)
            continue
        tenant_id, job_id, checkpoint = claimed
        async with AdminSessionLocal() as lock_session:
            lock_key = int(
                await lock_session.scalar(
                    text("SELECT hashtextextended(:tenant, 0)"),
                    {"tenant": str(tenant_id)},
                )
                or 0
            )
            locked = bool(
                await lock_session.scalar(
                    text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_key}
                )
            )
            if not locked:
                await complete_job(tenant_id, job_id, checkpoint, "Tenant synchronization lock is busy")
                continue
            try:
                with tracer.start_as_current_span("m365risk.sync_job") as span:
                    span.set_attribute("tenant.hash", redacted_tenant(tenant_id))
                    span.set_attribute("sync_job.id", str(job_id))
                    span.set_attribute("model.version", model_runtime().version)
                    await process_job(tenant_id, job_id, checkpoint)
            except Exception as exc:  # worker boundary must persist failures
                await complete_job(tenant_id, job_id, checkpoint, str(exc)[:2000])
                log.exception(
                    "sync_failed", tenant=redacted_tenant(tenant_id), job_id=str(job_id)
                )
            finally:
                await lock_session.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": lock_key}
                )


if __name__ == "__main__":
    asyncio.run(run())
