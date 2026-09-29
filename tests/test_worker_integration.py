from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from services.api.app.auth import Principal
from services.api.app.database import AdminSessionLocal, tenant_session
from services.api.app.main import start_sync
from services.worker.app.main import claim_job, complete_job, ensure_jobs


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="module")
async def test_queue_claims_skip_running_tenant_and_schedule_retry() -> None:
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    job_a1 = uuid.uuid4()
    job_a2 = uuid.uuid4()
    job_b = uuid.uuid4()
    async with AdminSessionLocal() as session, session.begin():
        await session.execute(
            text("INSERT INTO tenants(id,name) VALUES (:a,'Queue A'),(:b,'Queue B')"),
            {"a": tenant_a, "b": tenant_b},
        )
        await session.execute(
            text(
                """INSERT INTO sync_jobs
                   (tenant_id,id,status,attempt,checkpoint,created_at,next_attempt_at)
                   VALUES
                   (:a,:a1,'queued',0,'{}','2000-01-01T00:00:00Z',now()),
                   (:a,:a2,'queued',0,'{}','2000-01-01T00:00:01Z',now()),
                   (:b,:b1,'queued',0,'{}','2000-01-01T00:00:02Z',now())"""
            ),
            {"a": tenant_a, "b": tenant_b, "a1": job_a1, "a2": job_a2, "b1": job_b},
        )
    try:
        first = await claim_job()
        second = await claim_job()
        assert first is not None and second is not None
        assert first[:2] == (tenant_a, job_a1)
        assert second[:2] == (tenant_b, job_b)
        await complete_job(tenant_a, job_a1, {"cursor": "safe"}, "transient failure")
        async with AdminSessionLocal() as session:
            row = (
                await session.execute(
                    text(
                        """SELECT status,attempt,next_attempt_at > now() AS delayed,error,checkpoint
                           FROM sync_jobs WHERE tenant_id=:tenant AND id=:job"""
                    ),
                    {"tenant": tenant_a, "job": job_a1},
                )
            ).one()
            assert row.status == "retrying"
            assert row.attempt == 1
            assert row.delayed is True
            assert row.error == "transient failure"
            assert row.checkpoint == {"cursor": "safe"}
    finally:
        async with AdminSessionLocal() as session, session.begin():
            await session.execute(
                text("DELETE FROM tenants WHERE id IN (:a,:b)"),
                {"a": tenant_a, "b": tenant_b},
            )


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="module")
async def test_timed_out_job_is_recovered_and_duplicate_start_is_idempotent() -> None:
    tenant_id = uuid.UUID("00000000-0000-4000-8000-000000000001")
    stale_job = uuid.uuid4()
    idempotency_key = f"integration-{uuid.uuid4()}"
    async with AdminSessionLocal() as session, session.begin():
        await session.execute(
            text(
                """INSERT INTO sync_jobs
                   (tenant_id,id,status,attempt,checkpoint,created_at,started_at,next_attempt_at)
                   VALUES (:tenant,:job,'running',1,'{}',now(),:started,now())"""
            ),
            {
                "tenant": tenant_id,
                "job": stale_job,
                "started": datetime.now(UTC) - timedelta(minutes=2),
            },
        )
    try:
        await ensure_jobs()
        async with AdminSessionLocal() as session:
            recovered = (
                await session.execute(
                    text(
                        "SELECT status,error FROM sync_jobs "
                        "WHERE tenant_id=:tenant AND id=:job"
                    ),
                    {"tenant": tenant_id, "job": stale_job},
                )
            ).one()
            assert recovered.status == "queued"
            assert recovered.error == "Recovered after worker timeout"

        principal = Principal(tenant_id=tenant_id, subject="integration", role="admin")
        async for session in tenant_session(tenant_id):
            first = await start_sync(idempotency_key, principal, session)
            second = await start_sync(idempotency_key, principal, session)
            assert first.id == second.id
    finally:
        async with AdminSessionLocal() as session, session.begin():
            await session.execute(
                text(
                    "DELETE FROM sync_jobs WHERE tenant_id=:tenant "
                    "AND (id=:job OR checkpoint->>'idempotency_key'=:key)"
                ),
                {"tenant": tenant_id, "job": stale_job, "key": idempotency_key},
            )
