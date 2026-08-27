from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, Request
from fastapi.routing import APIRoute
from pydantic import ValidationError

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import AttendanceScanBatchResultModel
from app.presentation.api.v1.routes import tour_operations
from app.presentation.api.v1.routes import (
    tour_operations_attendance_batch_support as batch_support,
)
from app.presentation.api.v1.routes.tour_operations_attendance_batch_support import (
    AttendanceBatchDependencies,
)
from app.presentation.api.v1.schemas import tour_operations_schemas as schemas
from app.presentation.api.v1.schemas.tour_operations_schemas import (
    AttendanceScanBatchItemRequest,
    AttendanceScanBatchItemResponse,
    AttendanceScanBatchRequest,
    AttendanceScanResponse,
)

_QR_PAYLOAD = f"pdatt:{'A' * 43}"
_SCANNED_AT = datetime(2026, 8, 25, 9, 30, tzinfo=UTC)


def _item(client_event_id: str) -> AttendanceScanBatchItemRequest:
    return AttendanceScanBatchItemRequest(
        client_event_id=client_event_id,
        qr_payload=_QR_PAYLOAD,
        scanned_at=_SCANNED_AT,
    )


def _request(*event_ids: str) -> AttendanceScanBatchRequest:
    return AttendanceScanBatchRequest(
        batch_id=uuid.uuid4(),
        scans=[_item(event_id) for event_id in event_ids],
    )


def _coordinator(agency_id: uuid.UUID) -> User:
    return User(
        id=uuid.uuid4(),
        email="coordinator@example.test",
        hashed_password="hash",
        full_name="Coordinator",
        role=UserRole.AGENCY_COORDINATOR,
        agency_id=agency_id,
    )


def test_batch_contract_rejects_duplicates_naive_timestamps_and_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="unique within a batch"):
        _request("scan-event-0001", "scan-event-0001")

    with pytest.raises(ValidationError, match="timezone"):
        AttendanceScanBatchItemRequest(
            client_event_id="scan-event-0002",
            qr_payload=_QR_PAYLOAD,
            scanned_at=datetime(2026, 8, 25, 9, 30),
        )

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AttendanceScanBatchRequest.model_validate(
            {
                "batch_id": str(uuid.uuid4()),
                "scans": [
                    {
                        "client_event_id": "scan-event-0003",
                        "qr_payload": _QR_PAYLOAD,
                        "scanned_at": _SCANNED_AT.isoformat(),
                        "device_secret": "must-not-be-accepted",
                    }
                ],
            }
        )


def test_batch_contract_enforces_item_and_aggregate_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValidationError, match="at most 50"):
        _request(*(f"scan-event-{index:04d}" for index in range(51)))

    monkeypatch.setattr(schemas, "ATTENDANCE_SCAN_BATCH_MAX_AGGREGATE_BYTES", 64)
    with pytest.raises(ValidationError, match="aggregate byte limit"):
        _request("scan-event-aggregate-limit")


def test_batch_result_requires_exactly_one_payload_shape() -> None:
    with pytest.raises(ValidationError, match="exactly one"):
        AttendanceScanBatchItemResponse(
            client_event_id="scan-event-0004",
            outcome="rejected",
            retryable=False,
        )
    with pytest.raises(ValidationError, match="exactly one"):
        AttendanceScanBatchItemResponse(
            client_event_id="scan-event-0004",
            outcome="rejected",
            retryable=False,
            error_code="ATTENDANCE_QR_INVALID",
            scan=AttendanceScanResponse(
                session_id=uuid.uuid4(),
                status="invalid",
                message="invalid",
                scanned_count=0,
                assigned_count=1,
            ),
        )


def test_batch_fingerprints_are_deterministic_and_never_retain_raw_qr() -> None:
    item = _item("scan-event-0005")
    first = batch_support._item_fingerprint(item)  # noqa: SLF001
    second = batch_support._item_fingerprint(item)  # noqa: SLF001

    assert first == second
    assert len(first) == 64
    assert _QR_PAYLOAD not in first
    assert "qr_payload" not in AttendanceScanBatchResultModel.__table__.columns


def test_batch_error_mapping_preserves_stable_codes_and_retryability() -> None:
    code, retryable = batch_support._stable_error_code(  # noqa: SLF001
        HTTPException(
            status_code=503,
            detail={"code": "ATTENDANCE_DEPENDENCY_UNAVAILABLE"},
        )
    )
    assert (code, retryable) == ("ATTENDANCE_DEPENDENCY_UNAVAILABLE", True)

    assert batch_support._stable_error_code(  # noqa: SLF001
        HTTPException(status_code=409, detail="conflict")
    ) == ("ATTENDANCE_SCAN_CONFLICT", False)


