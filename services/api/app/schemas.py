from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ErrorEnvelope(BaseModel):
    code: str
    message: str
    request_id: str | None = None


class AlertCloseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Literal["resolved", "false_positive", "accepted_risk"]


class AlertResponse(BaseModel):
    id: str
    user_id: str | None
    severity: str
    provider_status: str
    soc_status: str
    created_at: datetime
    closure: dict[str, object] | None = None


class AlertPage(BaseModel):
    items: list[AlertResponse]
    next_cursor: str | None = None


class TokenRequest(BaseModel):
    tenant_id: uuid.UUID
    role: Literal["analyst", "admin"] = "analyst"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class EmailMetadataV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    user_id: str
    received_at: datetime
    external_sender: bool
    recipient_count: int = Field(ge=1)
    has_attachments: bool
    importance: Literal["low", "normal", "high"]
    authentication_results: dict[str, str]
    reply_to_domain_mismatch: bool
    from_sender_mismatch: bool
    received_hops: int = Field(ge=0)
    sender_domain_hash: str
    recipient_domain_hash: str


class MailObservationV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    received_at: datetime
    authentication_results: dict[str, str | None]
    auth_integrity: float | None = Field(default=None, ge=0, le=1)
    auth_availability: Literal["available", "unavailable"]
    sender_context: float = Field(ge=0, le=1)
    external_sender: bool
    reply_to_domain_mismatch: bool
    from_sender_mismatch: bool
    received_hops: int = Field(ge=0)
    recipient_count: int = Field(ge=1)
    sender_domain_hash: str


class SignInObservationV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    created_at: datetime
    successful: bool
    is_interactive: bool
    country: str | None = None
    city: str | None = None
    network_hash: str | None = None
    device_hash: str | None = None
    app_hash: str | None = None
    is_managed: bool | None = None
    is_compliant: bool | None = None
    risk_level: Literal["none", "low", "medium", "high", "hidden", "unknown"] = "unknown"


