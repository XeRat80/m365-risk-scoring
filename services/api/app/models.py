from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    connector_status: Mapped[str] = mapped_column(
        String(32), default="connected", server_default="connected"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class ConnectorConnection(Base):
    __tablename__ = "connector_connections"
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(32), default="microsoft_graph")
    client_id: Mapped[str] = mapped_column(String(80))
    encrypted_client_secret: Mapped[str] = mapped_column(Text)
    consent_status: Mapped[str] = mapped_column(String(24), default="pending")
    scopes: Mapped[list[str]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (Index("ix_connector_connections_tenant_status", "tenant_id", "consent_status"),)


class User(Base):
    __tablename__ = "users"
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(160))
    principal_hash: Mapped[str] = mapped_column(String(96))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_mfa_registered: Mapped[bool] = mapped_column(Boolean, default=True)
    is_mfa_capable: Mapped[bool] = mapped_column(Boolean, default=True)
    entra_risk_level: Mapped[str] = mapped_column(String(16), default="none")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_users_tenant_risk", "tenant_id", "entra_risk_level"),)


class SyncJob(Base):
    __tablename__ = "sync_jobs"
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(24), default="queued")
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    checkpoint: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (Index("ix_sync_jobs_tenant_status_created", "tenant_id", "status", "created_at"),)


class SimulationRun(Base):
    """A target-specific validation run kept outside the shipped product UI."""

    __tablename__ = "simulation_runs"
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    target_user_id: Mapped[str] = mapped_column(String(80))
    scenario: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="queued")
    baseline_score: Mapped[int | None] = mapped_column(Integer)
    current_score: Mapped[int | None] = mapped_column(Integer)
    detected: Mapped[bool] = mapped_column(Boolean, default=False)
    details: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "target_user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="CASCADE",
        ),
        Index("ix_simulation_runs_tenant_created", "tenant_id", "created_at"),
        Index(
            "ix_simulation_runs_tenant_target_created",
            "tenant_id",
            "target_user_id",
            "created_at",
        ),
    )


class EmailFeature(Base):
    __tablename__ = "email_features"
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(80))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    risk_probability: Mapped[float] = mapped_column(Float)
    features: Mapped[dict[str, object]] = mapped_column(JSONB)
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], ondelete="CASCADE"
        ),
        Index("ix_email_features_tenant_user_received", "tenant_id", "user_id", "received_at"),
        Index("ix_email_features_tenant_received_id", "tenant_id", "received_at", "id"),
    )


class SignInObservation(Base):
    __tablename__ = "sign_in_observations"
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    successful: Mapped[bool] = mapped_column(Boolean)
    is_interactive: Mapped[bool] = mapped_column(Boolean, default=True)
    country: Mapped[str | None] = mapped_column(String(8))
    city: Mapped[str | None] = mapped_column(String(96))
    network_hash: Mapped[str | None] = mapped_column(String(96))
    device_hash: Mapped[str | None] = mapped_column(String(96))
    app_hash: Mapped[str | None] = mapped_column(String(96))
    is_managed: Mapped[bool | None] = mapped_column(Boolean)
    is_compliant: Mapped[bool | None] = mapped_column(Boolean)
    features: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], ondelete="CASCADE"
        ),
        Index("ix_sign_ins_tenant_user_created", "tenant_id", "user_id", "created_at"),
        Index("ix_sign_ins_tenant_created", "tenant_id", "created_at"),
    )


class SecurityAlertObservation(Base):
    __tablename__ = "security_alert_observations"
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    severity: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(80))
    category: Mapped[str | None] = mapped_column(String(100))
    device_hash: Mapped[str | None] = mapped_column(String(96))
    details: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], ondelete="CASCADE"
        ),
        Index("ix_security_alerts_tenant_user_created", "tenant_id", "user_id", "created_at"),
        Index("ix_security_alerts_tenant_created", "tenant_id", "created_at"),
    )


class UserDailyFeature(Base):
    __tablename__ = "user_daily_features"
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    email_risk_mean: Mapped[float] = mapped_column(Float)
    email_risk_max: Mapped[float] = mapped_column(Float)
    behaviour_anomaly_score: Mapped[float] = mapped_column(Float)
    emails_received: Mapped[int] = mapped_column(Integer)
    external_sender_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    suspicious_header_count: Mapped[int] = mapped_column(Integer, default=0)
    sender_domain_novelty: Mapped[float] = mapped_column(Float, default=0.0)
    feature_version: Mapped[str] = mapped_column(String(40), default="UserDailyFeaturesV1")
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], ondelete="CASCADE"
        ),
        Index("ix_user_daily_tenant_user_day", "tenant_id", "user_id", "day"),
    )


class UserFeatureWindow(Base):
    __tablename__ = "user_feature_windows_v2"
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    score: Mapped[int | None] = mapped_column(Integer)
    level: Mapped[str] = mapped_column(String(24), default="insufficient_data")
    components: Mapped[dict[str, object]] = mapped_column(JSONB)
    features: Mapped[dict[str, object]] = mapped_column(JSONB)
    availability: Mapped[dict[str, str]] = mapped_column(JSONB)
    evidence: Mapped[dict[str, object]] = mapped_column(JSONB)
    feature_version: Mapped[str] = mapped_column(String(40), default="UserFeatureWindowV2")
    model_version: Mapped[str] = mapped_column(String(40), default="shadow-rules-v2")
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], ondelete="CASCADE"
        ),
        Index("ix_feature_windows_tenant_user_end", "tenant_id", "user_id", "window_end"),
    )


class RiskScore(Base):
    __tablename__ = "risk_scores"
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(80))
    score: Mapped[int] = mapped_column(Integer)
    level: Mapped[str] = mapped_column(String(16))
    components: Mapped[dict[str, float]] = mapped_column(JSONB)
    model_version: Mapped[str] = mapped_column(String(40), default="demo-0.1.0")
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    factors: Mapped[list[RiskFactor]] = relationship(back_populates="risk", cascade="all, delete-orphan")
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], ondelete="CASCADE"
        ),
        Index("ix_risk_scores_tenant_user_calculated", "tenant_id", "user_id", "calculated_at"),
    )


class RiskFactor(Base):
    __tablename__ = "risk_factors"
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    risk_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(200))
    contribution: Mapped[float] = mapped_column(Float)
    risk: Mapped[RiskScore] = relationship(back_populates="factors")
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "risk_id"],
            ["risk_scores.tenant_id", "risk_scores.id"],
            ondelete="CASCADE",
        ),
        Index("ix_risk_factors_tenant_risk", "tenant_id", "risk_id"),
    )


class Feedback(Base):
    __tablename__ = "feedback"
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    risk_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    verdict: Mapped[str] = mapped_column(String(32))
    comment: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "risk_id"],
            ["risk_scores.tenant_id", "risk_scores.id"],
            ondelete="CASCADE",
        ),
        Index("ix_feedback_tenant_risk_created", "tenant_id", "risk_id", "created_at"),
    )


class ModelVersion(Base):
    __tablename__ = "model_versions"
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    version: Mapped[str] = mapped_column(String(40), primary_key=True)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    feature_version: Mapped[str] = mapped_column(String(40), default="EmailMetadataV1")
    metrics: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100))
    details: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
