import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from services.api.app.auth import Principal
from services.api.app.main import close_alert
from services.api.app.models import SecurityAlertObservation
from services.api.app.schemas import AlertCloseRequest


@pytest.mark.asyncio
async def test_closure_is_audited_idempotent_and_preserves_provider_state() -> None:
    tenant = uuid.uuid4()
    alert = SecurityAlertObservation(
        tenant_id=tenant, id="alert-1", user_id="user-1", severity="high",
        status="new", source="defender", created_at=datetime.now(UTC), details={},
    )
    db = MagicMock()
    db.scalar = AsyncMock(return_value=alert)
    principal = Principal(tenant, "analyst-1", "analyst")
    result = await close_alert("alert-1", AlertCloseRequest(reason="resolved"), principal, db)
    assert result.soc_status == "closed"
    assert result.provider_status == "new"
    assert result.closure is not None
    assert result.closure["actor"] == "analyst-1"
    assert db.add.call_count == 1
    query = db.scalar.await_args.args[0]
    assert tenant in query.compile().params.values()
    assert "FOR UPDATE" in str(query)
    again = await close_alert("alert-1", AlertCloseRequest(reason="false_positive"), principal, db)
    assert again.closure == result.closure
    assert db.add.call_count == 1


@pytest.mark.asyncio
async def test_absent_or_other_tenant_alert_cannot_be_closed() -> None:
    db = MagicMock()
    db.scalar = AsyncMock(return_value=None)
    with pytest.raises(HTTPException) as error:
        await close_alert("other", AlertCloseRequest(reason="resolved"),
                          Principal(uuid.uuid4(), "analyst", "analyst"), db)
    assert error.value.status_code == 404
    db.add.assert_not_called()
