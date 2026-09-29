"""Add normalized V2 observations and canonical feature windows."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

NEW_TABLES = (
    "sign_in_observations",
    "security_alert_observations",
    "user_feature_windows_v2",
)


def _tenant_columns() -> tuple[sa.Column[object], sa.Column[object]]:
    return (
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("user_id", sa.String(length=80), nullable=False),
    )


def upgrade() -> None:
    tenant_id, user_id = _tenant_columns()
    op.create_table(
        "sign_in_observations",
        tenant_id,
        sa.Column("id", sa.String(length=100), primary_key=True),
        user_id,
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("successful", sa.Boolean(), nullable=False),
        sa.Column("is_interactive", sa.Boolean(), nullable=False),
        sa.Column("country", sa.String(length=8)),
        sa.Column("city", sa.String(length=96)),
        sa.Column("network_hash", sa.String(length=96)),
        sa.Column("device_hash", sa.String(length=96)),
        sa.Column("app_hash", sa.String(length=96)),
        sa.Column("is_managed", sa.Boolean()),
        sa.Column("is_compliant", sa.Boolean()),
        sa.Column("features", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_sign_ins_tenant_user_created",
        "sign_in_observations",
        ["tenant_id", "user_id", "created_at"],
    )
    op.create_index(
        "ix_sign_ins_tenant_created",
        "sign_in_observations",
        ["tenant_id", "created_at"],
    )

    tenant_id, _ = _tenant_columns()
    op.create_table(
        "security_alert_observations",
        tenant_id,
        sa.Column("id", sa.String(length=100), primary_key=True),
        sa.Column("user_id", sa.String(length=80)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("severity", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("category", sa.String(length=100)),
        sa.Column("device_hash", sa.String(length=96)),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_security_alerts_tenant_user_created",
        "security_alert_observations",
        ["tenant_id", "user_id", "created_at"],
    )
    op.create_index(
        "ix_security_alerts_tenant_created",
        "security_alert_observations",
        ["tenant_id", "created_at"],
    )

    tenant_id, _ = _tenant_columns()
    op.create_table(
        "user_feature_windows_v2",
        tenant_id,
        sa.Column("user_id", sa.String(length=80), nullable=False, primary_key=True),
        sa.Column("window_end", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("score", sa.Integer()),
        sa.Column("level", sa.String(length=24), nullable=False),
        sa.Column("components", postgresql.JSONB(), nullable=False),
        sa.Column("features", postgresql.JSONB(), nullable=False),
        sa.Column("availability", postgresql.JSONB(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.Column("feature_version", sa.String(length=40), nullable=False),
        sa.Column("model_version", sa.String(length=40), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_feature_windows_tenant_user_end",
        "user_feature_windows_v2",
        ["tenant_id", "user_id", "window_end"],
    )

    for table in NEW_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'''CREATE POLICY tenant_isolation ON "{table}"
                USING (tenant_id = require_tenant_context())
                WITH CHECK (tenant_id = require_tenant_context())'''
        )
        op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{table}" TO m365risk')


def downgrade() -> None:
    for table in reversed(NEW_TABLES):
        op.drop_table(table)