class SecurityAlertObservationV1(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str | None = None
    created_at: datetime
    severity: Literal["informational", "low", "medium", "high", "unknown"]
    status: str
    source: str
    category: str | None = None
    device_hash: str | None = None


class UserFeatureWindowV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    window_end: datetime
    score: int | None = Field(default=None, ge=0, le=100)
    level: Literal["low", "medium", "high", "critical", "insufficient_data"]
    components: dict[str, float | None]
    features: dict[str, float | None]
    availability: dict[
        str, Literal["available", "unavailable", "insufficient_history"]
    ]
    evidence: dict[str, object]
    feature_version: str = "UserFeatureWindowV2"
    model_version: str = "shadow-rules-v2"
    calculated_at: datetime


class RiskGraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["employee", "observation", "feature", "component"]
    label: str
    status: Literal["available", "unavailable", "insufficient_history"] = "available"
    value: float | str | bool | None = None
    observed_at: datetime | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class RiskGraphEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    target: str
    relation: Literal["HAS_OBSERVATION", "DERIVES", "CONTRIBUTES_TO"]


class UserRiskGraphV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str
    feature_version: str
    model_version: str
    calculated_at: datetime
    score: int | None
    level: str
    components: dict[str, float | None]
    coverage: dict[str, Literal["available", "unavailable", "insufficient_history"]]
    nodes: list[RiskGraphNode]
    edges: list[RiskGraphEdge]


class ScannedFeatureRow(BaseModel):
    """Content-free, pseudonymous feature window for offline evaluation."""

    sample_id: str
    subject_key: str
    window_end: datetime
    feature_version: str
    model_version: str
    components: dict[str, float | None]
    features: dict[str, float | None]
    availability: dict[str, Literal["available", "unavailable", "insufficient_history"]]


class ScannedFeaturePage(BaseModel):
    items: list[ScannedFeatureRow]
    next_cursor: str | None = None
    source_category: Literal["generated", "real_unlabelled"]
    labelled: bool = False


class UserDailyFeaturesV1(BaseModel):
    tenant_id: uuid.UUID
    user_id: str
    day: date
    emails_received: int
    external_sender_ratio: float = Field(ge=0, le=1)
    suspicious_header_count: int = Field(ge=0)
    sender_domain_novelty: float = Field(ge=0, le=1)
    email_risk_mean: float
    email_risk_max: float
    behaviour_anomaly_score: float
    is_mfa_registered: bool
    is_mfa_capable: bool
    is_admin: bool
    entra_risk_level: Literal["none", "low", "medium", "high"]
    feature_version: str = "UserDailyFeaturesV1"


class RiskScoreV1(BaseModel):
    tenant_id: uuid.UUID
    user_id: str
    score: int = Field(ge=0, le=100)
    level: Literal["low", "medium", "high", "critical"]
    components: dict[str, float]
    model_version: str
    calculated_at: datetime


class AnalystFeedbackV1(BaseModel):
    tenant_id: uuid.UUID
    risk_id: uuid.UUID
    verdict: Literal["true_positive", "false_positive", "safe"]
    comment: str | None = Field(default=None, max_length=2000)
    actor: str
    created_at: datetime


class RiskFactorResponse(BaseModel):
    name: str
    contribution: float


class RiskScoreResponse(BaseModel):
    id: uuid.UUID
    user_id: str
    score: int
    level: str
    calculated_at: datetime
    model_version: str
    factors: list[RiskFactorResponse]
    recommended_actions: list[str]


class UserSummary(BaseModel):
    id: str
    display_name: str
    is_admin: bool
    is_mfa_registered: bool
    is_mfa_capable: bool
    entra_risk_level: str
    score: int = 0
    level: str = "low"
    calculated_at: datetime | None = None


class CursorPage(BaseModel):
    items: list[UserSummary]
    next_cursor: str | None = None


class RiskCursorPage(BaseModel):
    items: list[RiskScoreResponse]
    next_cursor: str | None = None


class DashboardSummary(BaseModel):
    users: int
    critical: int
    high: int
    medium: int
    low: int
    average_score: float
    last_sync_at: datetime | None


class FeedbackCreate(BaseModel):
    verdict: Literal["true_positive", "false_positive", "safe"]
    comment: str | None = Field(default=None, max_length=2000)


class SyncJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    attempt: int
    created_at: datetime
    completed_at: datetime | None
    next_attempt_at: datetime
    error: str | None


class SyncJobCursorPage(BaseModel):
    items: list[SyncJobResponse]
    next_cursor: str | None = None


class ModelResponse(BaseModel):
    version: str
    approved: bool
    feature_version: str
    metrics: dict[str, object]


class SimulationStatus(BaseModel):
    active: bool
    scenario: str
    paused: bool
    generated_messages: int
    target_user_id: str | None = None
    simulation_run_id: uuid.UUID | None = None


class SimulationRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: Literal[
        "credential-phishing",
        "domain-spoofing",
        "executive-impersonation",
        "account-takeover",
        "mfa-removal",
        "entra-escalation",
    ]
    target_user_id: str = Field(min_length=1, max_length=80)


class SimulationFlowStage(BaseModel):
    key: Literal["injected", "connector", "synchronized", "features", "scored", "alert"]
    label: str
    status: Literal["pending", "active", "done", "failed"]
    detail: str


class SimulationRunResponse(BaseModel):
    id: uuid.UUID
    scenario: str
    target_user_id: str
    target_display_name: str
    status: Literal["queued", "syncing", "evaluating", "detected", "missed", "reset"]
    detected: bool
    expected_signal: str
    baseline_score: int | None
    current_score: int | None
    score_delta: int | None
    components: dict[str, float | None]
    measurements: dict[str, int | float | bool | str | None]
    stages: list[SimulationFlowStage]
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class SimulationRunPage(BaseModel):
    items: list[SimulationRunResponse]


class MailEventResponse(BaseModel):
    """Privacy-safe header telemetry returned to the analyst dashboard."""

    model_config = ConfigDict(extra="forbid")

    id: str
    user_id: str
    received_at: datetime
    risk_probability: float = Field(ge=0, le=1)
    external_sender: bool
    recipient_count: int = Field(ge=1)
    has_attachments: bool
    importance: Literal["low", "normal", "high"]
    authentication_results: dict[str, str]
    reply_to_domain_mismatch: bool
    from_sender_mismatch: bool
    received_hops: int = Field(ge=0)
    sender_domain_hash: str


class MailEventPage(BaseModel):
    items: list[MailEventResponse]


class ConnectionResponse(BaseModel):
    mode: Literal["mock", "real"]
    status: str
    provider: str
    scopes: list[str]
    updated_at: datetime | None = None


class DatasetPreflightRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: list[str] = Field(min_length=1)
    dataset_kind: Literal["email", "identity"]
    source_category: Literal["imported", "generated", "real_labelled"]
    labelled: bool


class DatasetPreflightResponse(BaseModel):
    compatible: bool
    production_eligible: bool
    source_category: str
    present: list[str]
    missing: list[str]
    forbidden: list[str]
    warnings: list[str]
