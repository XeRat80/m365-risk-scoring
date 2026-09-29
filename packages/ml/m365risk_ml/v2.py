from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from statistics import fmean
from typing import Literal

Availability = Literal["available", "unavailable", "insufficient_history"]

V2_COMPONENT_WEIGHTS = {
    "email_threat": 0.30,
    "identity_compromise": 0.30,
    "mfa_exposure": 0.15,
    "privilege_exposure": 0.15,
    "endpoint_threat": 0.10,
}
V2_COMPONENT_NAMES = tuple(V2_COMPONENT_WEIGHTS)

AUTH_PASS = {"pass", "bestguesspass"}
AUTH_FAIL = {"fail", "hardfail"}
AUTH_PARTIAL = {"softfail", "neutral", "temperror", "permerror"}


@dataclass(frozen=True)
class CanonicalSignal:
    value: float | None
    availability: Availability
    explanation: str


@dataclass(frozen=True)
class V2Score:
    score: int | None
    level: str
    components: dict[str, float | None]
    coverage: dict[str, Availability]
    contributions: dict[str, float | None]


def component_feature_vector(
    components: Mapping[str, CanonicalSignal],
) -> dict[str, float]:
    """Encode component values with explicit availability masks for model parity.

    A missing value uses a numeric placeholder only alongside masks, so a model can
    distinguish a genuinely safe zero from unavailable or insufficient evidence.
    """
    vector: dict[str, float] = {}
    for name in V2_COMPONENT_NAMES:
        signal = components[name]
        is_available = signal.value is not None and signal.availability == "available"
        value = signal.value
        vector[f"{name}__value"] = (
            clamp(float(value)) if value is not None and is_available else 0.0
        )
        vector[f"{name}__available"] = float(is_available)
        vector[f"{name}__insufficient_history"] = float(
            signal.availability == "insufficient_history"
        )
    return vector


def clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _auth_value(value: object) -> str:
    normalized = str(value or "unknown").strip().lower()
    return normalized if normalized else "unknown"


def auth_integrity(authentication_results: Mapping[str, object] | None) -> CanonicalSignal:
    """Collapse email authentication into one signal so SPF/DKIM/DMARC are not re-counted.

    Composite authentication has precedence. DMARC is used next because it evaluates alignment.
    SPF and DKIM are only combined when neither higher-level result is available.
    """
    auth = authentication_results or {}
    compauth = _auth_value(auth.get("compauth"))
    if compauth in AUTH_PASS:
        return CanonicalSignal(0.0, "available", "Composite authentication passed")
    if compauth in AUTH_FAIL:
        return CanonicalSignal(1.0, "available", "Composite authentication failed")
    if compauth in AUTH_PARTIAL:
        return CanonicalSignal(0.65, "available", f"Composite authentication: {compauth}")

    dmarc = _auth_value(auth.get("dmarc"))
    if dmarc in AUTH_PASS:
        return CanonicalSignal(0.0, "available", "DMARC alignment passed")
    if dmarc in AUTH_FAIL:
        return CanonicalSignal(1.0, "available", "DMARC alignment failed")
    if dmarc in AUTH_PARTIAL:
        return CanonicalSignal(0.65, "available", f"DMARC: {dmarc}")

    lower_level = [_auth_value(auth.get(name)) for name in ("dkim", "spf")]
    observed = [value for value in lower_level if value != "unknown" and value != "none"]
    if not observed:
        return CanonicalSignal(None, "unavailable", "No trustworthy authentication result")
    if any(value in AUTH_FAIL for value in observed):
        return CanonicalSignal(0.85, "available", "SPF or DKIM failed; DMARC unavailable")
    if any(value in AUTH_PARTIAL for value in observed):
        return CanonicalSignal(0.55, "available", "SPF or DKIM was inconclusive")
    if all(value in AUTH_PASS for value in observed):
        return CanonicalSignal(0.10, "available", "Available SPF/DKIM checks passed")
    return CanonicalSignal(None, "unavailable", "Authentication result was not recognized")


