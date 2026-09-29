"""Add target-specific simulator run telemetry."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "simulation_runs",
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("target_user_id", sa.String(length=80), nullable=False),
        sa.Column("scenario", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="queued"),
        sa.Column("baseline_score", sa.Integer()),
        sa.Column("current_score", sa.Integer()),
        sa.Column("detected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["tenant_id", "target_user_id"],
            ["users.tenant_id", "users.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_simulation_runs_tenant_created",
        "simulation_runs",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "ix_simulation_runs_tenant_target_created",
        "simulation_runs",
        ["tenant_id", "target_user_id", "created_at"],
    )
    op.execute('ALTER TABLE "simulation_runs" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "simulation_runs" FORCE ROW LEVEL SECURITY')
    op.execute(
        '''CREATE POLICY tenant_isolation ON "simulation_runs"
           USING (tenant_id = require_tenant_context())
           WITH CHECK (tenant_id = require_tenant_context())'''
    )
    op.execute('GRANT SELECT, INSERT, UPDATE, DELETE ON "simulation_runs" TO m365risk')


def downgrade() -> None:
    op.drop_table("simulation_runs")
