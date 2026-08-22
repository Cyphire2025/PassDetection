from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Literal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.core.security.mobile_jwt import MobileAccessClaims
from app.domain.exceptions.exceptions import AuthorizationError, EntityNotFoundError
from app.infrastructure.qr.approved_passenger_qr_issuer import qr_hash
from app.presentation.api.v1.routes.mobile_ops import (
    _MANAGER_PREVIEW_DATABASE_TYPES,
    _PUSH_ONLY_NOTIFICATION_TYPES,
    _accessible_group_ids,
    _assert_attendance_session_creation_capacity,
    _attendance_rejection_code,
    _attendance_replay_snapshot,
    _attendance_replay_state,
    _attendance_replay_state_from_snapshot,
    _attendance_sessions_for_actions,
    _AttendanceReplaySnapshot,
    _coordinator_document_category,
    _PreparedAttendanceAction,
    _push_fernet,
    _require_client_manager_trip,
    _resolve_scannable_passenger_from_snapshot,
    _safe_optional_date,
    _safe_public_payload,
    _scannable_passenger_snapshot,
    _validate_manager_document_signature,
    apply_mobile_attendance_actions,
    complete_mobile_attendance_session,
    complete_mobile_manager_attendance_session,
    create_mobile_attendance_session,
    create_mobile_incident,
    create_mobile_manager_attendance_session,
    get_mobile_coordinator_passenger,
    get_mobile_manager_attendance_closeout_status,
    get_mobile_manager_passenger,
    list_mobile_coordinator_passengers,
    list_mobile_manager_passengers,
    publish_mobile_attendance_closeout_checkpoint,
    router,
)
from app.presentation.api.v1.schemas.attendance_closeout_schemas import (
    AttendanceCloseoutCheckpointRequest,
    AttendanceCloseoutCoordinatorStatusResponse,
    AttendanceCloseoutStatusResponse,
    AttendanceCloseRequest,
)
from app.presentation.api.v1.schemas.mobile_schemas import (
    MobileAttendanceActionInput,
    MobileAttendanceBatchRequest,
    MobileAttendanceSessionCreateRequest,
    MobileIncidentCreateRequest,
    MobilePushRegistrationRequest,
)


def _claims(role: str = "coordinator") -> MobileAccessClaims:
    principal_id = uuid.uuid4()
    return MobileAccessClaims(
        principal_id=principal_id,
        account_id=principal_id,
        principal_type=role,  # type: ignore[arg-type]
        agency_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        session_generation=1,
        password_change_required=False,
        expires_at=datetime.now(tz=UTC) + timedelta(minutes=10),
    )


def _action(*, event_id: uuid.UUID | None = None) -> MobileAttendanceActionInput:
    return MobileAttendanceActionInput(
        client_event_id=event_id or uuid.uuid4(),
        signed_qr="pdatt:" + ("A" * 43),
        scanned_at=datetime.now(tz=UTC),
        source="qr",
    )


def test_mobile_ops_projects_domestic_lanes_as_flight_tickets() -> None:
    manager_types = _MANAGER_PREVIEW_DATABASE_TYPES["flight_ticket"]

    assert "flight_ticket_domestic" in manager_types
    assert "flight_ticket_domestic_arrival" in manager_types
    assert _coordinator_document_category("flight_ticket_domestic") == "flight_ticket"
    assert _coordinator_document_category("flight_ticket_domestic_arrival") == "flight_ticket"


def test_mobile_ops_routes_match_native_client_contract() -> None:
    assert {route.path for route in router.routes} == {
        "/coordinator/groups/{group_id}/passengers",
        "/coordinator/groups/{group_id}/passengers/{passenger_id}",
        "/coordinator/groups/{group_id}/attendance/sessions",
        "/coordinator/groups/{group_id}/attendance/sessions/{session_id}",
        "/coordinator/groups/{group_id}/attendance/sessions/{session_id}/closeout-checkpoint",
        "/coordinator/groups/{group_id}/attendance/sessions/{session_id}/complete",
        "/coordinator/groups/{group_id}/attendance/sessions/{session_id}/roster",
        "/coordinator/groups/{group_id}/attendance/actions",
        "/coordinator/groups/{group_id}/attendance/summary",
        "/coordinator/groups/{group_id}/incidents",
        "/manager/groups/{group_id}/passengers",
        "/manager/groups/{group_id}/passengers/{passenger_id}",
        "/manager/groups/{group_id}/passengers/{passenger_id}/documents/{document_type}/preview",
        "/manager/groups/{group_id}/attendance/sessions",
        "/manager/groups/{group_id}/attendance/sessions/{session_id}/closeout",
        "/manager/groups/{group_id}/attendance/sessions/{session_id}/complete",
        "/manager/groups/{group_id}/attendance/sessions/{session_id}/roster",
        "/push/register",
        "/push/unregister",
        "/notifications",
        "/notifications/{notification_id}/read",
    }
    coordinator_create = next(
        route
        for route in router.routes
        if route.path == "/coordinator/groups/{group_id}/attendance/sessions"
        and "POST" in route.methods
    )
    manager_create = next(
        route
        for route in router.routes
        if route.path == "/manager/groups/{group_id}/attendance/sessions"
        and "POST" in route.methods
    )
    assert coordinator_create.deprecated is True
    assert manager_create.deprecated is not True


def _closeout_response(
    state: str = "ready",
    *,
    pending_count: int = 0,
) -> AttendanceCloseoutStatusResponse:
    coordinator = AttendanceCloseoutCoordinatorStatusResponse(
        coordinator_id=uuid.uuid4(),
        coordinator_name="Coordinator",
        state=state,  # type: ignore[arg-type]
        reported_at=(datetime.now(tz=UTC) if state != "missing" else None),
        report_age_seconds=(0 if state != "missing" else None),
        pending_count=pending_count,
        sending_count=0,
        retryable_count=0,
        needs_review_count=0,
        unreviewed_rejected_count=0,
        oldest_pending_age_seconds=(1 if pending_count else None),
    )
    ready = state == "ready"
    return AttendanceCloseoutStatusResponse(
        ready=ready,
        checkpoint_ttl_seconds=120,
        active_assignment_count=1,
        ready_assignment_count=1 if ready else 0,
        missing_assignment_count=1 if state == "missing" else 0,
        stale_assignment_count=1 if state == "stale" else 0,
        nonzero_assignment_count=1 if pending_count else 0,
        blocked_assignment_count=0 if ready else 1,
        unresolved_count=pending_count,
        oldest_pending_age_seconds=1 if pending_count else None,
        coordinators=[coordinator],
    )


