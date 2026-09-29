"""Add the tenant-first index used by the live mail telemetry feed."""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_email_features_tenant_received_id",
        "email_features",
        ["tenant_id", "received_at", "id"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_email_features_tenant_received_id",
        table_name="email_features",
        if_exists=True,
    )
