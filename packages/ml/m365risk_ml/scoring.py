from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

HYBRID_WEIGHTS = {
    "email": 0.35,
    "behaviour": 0.20,
    "entra": 0.20,
    "posture": 0.15,
    "privilege": 0.10,
}

ENTRA_LEVELS = {"none": 0.0, "low": 0.30, "medium": 0.65, "high": 1.0}


@dataclass(frozen=True)
class ScoredRisk:
    score: int
    level: str
    components: dict[str, float]
    factors: list[tuple[str, float]]


def clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def email_threat_score(message: Mapping[str, object]) -> tuple[float, list[str]]:
    """Transparent metadata-only baseline used by the worker and training benchmark."""
    score = 0.03
    factors: list[str] = []
    auth = message.get("authenticationResults") or {}
    if not isinstance(auth, Mapping):
        auth = {}
    for key, weight in (("spf", 0.22), ("dkim", 0.20), ("dmarc", 0.24)):
        result = str(auth.get(key, "none")).lower()
        if result in {"fail", "softfail", "none"}:
            score += weight if result == "fail" else weight * 0.45
            factors.append(f"{key.upper()} {result}")
    if bool(message.get("replyToDomainMismatch")):
        score += 0.18
        factors.append("Reply-to domain mismatch")
    if bool(message.get("fromSenderMismatch")):
        score += 0.14
        factors.append("From and sender mismatch")
    hops = int(str(message.get("receivedHops") or 0))
    if hops == 0 or hops > 8:
        score += 0.08
        factors.append("Unusual relay path")
    if bool(message.get("externalSender")):
        score += 0.04
    return clamp(score), factors


def precision_guarded_email_probability(
    model_probability: float,
    message: Mapping[str, object],
) -> float:
    """Combine ML ranking with trustworthy authentication evidence.

    The legacy corpus cannot teach the model the meaning of SPF/DKIM/DMARC
    outcomes because those fields are absent from it.  A fully aligned message
    must therefore not become an alert solely because it is out-of-distribution
    for that corpus. Conversely, explicit authentication failures or identity
    mismatches must not be diluted by an uncertain model prediction.
    """

    auth = message.get("authenticationResults") or {}
    if not isinstance(auth, Mapping):
        auth = {}
    results = {
        name: str(auth.get(name, "unknown")).strip().lower()
        for name in ("spf", "dkim", "dmarc")
    }
    reply_mismatch = bool(message.get("replyToDomainMismatch"))
    sender_mismatch = bool(message.get("fromSenderMismatch"))
    all_pass = all(value in {"pass", "bestguesspass"} for value in results.values())
    explicit_failure = any(value in {"fail", "hardfail"} for value in results.values())

    # Passing authentication proves domain alignment, not that a message is benign.
    # Preserve the model as low-priority telemetry, but keep it below the alerting
    # range when there is no contradictory header evidence.
    if all_pass and not reply_mismatch and not sender_mismatch:
        return min(clamp(float(model_probability)), 0.20)

    transparent_probability, _ = email_threat_score(message)
    probability = clamp(float(model_probability))
    if explicit_failure:
        probability = max(probability, transparent_probability, 0.80)
    if reply_mismatch or sender_mismatch:
        probability = max(probability, transparent_probability, 0.65)
    return clamp(probability)


def hybrid_user_score(
    *,
    email: float,
    behaviour: float,
    entra_level: str,
    mfa_registered: bool,
    is_admin: bool,
    weights: Mapping[str, float] = HYBRID_WEIGHTS,
) -> ScoredRisk:
    components = {
        "email": clamp(email),
        "behaviour": clamp(behaviour),
        "entra": ENTRA_LEVELS.get(entra_level.lower(), 0.0),
        "posture": 0.0 if mfa_registered else 1.0,
        "privilege": 0.0,
    }
    contributions = {
        name: 100 * weights[name] * value
        for name, value in components.items()
        if name != "privilege"
    }
    # Privilege changes incident impact; it is not evidence of compromise by
    # itself. It amplifies existing evidence by at most ten percent and stays
    # exactly zero for a healthy administrator.
    base_score = sum(contributions.values())
    contributions["privilege"] = base_score * weights["privilege"] if is_admin else 0.0
    score = round(sum(contributions.values()))
    level = "critical" if score >= 75 else "high" if score >= 50 else "medium" if score >= 25 else "low"
    names = {
        "email": "High-risk email headers",
        "behaviour": "Unusual communication behaviour",
        "entra": f"Entra risk level: {entra_level}",
        "posture": "MFA not registered",
        "privilege": "Privileged account exposure",
    }
    factors = sorted(
        [(names[key], round(value, 2)) for key, value in contributions.items() if value >= 1],
        key=lambda item: item[1],
        reverse=True,
    )[:5]
    return ScoredRisk(score=score, level=level, components=contributions, factors=factors)