@pytest.mark.asyncio
async def test_client_manager_trip_scope_fails_closed_for_other_mobile_roles() -> None:
    with pytest.raises(AuthorizationError, match="Client manager"):
        await _require_client_manager_trip(MagicMock(), _claims("coordinator"), uuid.uuid4())


@pytest.mark.asyncio
async def test_legacy_coordinator_global_close_is_explicitly_denied_before_session_lookup() -> None:
    claims = _claims("coordinator")
    group_id = uuid.uuid4()
    database = MagicMock()
    authorize = AsyncMock(return_value=SimpleNamespace())
    lookup = AsyncMock()

    with (
        patch(
            "app.presentation.api.v1.routes.mobile_ops._require_coordinator_trip",
            new=authorize,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._mobile_attendance_session",
            new=lookup,
        ),
        pytest.raises(AuthorizationError, match="Only an authorized Client Manager"),
    ):
        await complete_mobile_attendance_session(
            group_id=group_id,
            session_id=uuid.uuid4(),
            claims=claims,
            session=database,
        )

    authorize.assert_awaited_once_with(database, claims, group_id)
    lookup.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_coordinator_activity_create_is_denied_before_any_write() -> None:
    claims = _claims("coordinator")
    group_id = uuid.uuid4()
    database = MagicMock()
    authorize = AsyncMock(return_value=SimpleNamespace())
    create = AsyncMock()

    with (
        patch(
            "app.presentation.api.v1.routes.mobile_ops._require_coordinator_trip",
            new=authorize,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._create_canonical_attendance_activity",
            new=create,
        ),
        pytest.raises(AuthorizationError, match="authorized Client Manager"),
    ):
        await create_mobile_attendance_session(
            group_id=group_id,
            body=MobileAttendanceSessionCreateRequest(name="Unauthorized count"),
            claims=claims,
            session=database,
        )

    authorize.assert_awaited_once_with(database, claims, group_id)
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_manager_global_close_rejects_coordinator_before_any_object_query() -> None:
    database = MagicMock()
    database.execute = AsyncMock()

    with pytest.raises(AuthorizationError, match="Client manager"):
        await complete_mobile_manager_attendance_session(
            group_id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            request=MagicMock(),
            claims=_claims("coordinator"),
            session=database,
        )

    database.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_client_manager_creation_uses_canonical_boundary_and_notifies_coordinators() -> None:
    claims = _claims("client_manager")
    group_id = uuid.uuid4()
    activity = SimpleNamespace(id=uuid.uuid4(), status="active")
    access = SimpleNamespace(manifest_version=17)
    trip = SimpleNamespace(access=access)
    expected = SimpleNamespace(id=activity.id, scanned_count=0, assigned_count=800)
    database = MagicMock()
    authorize = AsyncMock(return_value=trip)
    create = AsyncMock(return_value=(activity, "created"))
    responses = AsyncMock(return_value=[expected])
    append_change = AsyncMock()
    audit = MagicMock(record=AsyncMock())

    with (
        patch(
            "app.presentation.api.v1.routes.mobile_ops._require_client_manager_trip",
            new=authorize,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._create_canonical_attendance_activity",
            new=create,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._mobile_attendance_session_responses",
            new=responses,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops.append_mobile_sync_change",
            new=append_change,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops.AuditLogRepository",
            return_value=audit,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops.trusted_client_ip",
            return_value="203.0.113.10",
        ),
    ):
        result = await create_mobile_manager_attendance_session(
            group_id=group_id,
            body=MobileAttendanceSessionCreateRequest(name="Airport reporting"),
            request=MagicMock(),
            claims=claims,
            session=database,
        )

    assert result is expected
    authorize.assert_awaited_once_with(database, claims, group_id)
    create.assert_awaited_once_with(
        database,
        agency_id=claims.agency_id,
        group_id=group_id,
        name="Airport reporting",
        created_by_user_id=claims.principal_id,
    )
    append_change.assert_awaited_once()
    assert append_change.await_args.kwargs["audience"] == "coordinator"
    assert append_change.await_args.kwargs["entity_id"] == activity.id
    audit.record.assert_awaited_once()
    assert audit.record.await_args.kwargs["metadata"] == {
        "group_id": str(group_id),
        "outcome": "created",
        "canonical_session_id": str(activity.id),
    }


@pytest.mark.asyncio
async def test_client_manager_global_close_uses_locked_shared_boundary_and_audits() -> None:
    claims = _claims("client_manager")
    group_id = uuid.uuid4()
    activity = SimpleNamespace(id=uuid.uuid4(), status="active")
    access = SimpleNamespace(manifest_version=17)
    trip = SimpleNamespace(access=access)
    expected = SimpleNamespace(scanned_count=794, assigned_count=800)
    database = MagicMock()
    authorize = AsyncMock(return_value=trip)
    lookup = AsyncMock(return_value=activity)
    lock_group = AsyncMock()
    closeout = _closeout_response()
    load_closeout = AsyncMock(return_value=closeout)
    close = AsyncMock(return_value=True)
    responses = AsyncMock(return_value=[expected])
    append_change = AsyncMock()
    audit = MagicMock(record=AsyncMock())

    with (
        patch(
            "app.presentation.api.v1.routes.mobile_ops._require_client_manager_trip",
            new=authorize,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._mobile_attendance_session",
            new=lookup,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._lock_attendance_closeout_group",
            new=lock_group,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._load_attendance_closeout_status",
            new=load_closeout,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._close_shared_attendance_activity",
            new=close,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._mobile_attendance_session_responses",
            new=responses,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops.append_mobile_sync_change",
            new=append_change,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops.AuditLogRepository",
            return_value=audit,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops.trusted_client_ip",
            return_value="203.0.113.10",
        ),
    ):
        result = await complete_mobile_manager_attendance_session(
            group_id=group_id,
            session_id=activity.id,
            request=MagicMock(),
            claims=claims,
            session=database,
        )

    assert result is expected
    authorize.assert_awaited_once_with(database, claims, group_id)
    lock_group.assert_awaited_once_with(
        database,
        agency_id=claims.agency_id,
        group_id=group_id,
    )
    lookup.assert_awaited_once_with(
        database,
        claims=claims,
        group_id=group_id,
        session_id=activity.id,
        lock=True,
    )
    close.assert_awaited_once_with(database, activity)
    append_change.assert_awaited_once()
    assert append_change.await_args.kwargs["audience"] == "coordinator"
    assert append_change.await_args.kwargs["entity_type"] == "attendance_session"
    audit.record.assert_awaited_once()
    assert audit.record.await_args.kwargs["metadata"] == {
        "group_id": str(group_id),
        "server_scanned_count": 794,
        "assigned_count": 800,
        "late_offline_reconciliation_allowed": True,
        "closeout": {
            "exception_used": False,
            "exception_reason": None,
            "checkpoint_ttl_seconds": 120,
            "active_assignment_count": 1,
            "ready_assignment_count": 1,
            "missing_assignment_count": 0,
            "stale_assignment_count": 0,
            "nonzero_assignment_count": 0,
            "blocked_assignment_count": 0,
            "unresolved_count": 0,
            "oldest_pending_age_seconds": None,
            "coordinators": [
                {
                    "coordinator_id": str(closeout.coordinators[0].coordinator_id),
                    "state": "ready",
                    "reported_at": closeout.coordinators[0].reported_at.isoformat(),
                    "pending_count": 0,
                    "sending_count": 0,
                    "retryable_count": 0,
                    "needs_review_count": 0,
                    "unreviewed_rejected_count": 0,
                    "oldest_pending_age_seconds": None,
                }
            ],
        },
    }