@pytest.mark.asyncio
async def test_unexpected_batch_failure_logs_only_sanitized_error_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _item("scan-event-private-error")
    agency_id = uuid.uuid4()
    sanitized_error = MagicMock()
    scan = AsyncMock(side_effect=RuntimeError("traveller-secret-must-not-be-logged"))
    session = MagicMock()
    monkeypatch.setattr(batch_support, "logger", SimpleNamespace(error=sanitized_error))
    monkeypatch.setattr(batch_support, "record_coordinator_attendance_scan", scan)

    response = await batch_support._process_new_item(  # noqa: SLF001
        item=item,
        request=Request({"type": "http", "method": "POST", "path": "/"}),
        current_user=_coordinator(agency_id),
        session=cast(Any, session),
        agency_id=agency_id,
        attendance_session=cast(
            Any,
            SimpleNamespace(id=uuid.uuid4(), group_id=uuid.uuid4()),
        ),
        runtime=None,
        dependencies=AttendanceBatchDependencies(
            scan=cast(Any, object()),
            attendance_scan_response=cast(Any, object()),
        ),
    )

    assert response.retryable is True
    assert response.error_code == "ATTENDANCE_SCAN_TEMPORARY_FAILURE"
    sanitized_error.assert_called_once_with(
        "attendance_scan_batch_item_failed",
        client_event_id=item.client_event_id,
        error_code="ATTENDANCE_SCAN_TEMPORARY_FAILURE",
        error_type="RuntimeError",
    )
    assert "traveller-secret-must-not-be-logged" not in repr(sanitized_error.call_args)


@pytest.mark.asyncio
async def test_batch_preserves_request_order_and_does_not_ledger_retryable_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = _request("scan-event-0006", "scan-event-0007")
    agency_id = uuid.uuid4()
    current_user = _coordinator(agency_id)
    retryable = AttendanceScanBatchItemResponse(
        client_event_id="scan-event-0006",
        outcome="rejected",
        retryable=True,
        error_code="ATTENDANCE_SCAN_TEMPORARY_FAILURE",
    )
    terminal = AttendanceScanBatchItemResponse(
        client_event_id="scan-event-0007",
        outcome="rejected",
        retryable=False,
        error_code="ATTENDANCE_QR_INVALID",
    )
    replayed = terminal.model_copy()

    require_batch = AsyncMock(return_value=None)
    load_existing = AsyncMock(side_effect=[None, None])
    process_item = AsyncMock(side_effect=[retryable, terminal])
    persisted = SimpleNamespace(client_event_id="scan-event-0007")
    persist_terminal = AsyncMock(return_value=persisted)
    replay_existing = AsyncMock(return_value=replayed)
    monkeypatch.setattr(batch_support, "_require_batch_identity", require_batch)
    monkeypatch.setattr(batch_support, "_load_existing_result", load_existing)
    monkeypatch.setattr(batch_support, "_process_new_item", process_item)
    monkeypatch.setattr(batch_support, "_persist_terminal_result", persist_terminal)
    monkeypatch.setattr(batch_support, "_replay_existing_result", replay_existing)

    response = await batch_support.process_coordinator_attendance_scan_batch(
        body=body,
        request=Request({"type": "http", "method": "POST", "path": "/"}),
        current_user=current_user,
        session=cast(Any, object()),
        agency_id=agency_id,
        attendance_session=cast(
            Any,
            SimpleNamespace(id=uuid.uuid4(), group_id=uuid.uuid4()),
        ),
        runtime=None,
        dependencies=AttendanceBatchDependencies(
            scan=cast(Any, object()),
            attendance_scan_response=cast(Any, object()),
        ),
    )

    assert [item.client_event_id for item in response.items] == [
        "scan-event-0006",
        "scan-event-0007",
    ]
    assert persist_terminal.await_count == 1
    persist_call = persist_terminal.await_args
    assert persist_call is not None
    assert persist_call.kwargs["item"].client_event_id == "scan-event-0007"


def test_batch_route_requires_cookie_csrf_and_coordinator_auth() -> None:
    route = next(
        route
        for route in tour_operations.router.routes
        if isinstance(route, APIRoute)
        and route.path == "/coordinator/sessions/{session_id}/scan/batch"
    )
    dependency_names = {
        dependency.call.__name__
        for dependency in route.dependant.dependencies
        if dependency.call is not None
    }

    assert route.methods == {"POST"}
    assert "require_cookie_csrf" in dependency_names
    assert "_check_role" in dependency_names
