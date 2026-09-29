"""Make tenant creation safe for administrative SQL clients."""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenants ALTER COLUMN connector_status SET DEFAULT 'connected'")
    op.execute("ALTER TABLE tenants ALTER COLUMN created_at SET DEFAULT now()")


def downgrade() -> None:
    op.execute("ALTER TABLE tenants ALTER COLUMN created_at DROP DEFAULT")
    op.execute("ALTER TABLE tenants ALTER COLUMN connector_status DROP DEFAULT")