@pytest.mark.asyncio
async def test_mobile_coordinator_checkpoint_uses_shared_activity_lock_and_count_only_identity() -> None:
    claims = _claims("coordinator")
    group_id = uuid.uuid4()
    activity = SimpleNamespace(id=uuid.uuid4(), status="active")
    checkpoint = SimpleNamespace(reported_at=datetime.now(tz=UTC))
    repository = MagicMock(publish=AsyncMock(return_value=checkpoint))
    authorize = AsyncMock(return_value=SimpleNamespace())
    lookup = AsyncMock(return_value=activity)
    body = AttendanceCloseoutCheckpointRequest(
        pending_count=2,
        sending_count=0,
        retryable_count=0,
        needs_review_count=1,
        unreviewed_rejected_count=0,
        oldest_pending_age_seconds=15,
    )

    with (
        patch(
            "app.presentation.api.v1.routes.mobile_ops._require_coordinator_trip",
            new=authorize,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._mobile_attendance_session",
            new=lookup,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops.AttendanceCloseoutRepository",
            return_value=repository,
        ),
    ):
        response = await publish_mobile_attendance_closeout_checkpoint(
            group_id=group_id,
            session_id=activity.id,
            body=body,
            claims=claims,
            session=MagicMock(),
        )

    lookup.assert_awaited_once()
    assert lookup.await_args.kwargs["lock"] == "read"
    publish_kwargs = repository.publish.await_args.kwargs
    assert publish_kwargs["coordinator_user_id"] == claims.principal_id
    assert set(publish_kwargs["counts"].__dataclass_fields__) == {
        "pending_count",
        "sending_count",
        "retryable_count",
        "needs_review_count",
        "unreviewed_rejected_count",
        "oldest_pending_age_seconds",
    }
    assert response.pending_count == 2
    assert response.needs_review_count == 1


@pytest.mark.asyncio
async def test_mobile_manager_close_fails_closed_before_state_change_when_checkpoint_missing() -> None:
    claims = _claims("client_manager")
    group_id = uuid.uuid4()
    activity = SimpleNamespace(id=uuid.uuid4(), status="active")
    close = AsyncMock()
    responses = AsyncMock()
    with (
        patch(
            "app.presentation.api.v1.routes.mobile_ops._require_client_manager_trip",
            new=AsyncMock(return_value=SimpleNamespace()),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._lock_attendance_closeout_group",
            new=AsyncMock(),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._mobile_attendance_session",
            new=AsyncMock(return_value=activity),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._load_attendance_closeout_status",
            new=AsyncMock(return_value=_closeout_response("missing")),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._close_shared_attendance_activity",
            new=close,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._mobile_attendance_session_responses",
            new=responses,
        ),
        pytest.raises(HTTPException) as caught,
    ):
        await complete_mobile_manager_attendance_session(
            group_id=group_id,
            session_id=activity.id,
            request=MagicMock(),
            claims=claims,
            session=MagicMock(),
        )

    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "ATTENDANCE_CLOSEOUT_BLOCKED"
    close.assert_not_awaited()
    responses.assert_not_awaited()


@pytest.mark.asyncio
async def test_mobile_manager_exception_matches_web_guard_and_audit_contract() -> None:
    claims = _claims("client_manager")
    group_id = uuid.uuid4()
    activity = SimpleNamespace(id=uuid.uuid4(), status="active")
    closeout = _closeout_response("blocked", pending_count=3)
    response = SimpleNamespace(scanned_count=797, assigned_count=800)
    audit = MagicMock(record=AsyncMock())
    with (
        patch(
            "app.presentation.api.v1.routes.mobile_ops._require_client_manager_trip",
            new=AsyncMock(return_value=SimpleNamespace(access=SimpleNamespace(manifest_version=9))),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._lock_attendance_closeout_group",
            new=AsyncMock(),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._mobile_attendance_session",
            new=AsyncMock(return_value=activity),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._load_attendance_closeout_status",
            new=AsyncMock(return_value=closeout),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._close_shared_attendance_activity",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._mobile_attendance_session_responses",
            new=AsyncMock(return_value=[response]),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops.append_mobile_sync_change",
            new=AsyncMock(),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops.AuditLogRepository",
            return_value=audit,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops.trusted_client_ip",
            return_value="203.0.113.13",
        ),
    ):
        result = await complete_mobile_manager_attendance_session(
            group_id=group_id,
            session_id=activity.id,
            request=MagicMock(),
            claims=claims,
            session=MagicMock(),
            body=AttendanceCloseRequest(
                exception_reason="approved transport emergency override",
            ),
        )

    assert result is response
    audited = audit.record.await_args.kwargs["metadata"]["closeout"]
    assert audited["exception_used"] is True
    assert audited["exception_reason"] == "approved transport emergency override"
    assert audited["unresolved_count"] == 3