def sender_context(
    *,
    external_sender: bool,
    reply_to_domain_mismatch: bool,
    from_sender_mismatch: bool,
) -> CanonicalSignal:
    """Represent header identity context without duplicating authentication alignment."""
    mismatch_count = int(reply_to_domain_mismatch) + int(from_sender_mismatch)
    # Receiving legitimate external mail is normal business activity, not threat
    # evidence. Only identity inconsistencies contribute to risk.
    value = 0.45 * mismatch_count
    labels: list[str] = []
    if external_sender:
        labels.append("external sender")
    if reply_to_domain_mismatch:
        labels.append("reply-to mismatch")
    if from_sender_mismatch:
        labels.append("from/sender mismatch")
    return CanonicalSignal(clamp(value), "available", ", ".join(labels) or "normal sender context")


def top_k_mean(values: Iterable[float], k: int = 3) -> CanonicalSignal:
    """Aggregate daily email risk once, limiting both one-message spikes and volume inflation."""
    ordered = sorted((clamp(float(value)) for value in values), reverse=True)
    if not ordered:
        return CanonicalSignal(None, "unavailable", "No email observations in this window")
    selected = ordered[: max(1, k)]
    return CanonicalSignal(fmean(selected), "available", f"Mean of top {len(selected)} email risks")


def provider_identity_risk(level: str | None) -> CanonicalSignal:
    if level is None or level.lower() in {"unknown", "hidden", "unavailable"}:
        return CanonicalSignal(None, "unavailable", "Entra risk evidence unavailable")
    mapped = {"none": 0.0, "low": 0.30, "medium": 0.65, "high": 1.0}
    normalized = level.lower()
    if normalized not in mapped:
        return CanonicalSignal(None, "unavailable", "Unrecognized Entra risk level")
    return CanonicalSignal(mapped[normalized], "available", f"Entra risk level: {normalized}")


def local_identity_anomaly(
    signals: Mapping[str, float | None], history_days: int
) -> CanonicalSignal:
    """Fuse independent UEBA dimensions; values describe the current window only."""
    values = [clamp(value) for value in signals.values() if value is not None]
    if history_days < 7:
        return CanonicalSignal(
            None, "insufficient_history", "At least 7 baseline days are required"
        )
    if not values:
        return CanonicalSignal(None, "unavailable", "No sign-in evidence in this window")
    # Noisy-OR preserves distinct dimensions without letting a repeated signal exceed 1.
    combined = 1.0
    for value in values:
        combined *= 1.0 - value
    return CanonicalSignal(1.0 - combined, "available", "Independent local sign-in anomalies")


def identity_compromise(
    local: CanonicalSignal,
    provider: CanonicalSignal,
) -> CanonicalSignal:
    """Use the strongest identity evidence instead of summing overlapping detectors."""
    candidates = [
        ("local", local.value, local.explanation, local.availability),
        ("provider", provider.value, provider.explanation, provider.availability),
    ]
    available = [candidate for candidate in candidates if candidate[1] is not None]
    if not available:
        availability: Availability = (
            "insufficient_history"
            if any(item[3] == "insufficient_history" for item in candidates)
            else "unavailable"
        )
        return CanonicalSignal(None, availability, "Identity evidence unavailable")
    source, value, explanation, _ = max(available, key=lambda item: float(item[1] or 0.0))
    assert value is not None
    return CanonicalSignal(float(value), "available", f"{source}: {explanation}")


def mfa_exposure(registered: bool | None, capable: bool | None) -> CanonicalSignal:
    if registered is None or capable is None:
        return CanonicalSignal(None, "unavailable", "MFA registration evidence unavailable")
    if not capable:
        return CanonicalSignal(1.0, "available", "User is not MFA capable")
    if not registered:
        return CanonicalSignal(0.90, "available", "User has not registered MFA")
    return CanonicalSignal(0.0, "available", "MFA is registered and capable")


