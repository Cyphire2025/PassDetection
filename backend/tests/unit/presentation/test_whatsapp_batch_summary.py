from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.domain.entities.entities import UserRole
from app.presentation.api.v1.routes.whatsapp import (
    WhatsAppBatchSummaryResponse,
    _broadcast_batch_summary_statement,
    get_broadcast_batch_summary,
)
from app.presentation.api.v1.routes.whatsapp import (
    router as whatsapp_router,
)


def test_batch_summary_route_is_role_gated_and_has_compact_contract() -> None:
    route = next(
        item for item in whatsapp_router.routes if item.path == "/batches/{batch_id}/summary"
    )

    assert route.methods == {"GET"}
    assert route.response_model is WhatsAppBatchSummaryResponse
    assert set(WhatsAppBatchSummaryResponse.model_fields) == {
        "batch_id",
        "queued",
        "sent",
        "failed",
        "delivery_unknown",
    }
    assert [dependency.call.__name__ for dependency in route.dependant.dependencies] == [
        "_check_role",
        "get_db_session",
    ]


def test_batch_summary_query_is_tenant_scoped_and_does_not_load_recipients() -> None:
    batch_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    cutoff = datetime.now(tz=UTC) - timedelta(minutes=30)
    statement = _broadcast_batch_summary_statement(
        batch_id=batch_id,
        current_user=SimpleNamespace(role=UserRole.AGENCY_ADMIN, agency_id=agency_id),
        stale_cutoff=cutoff,
    )

    compiled = statement.compile()
    sql = str(compiled).lower()
    parameters = list(compiled.params.values())
    assert "count(" in sql
    assert "filter (where" in sql
    assert "join whatsapp_broadcast_groups" in sql
    assert "whatsapp_broadcast_groups.agency_id" in sql
    assert "whatsapp_broadcast_recipients" not in sql
    assert "phone_number" not in sql
    assert batch_id in parameters
    assert agency_id in parameters
    assert cutoff in parameters


@pytest.mark.asyncio
async def test_batch_summary_endpoint_returns_aggregate_counts() -> None:
    batch_id = uuid.uuid4()
    aggregate_result = MagicMock()
    aggregate_result.one.return_value = SimpleNamespace(
        total=1_500,
        queued=700,
        sent=750,
        failed=25,
        delivery_unknown=25,
    )
    session = MagicMock()
    session.execute = AsyncMock(return_value=aggregate_result)

    response = await get_broadcast_batch_summary(
        batch_id=batch_id,
        current_user=SimpleNamespace(role=UserRole.SUPER_ADMIN, agency_id=None),
        session=session,
    )

    assert response == WhatsAppBatchSummaryResponse(
        batch_id=batch_id,
        queued=700,
        sent=750,
        failed=25,
        delivery_unknown=25,
    )
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_batch_summary_endpoint_hides_missing_or_inaccessible_batch() -> None:
    aggregate_result = MagicMock()
    aggregate_result.one.return_value = SimpleNamespace(
        total=0,
        queued=0,
        sent=0,
        failed=0,
        delivery_unknown=0,
    )
    session = MagicMock()
    session.execute = AsyncMock(return_value=aggregate_result)

    with pytest.raises(HTTPException) as exc_info:
        await get_broadcast_batch_summary(
            batch_id=uuid.uuid4(),
            current_user=SimpleNamespace(
                role=UserRole.AGENCY_ADMIN,
                agency_id=uuid.uuid4(),
            ),
            session=session,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "WhatsApp broadcast batch not found"