@pytest.mark.asyncio
async def test_mobile_manager_status_returns_only_safe_closeout_aggregates() -> None:
    claims = _claims("client_manager")
    group_id = uuid.uuid4()
    activity = SimpleNamespace(id=uuid.uuid4(), status="active")
    closeout = _closeout_response("blocked", pending_count=1)
    load = AsyncMock(return_value=closeout)
    with (
        patch(
            "app.presentation.api.v1.routes.mobile_ops._require_client_manager_trip",
            new=AsyncMock(return_value=SimpleNamespace()),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._mobile_attendance_session",
            new=AsyncMock(return_value=activity),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._load_attendance_closeout_status",
            new=load,
        ),
    ):
        result = await get_mobile_manager_attendance_closeout_status(
            group_id=group_id,
            session_id=activity.id,
            claims=claims,
            session=MagicMock(),
        )

    assert result is closeout
    serialized = result.model_dump(mode="json")
    assert "coordinators" in serialized
    assert not any(
        forbidden in str(serialized).lower()
        for forbidden in ("qr_payload", "passenger_id", "device_id", "client_event_id")
    )


@pytest.mark.asyncio
async def test_client_manager_roster_includes_every_group_passenger_status() -> None:
    claims = _claims("client_manager")
    group_id = uuid.uuid4()
    count_result = MagicMock()
    count_result.scalar_one.return_value = 0
    rows_result = MagicMock()
    rows_result.all.return_value = []
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[count_result, rows_result])

    with patch(
        "app.presentation.api.v1.routes.mobile_ops._require_client_manager_trip",
        new=AsyncMock(return_value=SimpleNamespace()),
    ):
        response = await list_mobile_manager_passengers(
            group_id=group_id,
            search="",
            cursor=None,
            limit=100,
            claims=claims,
            session=session,
        )

    assert response.total == 0
    sql = "\n".join(
        str(call.args[0].compile(compile_kwargs={"literal_binds": True}))
        for call in session.execute.await_args_list
    )
    assert "passport_submissions.agency_id =" in sql
    assert "passport_submissions.group_id =" in sql
    assert "passport_submissions.status" not in sql


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("roster_filter", "required_sql"),
    (("rooming", "rooming_rooms.room_number"), ("meals", "meal_preference")),
)
async def test_coordinator_roster_filters_before_count_and_cursor_pagination(
    roster_filter: Literal["rooming", "meals"],
    required_sql: str,
) -> None:
    claims = _claims("coordinator")
    group_id = uuid.uuid4()
    count_result = MagicMock()
    count_result.scalar_one.return_value = 0
    rows_result = MagicMock()
    rows_result.all.return_value = []
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[count_result, rows_result])

    with (
        patch(
            "app.presentation.api.v1.routes.mobile_ops._require_coordinator_trip",
            new=AsyncMock(return_value=SimpleNamespace()),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._latest_attendance_session",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops.coordinator_roster_revision",
            new=AsyncMock(return_value=7),
        ),
    ):
        response = await list_mobile_coordinator_passengers(
            group_id=group_id,
            search="",
            roster_filter=roster_filter,
            cursor=None,
            limit=100,
            claims=claims,
            session=session,
        )

    assert response.total == 0
    statements = [
        str(call.args[0].compile(compile_kwargs={"literal_binds": True})).lower()
        for call in session.execute.await_args_list
    ]
    assert len(statements) == 2
    for sql in statements:
        assert required_sql in sql
        assert "is not null" in sql
        assert "length(trim" in sql


@pytest.mark.asyncio
async def test_attendance_session_capacity_is_tenant_scoped_and_serialized() -> None:
    claims = _claims("coordinator")
    group_id = uuid.uuid4()
    session = MagicMock()
    session.scalar = AsyncMock(side_effect=[group_id, None, 10_000])

    with pytest.raises(HTTPException) as caught:
        await _assert_attendance_session_creation_capacity(
            session,
            claims=claims,
            group_id=group_id,
            normalized_name="departure",
        )

    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "ATTENDANCE_SESSION_CAPACITY_REACHED"
    assert session.scalar.await_count == 3
    lock_sql = str(
        session.scalar.await_args_list[0].args[0].compile(
            compile_kwargs={"literal_binds": True}
        )
    )
    assert "client_groups.agency_id" in lock_sql
    assert "client_groups.deleted_at IS NULL" in lock_sql
    assert "FOR UPDATE" in lock_sql


@pytest.mark.asyncio
async def test_attendance_session_capacity_keeps_idempotent_active_name_retry() -> None:
    claims = _claims("coordinator")
    group_id = uuid.uuid4()
    existing_id = uuid.uuid4()
    session = MagicMock()
    session.scalar = AsyncMock(side_effect=[group_id, existing_id])

    await _assert_attendance_session_creation_capacity(
        session,
        claims=claims,
        group_id=group_id,
        normalized_name="departure",
    )

    assert session.scalar.await_count == 2



@pytest.mark.asyncio
async def test_client_manager_detail_accepts_an_assigned_in_progress_passenger() -> None:
    claims = _claims("client_manager")
    group_id = uuid.uuid4()
    passenger_id = uuid.uuid4()
    missing = MagicMock()
    missing.one_or_none.return_value = None
    session = MagicMock()
    session.execute = AsyncMock(return_value=missing)

    with (
        patch(
            "app.presentation.api.v1.routes.mobile_ops._require_client_manager_trip",
            new=AsyncMock(return_value=SimpleNamespace()),
        ),
        pytest.raises(EntityNotFoundError),
    ):
        await get_mobile_manager_passenger(
            group_id=group_id,
            passenger_id=passenger_id,
            claims=claims,
            session=session,
        )

    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
    where_sql = sql.split("WHERE", 1)[1]
    assert "passport_submissions.id =" in sql
    assert "passport_submissions.agency_id =" in sql
    assert "passport_submissions.group_id =" in sql
    assert "passport_submissions.status" not in where_sql


def test_client_manager_preview_signature_validation_is_fail_closed() -> None:
    _validate_manager_document_signature(b"%PDF-1.7\n", "application/pdf")
    _validate_manager_document_signature(b"\xff\xd8\xff\xe0", "image/jpeg")
    _validate_manager_document_signature(b"\x89PNG\r\n\x1a\n", "image/png")
    _validate_manager_document_signature(b"RIFF1234WEBP", "image/webp")

    with pytest.raises(HTTPException) as caught:
        _validate_manager_document_signature(b"<html>not a pdf", "application/pdf")
    assert caught.value.status_code == 415


def test_attendance_batch_requires_unique_uuid_event_ids() -> None:
    event_id = uuid.uuid4()
    with pytest.raises(ValidationError, match="must be unique"):
        MobileAttendanceBatchRequest(
            actions=[_action(event_id=event_id), _action(event_id=event_id)]
        )


