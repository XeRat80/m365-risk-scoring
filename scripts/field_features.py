"""Canonical, privacy-reduced signals for an authorized Graph field scan."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
from datetime import UTC, datetime, timedelta
from typing import Any

from packages.ml.m365risk_ml.v2 import (
    CanonicalSignal,
    endpoint_threat,
    identity_compromise,
    local_identity_anomaly,
    mfa_exposure,
    privilege_exposure,
    provider_identity_risk,
    sign_in_window_signals,
)


def _digest(key: bytes, kind: str, value: object) -> str:
    return hmac.new(key, f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()


def _datetime(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _network_hash(key: bytes, value: object) -> str | None:
    try:
        address = ipaddress.ip_address(str(value))
    except ValueError:
        return None
    prefix = 24 if address.version == 4 else 48
    network = ipaddress.ip_network(f"{address}/{prefix}", strict=False)
    return _digest(key, "network-prefix", network)


def signal_dict(signal: CanonicalSignal) -> dict[str, Any]:
    return {
        "value": signal.value,
        "availability": signal.availability,
        "explanation": signal.explanation,
    }


def canonical_from_graph(
    *,
    user_id: str,
    key: bytes,
    registration: dict[str, Any] | None,
    risky: dict[str, Any] | None,
    admin_ids: set[str] | None,
    sign_ins: list[dict[str, Any]] | None,
    alerts: list[dict[str, Any]] | None,
    captured_at: datetime,
) -> dict[str, Any]:
    recent_cutoff = captured_at - timedelta(hours=24)
    observations: list[dict[str, Any]] = []
    for event in sign_ins or []:
        if str(event.get("userId")) != user_id:
            continue
        try:
            occurred = _datetime(event["createdDateTime"])
        except (KeyError, TypeError, ValueError):
            continue
        location = event.get("location") if isinstance(event.get("location"), dict) else {}
        device = event.get("deviceDetail") if isinstance(event.get("deviceDetail"), dict) else {}
        status = event.get("status") if isinstance(event.get("status"), dict) else {}
        observations.append({
            "created_at": occurred,
            "country": str(location.get("countryOrRegion") or "") or None,
            "network_hash": _network_hash(key, event.get("ipAddress")),
            "device_hash": _digest(key, "device", device["deviceId"]) if device.get("deviceId") else None,
            "app_hash": _digest(key, "app", event["appId"]) if event.get("appId") else None,
            "successful": int(status.get("errorCode") or 0) == 0,
        })
    baseline = [event for event in observations if event["created_at"] < recent_cutoff]
    recent = [event for event in observations if event["created_at"] >= recent_cutoff]
    signals = sign_in_window_signals(
        recent,
        known_countries={str(event["country"]) for event in baseline if event["country"]},
        known_networks={str(event["network_hash"]) for event in baseline if event["network_hash"]},
        known_devices={str(event["device_hash"]) for event in baseline if event["device_hash"]},
        known_apps={str(event["app_hash"]) for event in baseline if event["app_hash"]},
    )
    # Tenant/user working hours are not known. UTC hour is not evidence of a
    # late-night sign-in, so do not score this dimension in a field pilot.
    signals["time"] = None
    history_days = len({event["created_at"].date() for event in baseline})
    local = local_identity_anomaly(signals, history_days)
    if sign_ins is None:
        local = CanonicalSignal(None, "unavailable", "Sign-in source unavailable")
    provider = provider_identity_risk(
        str(risky["riskLevel"]) if risky and risky.get("riskLevel") is not None else None
    )
    identity = identity_compromise(local, provider)
    own_alert_severities: list[str] | None = None
    if alerts is not None:
        own_alert_severities = [
            str(alert.get("severity") or "unknown")
            for alert in alerts
            if str(alert.get("status") or "").lower() != "resolved"
            and any(
                isinstance(state, dict) and str(state.get("userId")) == user_id
                for state in alert.get("userStates") or []
            )
        ]
    components = {
        "identity_compromise": identity,
        "mfa_exposure": mfa_exposure(
            registration.get("isMfaRegistered") if registration else None,
            registration.get("isMfaCapable") if registration else None,
        ),
        "privilege_exposure": privilege_exposure(
            user_id in admin_ids if admin_ids is not None else None
        ),
        "endpoint_threat": endpoint_threat(own_alert_severities),
    }
    return {
        "sample_id": _digest(key, "user", user_id),
        "window_end": captured_at.isoformat(),
        "feature_version": "RealGraphCanonicalV1",
        "canonical": {name: signal_dict(signal) for name, signal in components.items()},
        "identity_features": signals,
        "baseline_days": history_days,
    }
