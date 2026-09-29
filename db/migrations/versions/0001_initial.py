"""Initial tenant-isolated schema."""

from alembic import op

from services.api.app.models import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TENANT_TABLES = (
    "tenants",
    "connector_connections",
    "users",
    "sync_jobs",
    "email_features",
    "user_daily_features",
    "risk_scores",
    "risk_factors",
    "feedback",
    "model_versions",
    "audit_events",
)


def upgrade() -> None:
    bind = op.get_bind()
    # Freeze revision 0001 to its historical table set. Without ``tables=`` a fresh
    # install would also create models introduced by future revisions.
    Base.metadata.create_all(bind, tables=[Base.metadata.tables[name] for name in TENANT_TABLES])
    for table in TENANT_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        column = "id" if table == "tenants" else "tenant_id"
        op.execute(
            f'''CREATE POLICY tenant_isolation ON "{table}"
                USING ({column} = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
                WITH CHECK ({column} = NULLIF(current_setting('app.tenant_id', true), '')::uuid)'''
        )
        op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{table}" TO m365risk')


def downgrade() -> None:
    Base.metadata.drop_all(
        op.get_bind(), tables=[Base.metadata.tables[name] for name in reversed(TENANT_TABLES)]
    )