def test_attendance_batch_is_bounded_to_one_hundred_actions() -> None:
    with pytest.raises(ValidationError):
        MobileAttendanceBatchRequest(actions=[_action() for _ in range(101)])


def test_attendance_scan_timestamp_requires_timezone() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        MobileAttendanceActionInput(
            client_event_id=uuid.uuid4(),
            signed_qr="pdatt:" + ("A" * 43),
            scanned_at=datetime.now(),
        )


@pytest.mark.asyncio
async def test_attendance_batch_returns_per_item_idempotent_results() -> None:
    claims = _claims()
    group_id = uuid.uuid4()
    actions = [_action(), _action(), _action()]
    attendance_session = SimpleNamespace(
        id=uuid.uuid4(),
        status="active",
        started_at=None,
        completed_at=None,
    )
    passenger = SimpleNamespace(id=uuid.uuid4())
    session = MagicMock()
    session.flush = AsyncMock()

    with (
        patch(
            "app.presentation.api.v1.routes.mobile_ops._require_coordinator_trip",
            new=AsyncMock(return_value=SimpleNamespace(access=SimpleNamespace())),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._attendance_sessions_for_actions",
            new=AsyncMock(return_value={None: attendance_session}),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._scannable_passenger_snapshot",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._resolve_scannable_passenger_from_snapshot",
            new=MagicMock(
                side_effect=[
                    (passenger, None),
                    (passenger, None),
                    (None, "wrong_group"),
                ]
            ),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._attendance_replay_snapshot",
            new=AsyncMock(
                return_value=_AttendanceReplaySnapshot(passengers=set(), event_passengers={})
            ),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._attendance_replay_state_from_snapshot",
            new=MagicMock(return_value="unknown"),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._insert_canonical_attendance_record",
            new=AsyncMock(side_effect=[uuid.uuid4(), None]),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._attendance_replay_state",
            new=AsyncMock(return_value="already_applied"),
        ) as replay_lookup,
        patch(
            "app.presentation.api.v1.routes.mobile_ops.append_mobile_sync_change",
            new=AsyncMock(return_value=SimpleNamespace(payload={})),
        ) as append_change,
        patch(
            "app.presentation.api.v1.routes.mobile_ops.coordinator_roster_revision",
            new=AsyncMock(return_value=4242),
        ) as roster_revision,
    ):
        response = await apply_mobile_attendance_actions(
            group_id=group_id,
            body=MobileAttendanceBatchRequest(actions=actions),
            claims=claims,
            session=session,
        )

    assert [item.client_event_id for item in response.results] == [
        item.client_event_id for item in actions
    ]
    assert [item.status for item in response.results] == [
        "accepted",
        "already_applied",
        "rejected",
    ]
    assert response.results[-1].reason_code == "QR_WRONG_GROUP"
    roster_revision.assert_awaited_once()
    assert append_change.await_count == 1
    assert append_change.await_args.kwargs["flush"] is False
    assert append_change.return_value.payload["roster_revision"] == 4242
    assert session.flush.await_count == 2
    replay_lookup.assert_awaited_once()


@pytest.mark.asyncio
async def test_mobile_batch_rejects_a_fresh_scan_after_manager_close() -> None:
    claims = _claims()
    group_id = uuid.uuid4()
    completed_at = datetime.now(tz=UTC) - timedelta(seconds=1)
    action = _action()
    attendance_session = SimpleNamespace(
        id=uuid.uuid4(),
        status="completed",
        started_at=completed_at - timedelta(hours=1),
        completed_at=completed_at,
    )
    qr_lookup = AsyncMock()

    with (
        patch(
            "app.presentation.api.v1.routes.mobile_ops._require_coordinator_trip",
            new=AsyncMock(return_value=SimpleNamespace(access=SimpleNamespace())),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._attendance_sessions_for_actions",
            new=AsyncMock(return_value={None: attendance_session}),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._scannable_passenger_snapshot",
            new=qr_lookup,
        ),
    ):
        response = await apply_mobile_attendance_actions(
            group_id=group_id,
            body=MobileAttendanceBatchRequest(actions=[action]),
            claims=claims,
            session=MagicMock(),
        )

    assert len(response.results) == 1
    assert response.results[0].status == "rejected"
    assert response.results[0].reason_code == "SCANNED_OUTSIDE_SESSION_WINDOW"
    qr_lookup.assert_awaited_once()
    assert qr_lookup.await_args.kwargs["actions"] == []


@pytest.mark.asyncio
async def test_attendance_replay_rejects_event_id_bound_to_another_passenger() -> None:
    claims = _claims()
    requested_passenger = uuid.uuid4()
    reused_event_id = str(uuid.uuid4())
    result = MagicMock()
    result.all.return_value = [
        SimpleNamespace(
            passenger_id=uuid.uuid4(),
            client_event_id=reused_event_id,
        )
    ]
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    state = await _attendance_replay_state(
        session,
        claims=claims,
        attendance_session=SimpleNamespace(id=uuid.uuid4()),
        passenger_id=requested_passenger,
        client_event_id=reused_event_id,
    )

    assert state == "event_reused"
    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "attendance_records.agency_id" in sql
    assert "attendance_session_family.canonical_session_id" in sql
    assert reused_event_id in sql


def test_attendance_rejection_codes_do_not_echo_internal_values() -> None:
    assert _attendance_rejection_code("expired") == "QR_EXPIRED"
    assert _attendance_rejection_code("database-details") == "QR_INVALID"


@pytest.mark.asyncio
async def test_attendance_session_batch_uses_two_bounded_scoped_reads() -> None:
    claims = _claims()
    group_id = uuid.uuid4()
    requested_id = uuid.uuid4()
    requested_session = SimpleNamespace(id=requested_id)
    default_session = SimpleNamespace(id=uuid.uuid4())
    requested_result = MagicMock()
    requested_result.scalars.return_value = [requested_session]
    default_result = MagicMock()
    default_result.scalars.return_value = [default_session]
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[requested_result, default_result])
    requested_action = _action().model_copy(update={"session_id": requested_id})

    resolved = await _attendance_sessions_for_actions(
        session,
        claims,
        group_id,
        actions=[requested_action, requested_action, _action()],
    )

    assert resolved == {requested_id: requested_session, None: default_session}
    assert session.execute.await_count == 2
    requested_sql = str(
        session.execute.await_args_list[0].args[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True}
        )
    )
    default_sql = str(
        session.execute.await_args_list[1].args[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True}
        )
    )
    assert "attendance_sessions.agency_id" in requested_sql
    assert "attendance_sessions.group_id" in requested_sql
    assert str(claims.agency_id) in requested_sql
    assert str(group_id) in requested_sql
    assert str(requested_id) in requested_sql
    assert "FOR SHARE" in requested_sql
    assert "LIMIT 2" in default_sql
    assert "FOR SHARE" in default_sql


