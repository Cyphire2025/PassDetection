from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.domain.entities.entities import UserRole
from app.presentation.api.v1.routes.whatsapp_activity import (
    _activity_statement,
    get_whatsapp_activity_failures,
    get_whatsapp_activity_summary,
    router,
)
from app.presentation.api.v1.schemas.whatsapp_activity_schemas import (
    WhatsAppActivityFailureResponse,
    WhatsAppActivitySummaryResponse,
)


def _user(role: UserRole, *, agency_id: uuid.UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), role=role, agency_id=agency_id)


def test_activity_routes_have_compact_role_gated_contracts() -> None:
    summary_route = next(
        route for route in router.routes if route.path == "/activities/{kind}/{batch_id}"
    )
    failures_route = next(
        route for route in router.routes if route.path == "/activities/{kind}/{batch_id}/failures"
    )

    assert summary_route.methods == {"GET"}
    assert summary_route.response_model is WhatsAppActivitySummaryResponse
    assert failures_route.methods == {"GET"}
    assert failures_route.response_model == list[WhatsAppActivityFailureResponse]
    assert [dependency.call.__name__ for dependency in summary_route.dependant.dependencies] == [
        "_check_role",
        "get_db_session",
    ]


@pytest.mark.parametrize("kind", ["broadcast", "document", "qr"])
def test_activity_summary_queries_are_aggregated_and_tenant_scoped(kind: str) -> None:
    batch_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    statement = _activity_statement(
        kind=kind,  # type: ignore[arg-type]
        batch_id=batch_id,
        current_user=_user(UserRole.AGENCY_ADMIN, agency_id=agency_id),
        stale_cutoff=datetime.now(tz=UTC) - timedelta(minutes=30),
    )

    compiled = statement.compile()
    sql = str(compiled).lower()
    parameters = list(compiled.params.values())
    assert "count(" in sql
    assert "filter (where" in sql
    assert "group by" in sql
    assert batch_id in parameters
    assert agency_id in parameters
    if kind == "broadcast":
        assert "whatsapp_broadcast_groups.agency_id" in sql
        assert "whatsapp_broadcast_recipients" not in sql
    else:
        assert "client_groups.agency_id" in sql


def test_document_activity_query_keeps_staff_group_visibility_scope() -> None:
    user = _user(UserRole.AGENCY_STAFF, agency_id=uuid.uuid4())
    statement = _activity_statement(
        kind="document",
        batch_id=uuid.uuid4(),
        current_user=user,
        stale_cutoff=datetime.now(tz=UTC) - timedelta(minutes=30),
    )

    sql = str(statement.compile()).lower()
    assert "client_groups.created_by_user_id" in sql
    assert "manager_group_access" in sql


@pytest.mark.asyncio
async def test_activity_summary_returns_document_context_and_live_counts() -> None:
    batch_id = uuid.uuid4()
    group_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    aggregate_result = MagicMock()
    aggregate_result.one_or_none.return_value = SimpleNamespace(
        activity_id=batch_id,
        source_group_id=group_id,
        context_label="Vietnam 2026",
        activity_label="flight_ticket_domestic",
        total=700,
        queued=645,
        sent=50,
        failed=5,
        delivery_unknown=0,
        started_at=now,
        updated_at=now,
    )
    session = MagicMock()
    session.execute = AsyncMock(return_value=aggregate_result)

    response = await get_whatsapp_activity_summary(
        kind="document",
        batch_id=batch_id,
        current_user=_user(UserRole.AGENCY_ADMIN, agency_id=uuid.uuid4()),
        session=session,
    )

    assert response == WhatsAppActivitySummaryResponse(
        activity_id=batch_id,
        kind="document",
        title="Domestic Onward Flight Ticket broadcast",
        context_label="Vietnam 2026",
        source_group_id=group_id,
        document_type="flight_ticket_domestic",
        total=700,
        queued=645,
        sent=50,
        failed=5,
        delivery_unknown=0,
        started_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_staff_cannot_probe_main_broadcast_activity() -> None:
    session = MagicMock()
    session.execute = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await get_whatsapp_activity_summary(
            kind="broadcast",
            batch_id=uuid.uuid4(),
            current_user=_user(UserRole.AGENCY_STAFF, agency_id=uuid.uuid4()),
            session=session,
        )

    assert exc_info.value.status_code == 404
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_failure_details_return_names_and_safe_phone_fallback() -> None:
    failed_result = MagicMock()
    failed_result.all.return_value = [
        SimpleNamespace(
            recipient_name="Passenger One",
            phone_number="+919999999999",
            error_message="Provider rejected the destination",
        ),
        SimpleNamespace(
            recipient_name=None,
            phone_number="+918888888888",
            error_message=None,
        ),
    ]
    session = MagicMock()
    session.execute = AsyncMock(return_value=failed_result)

    response = await get_whatsapp_activity_failures(
        kind="qr",
        batch_id=uuid.uuid4(),
        current_user=_user(UserRole.AGENCY_ADMIN, agency_id=uuid.uuid4()),
        session=session,
    )

    assert response == [
        WhatsAppActivityFailureResponse(
            recipient_name="Passenger One",
            phone_number="+919999999999",
            error_message="Provider rejected the destination",
        ),
        WhatsAppActivityFailureResponse(
            recipient_name="+918888888888",
            phone_number="+918888888888",
            error_message=None,
        ),
    ]
