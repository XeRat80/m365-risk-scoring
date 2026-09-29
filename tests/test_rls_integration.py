from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import exc, text
from sqlalchemy.ext.asyncio import create_async_engine

from services.api.app.database import async_url

TENANT_A = "00000000-0000-4000-8000-000000000001"
TENANT_B = "00000000-0000-4000-8000-000000000002"
BUSINESS_TABLES = {
    "tenants",
    "connector_connections",
    "users",
    "sync_jobs",
    "email_features",
    "sign_in_observations",
    "security_alert_observations",
    "user_daily_features",
    "user_feature_windows_v2",
    "risk_scores",
    "risk_factors",
    "feedback",
    "model_versions",
    "audit_events",
}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_forced_rls_hides_other_tenant_from_application_role() -> None:
    url = async_url(os.getenv("DATABASE_URL", "postgresql://m365risk:m365risk@localhost:5432/m365risk"))
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(text("select set_config('app.tenant_id', :tenant, true)"), {"tenant": TENANT_A})
            visible = (await connection.execute(text("select id::text from tenants order by id"))).scalars().all()
            assert visible == [TENANT_A]
            cross_tenant = await connection.scalar(
                text("select count(*) from users where tenant_id=:tenant"), {"tenant": TENANT_B}
            )
            assert cross_tenant == 0
            await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_every_business_table_has_forced_rls_and_requires_context() -> None:
    url = async_url(
        os.getenv("DATABASE_URL", "postgresql://m365risk:m365risk@localhost:5432/m365risk")
    )
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            policies = (
                await connection.execute(
                    text(
                        """SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
                                  count(p.polname) AS policies
                           FROM pg_class c
                           JOIN pg_namespace n ON n.oid = c.relnamespace
                           LEFT JOIN pg_policy p ON p.polrelid = c.oid
                           WHERE n.nspname = 'public'
                             AND c.relname = ANY(:tables)
                           GROUP BY c.relname, c.relrowsecurity, c.relforcerowsecurity"""
                    ),
                    {"tables": sorted(BUSINESS_TABLES)},
                )
            ).all()
            assert {row.relname for row in policies} == BUSINESS_TABLES
            assert all(row.relrowsecurity and row.relforcerowsecurity for row in policies)
            assert all(row.policies >= 1 for row in policies)
        for table in sorted(BUSINESS_TABLES):
            async with engine.connect() as connection:
                query = text(
                    f'SELECT count(*) FROM "{table}"'  # noqa: S608 - allowlisted names
                )
                with pytest.raises(exc.DBAPIError) as denied:
                    await connection.scalar(query)
                assert "verified tenant context is required" in str(denied.value)
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rls_and_composite_foreign_keys_block_cross_tenant_writes() -> None:
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    admin_url = async_url(
        os.getenv(
            "DATABASE_ADMIN_URL", "postgresql://postgres:postgres@localhost:5432/m365risk"
        )
    )
    app_url = async_url(
        os.getenv("DATABASE_URL", "postgresql://m365risk:m365risk@localhost:5432/m365risk")
    )
    admin = create_async_engine(admin_url)
    app = create_async_engine(app_url)
    try:
        async with admin.begin() as connection:
            await connection.execute(
                text("INSERT INTO tenants(id, name) VALUES (:a, 'RLS A'), (:b, 'RLS B')"),
                {"a": tenant_a, "b": tenant_b},
            )
            await connection.execute(
                text(
                    """INSERT INTO users(tenant_id,id,display_name,principal_hash,is_admin,
                                         is_mfa_registered,is_mfa_capable,entra_risk_level)
                       VALUES (:tenant,'only-in-b','Only B','hash',false,true,true,'none')"""
                ),
                {"tenant": tenant_b},
            )
        async with app.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(
                text("select set_config('app.tenant_id', :tenant, true)"),
                {"tenant": str(tenant_a)},
            )
            with pytest.raises(exc.DBAPIError):
                await connection.execute(
                    text(
                        """INSERT INTO email_features
                           (tenant_id,id,user_id,received_at,risk_probability,features)
                           VALUES (:tenant,'cross-reference','only-in-b',now(),0.5,'{}')"""
                    ),
                    {"tenant": tenant_a},
                )
            await transaction.rollback()
        async with app.connect() as connection:
            transaction = await connection.begin()
            await connection.execute(
                text("select set_config('app.tenant_id', :tenant, true)"),
                {"tenant": str(tenant_a)},
            )
            with pytest.raises(exc.DBAPIError):
                await connection.execute(
                    text(
                        """INSERT INTO users
                           (tenant_id,id,display_name,principal_hash,is_admin,is_mfa_registered,
                            is_mfa_capable,entra_risk_level)
                           VALUES (:tenant,'wrong-tenant','Wrong','hash',false,true,true,'none')"""
                    ),
                    {"tenant": tenant_b},
                )
            await transaction.rollback()
    finally:
        async with admin.begin() as connection:
            await connection.execute(
                text("DELETE FROM tenants WHERE id IN (:a, :b)"),
                {"a": tenant_a, "b": tenant_b},
            )
        await app.dispose()
        await admin.dispose()