@pytest.mark.asyncio
async def test_attendance_qr_batch_is_tenant_scoped_and_loaded_once() -> None:
    claims = _claims()
    first_action = _action()
    second_action = _action().model_copy(
        update={"signed_qr": "pdatt:" + ("B" * 43)}
    )
    first_passenger = SimpleNamespace(id=uuid.uuid4())
    second_passenger = SimpleNamespace(id=uuid.uuid4())
    first_token = SimpleNamespace(token_hash=qr_hash(first_action.signed_qr))
    second_token = SimpleNamespace(token_hash=qr_hash(second_action.signed_qr))
    result = MagicMock()
    result.all.return_value = [
        (first_passenger, first_token),
        (second_passenger, second_token),
    ]
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    snapshot = await _scannable_passenger_snapshot(
        session,
        claims=claims,
        actions=[first_action, second_action],
    )

    assert session.execute.await_count == 1
    assert snapshot[first_token.token_hash][0] is first_passenger
    assert snapshot[second_token.token_hash][0] is second_passenger
    sql = str(
        session.execute.await_args.args[0].compile(
            compile_kwargs={"literal_binds": True}
        )
    )
    assert "passenger_qr_tokens.agency_id" in sql
    assert "passport_submissions.agency_id" in sql
    assert claims.agency_id.hex in sql
    assert first_token.token_hash in sql
    assert second_token.token_hash in sql


def test_attendance_qr_snapshot_preserves_fail_closed_rejection_precedence() -> None:
    payload = "pdatt:" + ("C" * 43)
    group_id = uuid.uuid4()
    passenger = SimpleNamespace(id=uuid.uuid4(), group_id=group_id)
    token = SimpleNamespace(
        token_hash=qr_hash(payload),
        revoked_at=datetime.now(tz=UTC),
        expires_at=datetime.now(tz=UTC) - timedelta(minutes=1),
        is_active=False,
    )
    snapshot = {token.token_hash: (passenger, token)}

    assert _resolve_scannable_passenger_from_snapshot(
        snapshot,
        group_id=group_id,
        qr_payload=payload,
    ) == (None, "revoked")
    token.revoked_at = None
    assert _resolve_scannable_passenger_from_snapshot(
        snapshot,
        group_id=group_id,
        qr_payload=payload,
    ) == (None, "expired")
    token.expires_at = datetime.now(tz=UTC) + timedelta(minutes=5)
    assert _resolve_scannable_passenger_from_snapshot(
        snapshot,
        group_id=group_id,
        qr_payload=payload,
    ) == (None, "inactive")
    token.is_active = True
    assert _resolve_scannable_passenger_from_snapshot(
        snapshot,
        group_id=uuid.uuid4(),
        qr_payload=payload,
    ) == (None, "wrong_group")
    assert _resolve_scannable_passenger_from_snapshot(
        snapshot,
        group_id=group_id,
        qr_payload=payload,
    ) == (passenger, None)


@pytest.mark.asyncio
async def test_attendance_replay_batch_uses_one_canonical_family_read() -> None:
    claims = _claims()
    attendance_session = SimpleNamespace(id=uuid.uuid4())
    passenger = SimpleNamespace(id=uuid.uuid4())
    action = _action().model_copy(update={"session_id": attendance_session.id})
    prepared = _PreparedAttendanceAction(
        action=action,
        attendance_session=attendance_session,
        passenger=passenger,
    )
    result = MagicMock()
    result.all.return_value = [
        SimpleNamespace(
            canonical_session_id=attendance_session.id,
            passenger_id=passenger.id,
            client_event_id=str(action.client_event_id),
        )
    ]
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    snapshot = await _attendance_replay_snapshot(
        session,
        claims=claims,
        prepared=[prepared, prepared],
    )

    assert session.execute.await_count == 1
    assert _attendance_replay_state_from_snapshot(
        snapshot,
        attendance_session=attendance_session,
        passenger_id=passenger.id,
        client_event_id=str(action.client_event_id),
    ) == "already_applied"
    sql = str(
        session.execute.await_args.args[0].compile(
            compile_kwargs={"literal_binds": True}
        )
    )
    assert "attendance_records.agency_id" in sql
    assert "mobile_attendance_batch_session_family.agency_id" in sql
    assert "mobile_attendance_batch_session_family.canonical_session_id" in sql
    assert attendance_session.id.hex in sql
    assert str(action.client_event_id) in sql


@pytest.mark.asyncio
async def test_hundred_scan_batch_bounds_reads_and_journal_flushes() -> None:
    claims = _claims()
    group_id = uuid.uuid4()
    actions = [_action() for _ in range(100)]
    attendance_session = SimpleNamespace(
        id=uuid.uuid4(),
        status="active",
        started_at=None,
        completed_at=None,
        updated_at=datetime.now(tz=UTC),
    )
    passengers = [SimpleNamespace(id=uuid.uuid4()) for _ in actions]
    session = MagicMock()
    session.flush = AsyncMock()
    session_lookup = AsyncMock(return_value={None: attendance_session})
    qr_lookup = AsyncMock(return_value={})
    replay_lookup = AsyncMock(
        return_value=_AttendanceReplaySnapshot(passengers=set(), event_passengers={})
    )
    race_fallback = AsyncMock(return_value="already_applied")
    changes = [SimpleNamespace(payload={}) for _ in actions]

    with (
        patch(
            "app.presentation.api.v1.routes.mobile_ops._require_coordinator_trip",
            new=AsyncMock(return_value=SimpleNamespace(access=SimpleNamespace())),
        ) as authorize,
        patch(
            "app.presentation.api.v1.routes.mobile_ops._attendance_sessions_for_actions",
            new=session_lookup,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._scannable_passenger_snapshot",
            new=qr_lookup,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._resolve_scannable_passenger_from_snapshot",
            new=MagicMock(side_effect=[(passenger, None) for passenger in passengers]),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._attendance_replay_snapshot",
            new=replay_lookup,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._insert_canonical_attendance_record",
            new=AsyncMock(side_effect=[uuid.uuid4() for _ in actions]),
        ) as insert_record,
        patch(
            "app.presentation.api.v1.routes.mobile_ops._attendance_replay_state",
            new=race_fallback,
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops.append_mobile_sync_change",
            new=AsyncMock(side_effect=changes),
        ) as append_change,
        patch(
            "app.presentation.api.v1.routes.mobile_ops.coordinator_roster_revision",
            new=AsyncMock(return_value=8080),
        ) as roster_revision,
    ):
        response = await apply_mobile_attendance_actions(
            group_id=group_id,
            body=MobileAttendanceBatchRequest(actions=actions),
            claims=claims,
            session=session,
        )

    authorize.assert_awaited_once_with(session, claims, group_id)
    session_lookup.assert_awaited_once()
    qr_lookup.assert_awaited_once()
    replay_lookup.assert_awaited_once()
    assert insert_record.await_count == 100
    race_fallback.assert_not_awaited()
    assert append_change.await_count == 100
    assert all(call.kwargs["flush"] is False for call in append_change.await_args_list)
    assert session.flush.await_count == 2
    roster_revision.assert_awaited_once()
    assert [item.client_event_id for item in response.results] == [
        action.client_event_id for action in actions
    ]
    assert {item.status for item in response.results} == {"accepted"}
    assert all(change.payload["roster_revision"] == 8080 for change in changes)


