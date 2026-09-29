"""Reject application queries that do not establish verified tenant context."""

from alembic import op

revision = "0004"
down_revision = "0003"
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
    op.execute(
        """
        CREATE OR REPLACE FUNCTION require_tenant_context()
        RETURNS uuid
        LANGUAGE plpgsql
        STABLE
        AS $$
        DECLARE
            configured text := current_setting('app.tenant_id', true);
        BEGIN
            IF configured IS NULL OR configured = '' THEN
                RAISE EXCEPTION 'verified tenant context is required'
                    USING ERRCODE = '42501';
            END IF;
            RETURN configured::uuid;
        EXCEPTION
            WHEN invalid_text_representation THEN
                RAISE EXCEPTION 'verified tenant context is invalid'
                    USING ERRCODE = '42501';
        END;
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION require_tenant_context() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION require_tenant_context() TO m365risk")
    for table in TENANT_TABLES:
        column = "id" if table == "tenants" else "tenant_id"
        op.execute(f'DROP POLICY tenant_isolation ON "{table}"')
        op.execute(
            f'''CREATE POLICY tenant_isolation ON "{table}"
                USING ({column} = require_tenant_context())
                WITH CHECK ({column} = require_tenant_context())'''
        )


def downgrade() -> None:
    for table in TENANT_TABLES:
        column = "id" if table == "tenants" else "tenant_id"
        op.execute(f'DROP POLICY tenant_isolation ON "{table}"')
        op.execute(
            f'''CREATE POLICY tenant_isolation ON "{table}"
                USING ({column} = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
                WITH CHECK ({column} = NULLIF(current_setting('app.tenant_id', true), '')::uuid)'''
        )
    op.execute("DROP FUNCTION require_tenant_context()")