def privilege_exposure(is_admin: bool | None, eligible_role_count: int = 0) -> CanonicalSignal:
    if is_admin is None:
        return CanonicalSignal(None, "unavailable", "Directory role evidence unavailable")
    if is_admin:
        value = min(1.0, 0.70 + 0.05 * max(0, eligible_role_count))
        return CanonicalSignal(value, "available", "Active privileged directory role")
    if eligible_role_count:
        value = min(0.65, 0.25 + 0.05 * eligible_role_count)
        return CanonicalSignal(value, "available", "Eligible privileged directory role")
    return CanonicalSignal(0.0, "available", "No privileged directory role observed")


def endpoint_threat(alert_severities: Sequence[str] | None) -> CanonicalSignal:
    if alert_severities is None:
        return CanonicalSignal(None, "unavailable", "Defender alert source unavailable")
    mapped = {"informational": 0.10, "low": 0.25, "medium": 0.60, "high": 1.0}
    values = [mapped.get(str(item).lower(), 0.0) for item in alert_severities]
    return CanonicalSignal(max(values, default=0.0), "available", "Highest active alert severity")


def score_components(components: Mapping[str, CanonicalSignal]) -> V2Score:
    encoded = component_feature_vector(components)
    values = {name: signal.value for name, signal in components.items()}
    coverage = {name: signal.availability for name, signal in components.items()}
    contributions = {
        name: (
            None
            if encoded[f"{name}__available"] == 0
            else 100 * V2_COMPONENT_WEIGHTS[name] * encoded[f"{name}__value"]
        )
        for name, signal in components.items()
    }
    threat_names = tuple(name for name in V2_COMPONENT_NAMES if name != "privilege_exposure")
    available_weight = sum(
        V2_COMPONENT_WEIGHTS[name]
        for name in threat_names
        if encoded[f"{name}__available"] == 1
    )
    if available_weight < 0.60:
        return V2Score(None, "insufficient_data", values, coverage, contributions)
    weighted = sum(contributions[name] or 0.0 for name in threat_names) / available_weight
    # Report contributions in the same reweighted space used by the final score,
    # so analyst-visible factors reconcile to the displayed total.
    for name in threat_names:
        contribution = contributions[name]
        if contribution is not None:
            contributions[name] = contribution / available_weight
    privilege = values.get("privilege_exposure") or 0.0
    # A privileged role increases impact only when compromise evidence exists.
    # It can never create risk for an otherwise healthy identity.
    privilege_addition = weighted * V2_COMPONENT_WEIGHTS["privilege_exposure"] * privilege
    contributions["privilege_exposure"] = privilege_addition
    score = round(min(100.0, weighted + privilege_addition))
    level = (
        "critical" if score >= 75 else "high" if score >= 50 else "medium" if score >= 25 else "low"
    )
    return V2Score(score, level, values, coverage, contributions)


def sign_in_window_signals(
    events: Sequence[Mapping[str, object]],
    *,
    known_countries: set[str],
    known_networks: set[str],
    known_devices: set[str],
    known_apps: set[str],
    normal_start_hour: int = 6,
    normal_end_hour: int = 22,
) -> dict[str, float | None]:
    """Create one value per UEBA dimension from privacy-safe sign-in observations."""
    if not events:
        return {name: None for name in ("time", "location", "network", "device", "auth", "app")}

    def ratio(predicate: object) -> float:
        callback = predicate
        return sum(bool(callback(event)) for event in events) / len(events)  # type: ignore[operator]

    def hour(event: Mapping[str, object]) -> int:
        value = event.get("created_at")
        return value.hour if isinstance(value, datetime) else 12

    return {
        "time": ratio(lambda event: not normal_start_hour <= hour(event) < normal_end_hour),
        "location": ratio(
            lambda event: (
                bool(event.get("country")) and str(event.get("country")) not in known_countries
            )
        ),
        "network": ratio(
            lambda event: (
                bool(event.get("network_hash"))
                and str(event.get("network_hash")) not in known_networks
            )
        ),
        "device": ratio(
            lambda event: (
                bool(event.get("device_hash"))
                and str(event.get("device_hash")) not in known_devices
            )
        ),
        "auth": ratio(lambda event: not bool(event.get("successful", True))),
        "app": ratio(
            lambda event: (
                bool(event.get("app_hash")) and str(event.get("app_hash")) not in known_apps
            )
        ),
    }