def test_push_token_ciphertext_does_not_contain_plaintext() -> None:
    token = b"ExponentPushToken[private-device-token]"
    encrypted = _push_fernet().encrypt(token)
    assert token not in encrypted
    assert _push_fernet().decrypt(encrypted) == token


def test_push_token_is_trimmed_before_length_validation() -> None:
    with pytest.raises(ValidationError):
        MobilePushRegistrationRequest(
            provider="fcm",
            push_token=" " * 16,
            installation_id="installation-1234",
        )

    request = MobilePushRegistrationRequest(
        provider="fcm",
        push_token="  valid-push-token-1234  ",
        installation_id="installation-1234",
    )
    assert request.push_token == "valid-push-token-1234"


def test_notification_payload_uses_a_fixed_public_allowlist() -> None:
    safe = _safe_public_payload(
        {
            "screen": "updates",
            "group_id": str(uuid.uuid4()),
            "passport_number": "P1234567",
            "storage_key": "private/passport.pdf",
        }
    )
    assert set(safe) == {"screen", "group_id"}


def test_trip_countdowns_are_excluded_from_the_durable_updates_feed() -> None:
    assert _PUSH_ONLY_NOTIFICATION_TYPES == frozenset({"trip_countdown"})


def test_coordinator_imported_date_parser_fails_closed() -> None:
    assert _safe_optional_date("2026-08-03").isoformat() == "2026-08-03"
    assert _safe_optional_date("03/08/2026").isoformat() == "2026-08-03"
    assert _safe_optional_date("not a passenger date") is None


@pytest.mark.asyncio
async def test_coordinator_passenger_detail_is_tenant_scoped_and_allowlisted() -> None:
    claims = _claims()
    group_id = uuid.uuid4()
    passenger_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    row = SimpleNamespace(
        id=passenger_id,
        client_name="Ada Passenger",
        client_phone="+919999999999",
        client_email="ada@example.test",
        departure_city="Delhi",
        nearest_domestic_airport="DEL",
        family_relation="Self",
        family_head_name="Ada Passenger",
        family_head_phone="+919999999999",
        family_head_email="ada@example.test",
        submission_mode="single",
        qualifier_relation_label="Self",
        status="confirmed",
        staff_metadata={
            "emergency_contact_name": "Grace Passenger",
            "emergency_contact_phone": "+919111111111",
            "emergency_contact_relation": "Sister",
            "remarks": "Wheelchair assistance at boarding",
            "flight_number": "AI 302",
            "shirt_size": "M",
            "checked_bag_count": 2,
            "passport_number": "P1234567",
            "mrz_raw": "P<INDSECRET",
            "storage_key": "private/passport-front.jpg",
            "confidence_score": "0.99",
            "internal_notes": "Office-only escalation",
            "source_sheet": "Roster",
        },
        custom_answers=[
            {
                "question_id": str(uuid.uuid4()),
                "label": "Preferred language",
                "value": "English",
            },
            {
                "question_id": str(uuid.uuid4()),
                "label": "Passport Number",
                "value": "P1234567",
            },
        ],
        custom_detail_answers=[
            {
                "detail_id": str(uuid.uuid4()),
                "label": "Accessibility requirement",
                "value": "Aisle seat near the exit",
            }
        ],
        image_s3_key="private/passport-front.jpg",
        updated_at=now,
        employee_code="EMP-42",
        employee_type="Staff",
        staff_code="STF-42",
        base_city="New Delhi",
        agency_dealership_name="North Region Dealer",
        zone_name="North",
        meal_preference="Vegetarian",
        designation="Engineer",
        department="Operations",
        gender="F",
        date_of_birth="03/08/1990",
        nationality="Indian",
        passport_surname="PASSENGER",
        passport_given_names="ADA",
        passport_place_of_issue="Delhi",
        passport_issuing_country="India",
        passport_date_of_issue="2020-01-02",
        passport_date_of_expiry="2030-01-01",
    )
    room = SimpleNamespace(room_id=uuid.uuid4(), room_number="402", hotel_name="Harbour Hotel")

    def one_or_none(value):  # type: ignore[no-untyped-def]
        result = MagicMock()
        result.one_or_none.return_value = value
        return result

    def first(value):  # type: ignore[no-untyped-def]
        result = MagicMock()
        result.first.return_value = value
        return result

    def scalars(values):  # type: ignore[no-untyped-def]
        result = MagicMock()
        result.scalars.return_value = values
        return result

    def scalar_one(value):  # type: ignore[no-untyped-def]
        result = MagicMock()
        result.scalar_one.return_value = value
        return result

    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=[
            one_or_none(row),
            first(room),
            scalars(["Grace Roommate"]),
            scalars(
                ["visa", "flight_ticket_arrival", "insurance", "hotel_voucher", "other"]
            ),
            scalar_one(1),
        ]
    )
    attendance = SimpleNamespace(id=uuid.uuid4(), status="completed")

    with (
        patch(
            "app.presentation.api.v1.routes.mobile_ops._require_coordinator_trip",
            new=AsyncMock(return_value=SimpleNamespace()),
        ),
        patch(
            "app.presentation.api.v1.routes.mobile_ops._latest_attendance_session",
            new=AsyncMock(return_value=attendance),
        ),
    ):
        response = await get_mobile_coordinator_passenger(
            group_id=group_id,
            passenger_id=passenger_id,
            claims=claims,
            session=session,
        )

    assert response.display_name == "Ada Passenger"
    assert response.attendance_status == "present"
    assert response.roommate_summary == "Grace Roommate"
    assert response.passport_status == "available"
    assert response.visa_status == "available"
    assert response.flight_ticket_status == "available"
    assert response.insurance_status == "available"
    assert response.hotel_voucher_status == "available"
    assert response.other_document_status == "available"
    assert response.staff_code == "STF-42"
    assert response.base_city == "New Delhi"
    assert response.agency_dealership_name == "North Region Dealer"
    assert response.zone_name == "North"
    assert response.passport_surname == "PASSENGER"
    assert response.passport_given_names == "ADA"
    assert response.passport_place_of_issue == "Delhi"
    assert response.passport_issuing_country == "India"
    assert response.passport_date_of_issue.isoformat() == "2020-01-02"
    assert response.passport_date_of_expiry.isoformat() == "2030-01-01"
    assert response.emergency_contact_name == "Grace Passenger"
    assert response.emergency_contact_phone == "+919111111111"
    assert response.emergency_contact_relation == "Sister"
    assert response.operational_remarks == "Wheelchair assistance at boarding"
    assert response.qualifier_relation == "Self"
    assert response.submission_mode == "single"
    assert response.submission_status == "confirmed"
    assert {(item.label, item.value, item.source) for item in response.additional_details} == {
        ("Flight Number", "AI 302", "imported"),
        ("Shirt Size", "M", "imported"),
        ("Checked Bag Count", "2", "imported"),
        ("Preferred language", "English", "custom_question"),
        (
            "Accessibility requirement",
            "Aisle seat near the exit",
            "custom_detail",
        ),
    }
    payload = response.model_dump(mode="json")
    assert not {
        "passport_number",
        "mrz_raw",
        "storage_key",
        "confidence_score",
        "internal_notes",
    }.intersection(payload)
    serialized_payload = json.dumps(payload).casefold()
    assert "p1234567" not in serialized_payload
    assert "p<indsecret" not in serialized_payload
    assert "private/passport-front.jpg" not in serialized_payload
    assert "office-only escalation" not in serialized_payload
    assert "confidence_score" not in serialized_payload

    sql = "\n".join(
        str(call.args[0].compile(compile_kwargs={"literal_binds": True}))
        for call in session.execute.await_args_list[:4]
    )
    assert "passport_submissions.agency_id =" in sql
    assert "passport_submissions.group_id =" in sql
    assert "passport_submissions.id =" in sql
    assert "rooming_hotels.agency_id =" in sql
    assert "rooming_hotels.group_id =" in sql
    assert "distributed_documents.agency_id =" in sql
    assert "distributed_documents.group_id =" in sql
    assert "distributed_documents.passenger_id =" in sql


@pytest.mark.asyncio
async def test_coordinator_passenger_detail_stops_before_query_when_group_is_unassigned() -> None:
    claims = _claims()
    session = MagicMock()
    session.execute = AsyncMock()
    with (
        patch(
            "app.presentation.api.v1.routes.mobile_ops._require_coordinator_trip",
            new=AsyncMock(side_effect=AuthorizationError("Coordinator group access is required")),
        ),
        pytest.raises(AuthorizationError, match="Coordinator group access"),
    ):
        await get_mobile_coordinator_passenger(
            group_id=uuid.uuid4(),
            passenger_id=uuid.uuid4(),
            claims=claims,
            session=session,
        )
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_coordinator_passenger_detail_rejects_cross_group_passenger_identifier() -> None:
    claims = _claims()
    group_id = uuid.uuid4()
    passenger_id = uuid.uuid4()
    missing = MagicMock()
    missing.one_or_none.return_value = None
    session = MagicMock()
    session.execute = AsyncMock(return_value=missing)
    with (
        patch(
            "app.presentation.api.v1.routes.mobile_ops._require_coordinator_trip",
            new=AsyncMock(return_value=SimpleNamespace()),
        ),
        pytest.raises(EntityNotFoundError),
    ):
        await get_mobile_coordinator_passenger(
            group_id=group_id,
            passenger_id=passenger_id,
            claims=claims,
            session=session,
        )

    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "passport_submissions.id =" in sql
    assert "passport_submissions.agency_id =" in sql
    assert "passport_submissions.group_id =" in sql


def test_accessible_notification_groups_are_role_and_tenant_scoped() -> None:
    claims = _claims("client_manager")
    statement = _accessible_group_ids(claims, datetime.now(tz=UTC))
    sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "gc_group_access.is_enabled IS true" in sql
    assert "gc_group_access.client_manager_access_enabled IS true" in sql
    assert "client_manager_profiles.user_id" in sql
    assert claims.principal_id.hex in sql
    assert claims.agency_id.hex in sql
    assert "client_manager_group_assignments.is_active IS true" in sql
    assert "client_manager_group_assignments.revoked_at IS NULL" in sql


@pytest.mark.asyncio
async def test_incident_retry_returns_durable_receipt_without_duplicate_insert() -> None:
    claims = _claims()
    group_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    body = MobileIncidentCreateRequest(
        client_event_id=uuid.uuid4(),
        title="Transport delay",
        description="The airport transfer is delayed by twenty minutes.",
        severity="medium",
        occurred_at=datetime.now(tz=UTC),
    )
    request_hash = hashlib.sha256(
        json.dumps(
            body.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    insert_result = MagicMock()
    insert_result.scalar_one_or_none.return_value = None
    receipt = SimpleNamespace(
        request_hash=request_hash,
        status="completed",
        resource_id=incident_id,
    )
    receipt_result = MagicMock()
    receipt_result.scalar_one_or_none.return_value = receipt
    session = MagicMock()
    session.execute = AsyncMock(side_effect=[insert_result, receipt_result])
    request = MagicMock(client=None)

    with patch(
        "app.presentation.api.v1.routes.mobile_ops._require_coordinator_trip",
        new=AsyncMock(return_value=SimpleNamespace(access=SimpleNamespace(id=uuid.uuid4()))),
    ):
        response = await create_mobile_incident(
            group_id=group_id,
            body=body,
            request=request,
            claims=claims,
            session=session,
        )

    assert response.status == "already_applied"
    assert response.incident_id == incident_id
    assert session.execute.await_count == 2
