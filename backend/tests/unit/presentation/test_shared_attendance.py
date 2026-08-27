from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.domain.entities.entities import User, UserRole
from app.presentation.api.v1.routes import (
    tour_operations,
    tour_operations_attendance_scan_support,
)
from app.presentation.api.v1.schemas.attendance_closeout_schemas import (
    AttendanceCloseoutCheckpointRequest,
    AttendanceCloseoutCoordinatorStatusResponse,
    AttendanceCloseoutStatusResponse,
    AttendanceCloseRequest,
)
from app.presentation.api.v1.schemas.tour_operations_schemas import (
    AttendanceScanRequest,
    CreateAttendanceSessionRequest,
)


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one(self) -> object:
        return self._value

    def scalar_one_or_none(self) -> object:
        return self._value


class _FirstResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def first(self) -> object:
        return self._value


class _OneResult:
    def __init__(self, value: tuple[object, ...]) -> None:
        self._value = value

    def one(self) -> tuple[object, ...]:
        return self._value


class _RowsResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows

    def scalars(self) -> _RowsResult:
        return self


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


def _coordinator(agency_id: uuid.UUID) -> User:
    return User(
        id=uuid.uuid4(),
        email="coordinator@example.test",
        hashed_password="hash",
        full_name="Coordinator",
        role=UserRole.AGENCY_COORDINATOR,
        agency_id=agency_id,
    )


def _super_admin() -> User:
    return User(
        id=uuid.uuid4(),
        email="admin@example.test",
        hashed_password="hash",
        full_name="Super Admin",
        role=UserRole.SUPER_ADMIN,
        agency_id=None,
    )


def _manager(agency_id: uuid.UUID) -> User:
    return User(
        id=uuid.uuid4(),
        email="manager@example.test",
        hashed_password="hash",
        full_name="Manager",
        role=UserRole.AGENCY_MANAGER,
        agency_id=agency_id,
    )


def _staff(agency_id: uuid.UUID) -> User:
    return User(
        id=uuid.uuid4(),
        email="staff@example.test",
        hashed_password="hash",
        full_name="Staff",
        role=UserRole.AGENCY_STAFF,
        agency_id=agency_id,
    )


@pytest.mark.parametrize("name", ["  ", " a "])
def test_attendance_activity_name_is_validated_after_whitespace_normalization(
    name: str,
) -> None:
    with pytest.raises(ValidationError, match="at least 2 characters"):
        CreateAttendanceSessionRequest(name=name)


def test_web_attendance_scan_timestamp_requires_timezone() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        AttendanceScanRequest(
            qr_payload=f"pdatt:{'A' * 43}",
            client_event_id="naive-scan-time",
            scanned_at=datetime.now(),
            sync_source="offline",
        )


def test_completed_shared_activity_remains_scannable_for_other_coordinators() -> None:
    assert "completed" in tour_operations.SCANNABLE_ATTENDANCE_STATUSES
    assert (
        tour_operations._counted_attendance_message(  # noqa: SLF001
            "completed",
            "Asha",
        )
        == "Asha counted as a late scan after completion."
    )


def test_close_window_accepts_pre_close_queue_time_but_rejects_fresh_capture() -> None:
    completed_at = datetime.now(tz=UTC)
    activity = SimpleNamespace(
        started_at=completed_at - timedelta(hours=1),
        completed_at=completed_at,
    )

    assert tour_operations._attendance_scan_is_within_activity_window(  # noqa: SLF001
        activity,
        completed_at - timedelta(seconds=1),
    )
    assert not tour_operations._attendance_scan_is_within_activity_window(  # noqa: SLF001
        activity,
        completed_at + timedelta(microseconds=1),
    )


def test_global_close_capability_excludes_coordinators_and_ordinary_staff() -> None:
    assert UserRole.AGENCY_COORDINATOR not in tour_operations.ATTENDANCE_CLOSURE_ROLES
    assert UserRole.AGENCY_STAFF not in tour_operations.ATTENDANCE_CLOSURE_ROLES
    assert set(tour_operations.ATTENDANCE_CLOSURE_ROLES) == {
        UserRole.SUPER_ADMIN,
        UserRole.AGENCY_ADMIN,
        UserRole.AGENCY_MANAGER,
    }


def test_coordinator_create_route_is_deprecated_and_manager_route_is_canonical() -> None:
    coordinator_create = next(
        route
        for route in tour_operations.router.routes
        if route.path == "/coordinator/groups/{group_id}/sessions" and "POST" in route.methods
    )
    manager_create = next(
        route
        for route in tour_operations.router.routes
        if route.path == "/groups/{group_id}/attendance/sessions" and "POST" in route.methods
    )

    assert coordinator_create.deprecated is True
    assert manager_create.deprecated is not True


@pytest.mark.asyncio
async def test_legacy_coordinator_close_is_forbidden_without_a_shared_state_write() -> None:
    with pytest.raises(HTTPException) as caught:
        await tour_operations.complete_my_attendance_session(
            session_id=uuid.uuid4(),
            current_user=_coordinator(uuid.uuid4()),
        )

    assert caught.value.status_code == 403
    assert "manager or administrator" in caught.value.detail


@pytest.mark.asyncio
async def test_legacy_coordinator_create_is_forbidden_without_an_activity_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agency_id = uuid.uuid4()
    ensure_group = AsyncMock()
    session = SimpleNamespace(execute=AsyncMock(), scalar=AsyncMock(), flush=AsyncMock())
    monkeypatch.setattr(
        tour_operations,
        "_ensure_group_assigned_to_coordinator",
        ensure_group,
    )

    with pytest.raises(HTTPException) as caught:
        await tour_operations.create_my_attendance_session(
            group_id=uuid.uuid4(),
            body=CreateAttendanceSessionRequest(name="Unauthorized count"),
            current_user=_coordinator(agency_id),
            session=session,  # type: ignore[arg-type]
        )

    assert caught.value.status_code == 403
    assert "manager or administrator" in caught.value.detail
    ensure_group.assert_awaited_once()
    session.execute.assert_not_awaited()
    session.scalar.assert_not_awaited()


@pytest.mark.asyncio
async def test_ordinary_staff_cannot_create_a_canonical_activity() -> None:
    agency_id = uuid.uuid4()
    session = SimpleNamespace(execute=AsyncMock(), scalar=AsyncMock(), flush=AsyncMock())

    with pytest.raises(HTTPException) as caught:
        await tour_operations.create_managed_attendance_session(
            group_id=uuid.uuid4(),
            body=CreateAttendanceSessionRequest(name="Unauthorized count"),
            request=SimpleNamespace(),  # type: ignore[arg-type]
            current_user=_staff(agency_id),
            session=session,  # type: ignore[arg-type]
        )

    assert caught.value.status_code == 403
    session.execute.assert_not_awaited()
    session.scalar.assert_not_awaited()


@pytest.mark.asyncio
async def test_web_manager_create_stages_one_durable_realtime_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    manager = _manager(agency_id)
    activity = SimpleNamespace(
        id=uuid.uuid4(),
        updated_at=datetime.now(tz=UTC),
    )
    response = SimpleNamespace(id=activity.id)
    database = SimpleNamespace()
    notify = AsyncMock()
    audit = SimpleNamespace(record=AsyncMock())
    monkeypatch.setattr(
        tour_operations,
        "_get_attendance_close_group_scope",
        AsyncMock(return_value=(agency_id, SimpleNamespace(id=group_id))),
    )
    monkeypatch.setattr(
        tour_operations,
        "_create_canonical_attendance_activity",
        AsyncMock(return_value=(activity, "created")),
    )
    monkeypatch.setattr(
        tour_operations,
        "_attendance_session_response",
        AsyncMock(return_value=response),
    )
    monkeypatch.setattr(
        tour_operations,
        "append_attendance_realtime_invalidation",
        notify,
    )
    monkeypatch.setattr(tour_operations, "AuditLogRepository", lambda _session: audit)
    monkeypatch.setattr(tour_operations, "trusted_client_ip", lambda _request: "203.0.113.9")

    result = await tour_operations.create_managed_attendance_session(
        group_id=group_id,
        body=CreateAttendanceSessionRequest(name="Airport departure"),
        request=SimpleNamespace(),  # type: ignore[arg-type]
        current_user=manager,
        session=database,  # type: ignore[arg-type]
    )

    assert result is response
    notify.assert_awaited_once_with(
        database,
        agency_id=agency_id,
        group_id=group_id,
        entity_type="attendance_session",
        entity_id=activity.id,
        changed_by_user_id=manager.id,
        occurred_at=activity.updated_at,
    )


@pytest.mark.asyncio
async def test_web_manager_idempotent_create_does_not_stage_a_false_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    manager = _manager(agency_id)
    activity = SimpleNamespace(id=uuid.uuid4(), updated_at=datetime.now(tz=UTC))
    response = SimpleNamespace(id=activity.id)
    audit = SimpleNamespace(record=AsyncMock())
    notify = AsyncMock()
    monkeypatch.setattr(
        tour_operations,
        "_get_attendance_close_group_scope",
        AsyncMock(return_value=(agency_id, SimpleNamespace(id=group_id))),
    )
    monkeypatch.setattr(
        tour_operations,
        "_create_canonical_attendance_activity",
        AsyncMock(return_value=(activity, "existing")),
    )
    monkeypatch.setattr(
        tour_operations,
        "_attendance_session_response",
        AsyncMock(return_value=response),
    )
    monkeypatch.setattr(
        tour_operations,
        "append_attendance_realtime_invalidation",
        notify,
    )
    monkeypatch.setattr(tour_operations, "AuditLogRepository", lambda _session: audit)
    monkeypatch.setattr(tour_operations, "trusted_client_ip", lambda _request: "203.0.113.9")

    result = await tour_operations.create_managed_attendance_session(
        group_id=group_id,
        body=CreateAttendanceSessionRequest(name="Airport departure"),
        request=SimpleNamespace(),  # type: ignore[arg-type]
        current_user=manager,
        session=SimpleNamespace(),  # type: ignore[arg-type]
    )

    assert result is response
    notify.assert_not_awaited()


@pytest.mark.asyncio
async def test_fresh_web_scan_is_rejected_after_manager_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agency_id = uuid.uuid4()
    completed_at = datetime.now(tz=UTC) - timedelta(minutes=1)
    activity = SimpleNamespace(
        id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        status="completed",
        started_at=completed_at - timedelta(hours=1),
        completed_at=completed_at,
    )
    lookup = AsyncMock(return_value=activity)
    resolve = AsyncMock()
    monkeypatch.setattr(tour_operations, "_get_coordinator_attendance_session", lookup)
    monkeypatch.setattr(tour_operations, "_resolve_scannable_passenger", resolve)

    with pytest.raises(HTTPException) as caught:
        await tour_operations.record_my_attendance_scan(
            session_id=activity.id,
            body=AttendanceScanRequest(
                qr_payload=f"pdatt:{'A' * 43}",
                client_event_id="fresh-after-close",
                scanned_at=datetime.now(tz=UTC),
                sync_source="online",
            ),
            request=SimpleNamespace(),  # type: ignore[arg-type]
            current_user=_coordinator(agency_id),
            session=SimpleNamespace(),  # type: ignore[arg-type]
        )

    assert caught.value.status_code == 409
    assert "saved offline scan" in caught.value.detail
    resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_pre_close_web_queue_event_can_reconcile_after_manager_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agency_id = uuid.uuid4()
    completed_at = datetime.now(tz=UTC)
    scanned_at = completed_at - timedelta(minutes=2)
    activity = SimpleNamespace(
        id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        status="completed",
        started_at=completed_at - timedelta(hours=1),
        completed_at=completed_at,
    )
    passenger = SimpleNamespace(id=uuid.uuid4(), client_name="Asha")
    insert = AsyncMock(return_value=None)
    response = SimpleNamespace(status="duplicate")
    monkeypatch.setattr(
        tour_operations,
        "_get_coordinator_attendance_session",
        AsyncMock(return_value=activity),
    )
    monkeypatch.setattr(
        tour_operations,
        "_resolve_scannable_passenger",
        AsyncMock(return_value=(passenger, None, None)),
    )
    monkeypatch.setattr(tour_operations, "_insert_canonical_attendance_record", insert)
    monkeypatch.setattr(tour_operations, "_record_qr_audit", AsyncMock())
    monkeypatch.setattr(
        tour_operations,
        "_attendance_scan_response",
        AsyncMock(return_value=response),
    )

    result = await tour_operations.record_my_attendance_scan(
        session_id=activity.id,
        body=AttendanceScanRequest(
            qr_payload=f"pdatt:{'A' * 43}",
            client_event_id="queued-before-close",
            scanned_at=scanned_at,
            sync_source="offline",
        ),
        request=SimpleNamespace(),  # type: ignore[arg-type]
        current_user=_coordinator(agency_id),
        session=SimpleNamespace(),  # type: ignore[arg-type]
    )

    assert result is response
    insert.assert_awaited_once()
    assert insert.await_args.kwargs["scanned_at"] == scanned_at
    assert insert.await_args.kwargs["sync_source"] == "offline"


@pytest.mark.asyncio
async def test_authorized_close_is_idempotent_and_preserves_late_scan_policy() -> None:
    now = datetime.now(tz=UTC)
    activity = SimpleNamespace(
        status="active",
        completed_at=None,
        updated_at=now - timedelta(minutes=1),
    )
    session = SimpleNamespace(flush=AsyncMock())

    changed = await tour_operations._close_shared_attendance_activity(  # noqa: SLF001
        session,  # type: ignore[arg-type]
        activity,
    )

    assert changed is True
    assert activity.status == "completed"
    assert activity.completed_at is not None
    assert activity.updated_at == activity.completed_at
    session.flush.assert_awaited_once()
    assert "completed" in tour_operations.SCANNABLE_ATTENDANCE_STATUSES

    changed_again = await tour_operations._close_shared_attendance_activity(  # noqa: SLF001
        session,  # type: ignore[arg-type]
        activity,
    )
    assert changed_again is False
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_global_close_rejects_non_active_state_without_reinterpretation() -> None:
    activity = SimpleNamespace(status="draft", completed_at=None, updated_at=None)
    session = SimpleNamespace(flush=AsyncMock())

    with pytest.raises(HTTPException) as caught:
        await tour_operations._close_shared_attendance_activity(  # noqa: SLF001
            session,  # type: ignore[arg-type]
            activity,
        )

    assert caught.value.status_code == 409
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_agency_manager_close_uses_scoped_locked_activity_and_audits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    activity = SimpleNamespace(
        id=uuid.uuid4(),
        status="active",
        updated_at=datetime.now(tz=UTC),
    )
    manager = User(
        id=uuid.uuid4(),
        email="manager@example.test",
        hashed_password="hash",
        full_name="Manager",
        role=UserRole.AGENCY_MANAGER,
        agency_id=agency_id,
    )
    expected = SimpleNamespace(scanned_count=794, assigned_count=800)
    database = SimpleNamespace()
    close_scope = AsyncMock(return_value=(agency_id, SimpleNamespace(id=group_id)))
    lookup = AsyncMock(return_value=activity)
    close = AsyncMock(return_value=True)
    closeout = _closeout_response()
    load_closeout = AsyncMock(return_value=closeout)
    build_response = AsyncMock(return_value=expected)
    audit = SimpleNamespace(record=AsyncMock())
    notify = AsyncMock()
    monkeypatch.setattr(tour_operations, "_get_attendance_close_group_scope", close_scope)
    monkeypatch.setattr(tour_operations, "_get_managed_attendance_session", lookup)
    monkeypatch.setattr(tour_operations, "_close_shared_attendance_activity", close)
    monkeypatch.setattr(tour_operations, "_load_attendance_closeout_status", load_closeout)
    monkeypatch.setattr(tour_operations, "_attendance_session_response", build_response)
    monkeypatch.setattr(tour_operations, "AuditLogRepository", lambda _session: audit)
    monkeypatch.setattr(tour_operations, "trusted_client_ip", lambda _request: "203.0.113.11")
    monkeypatch.setattr(
        tour_operations,
        "append_attendance_realtime_invalidation",
        notify,
    )

    response = await tour_operations.complete_managed_attendance_session(
        group_id=group_id,
        session_id=activity.id,
        request=SimpleNamespace(),  # type: ignore[arg-type]
        current_user=manager,
        session=database,  # type: ignore[arg-type]
    )

    assert response is expected
    close_scope.assert_awaited_once_with(
        database,
        group_id=group_id,
        current_user=manager,
        lock_for_update=True,
    )
    lookup.assert_awaited_once_with(
        database,
        agency_id=agency_id,
        group_id=group_id,
        session_id=activity.id,
    )
    close.assert_awaited_once_with(database, activity)
    notify.assert_awaited_once_with(
        database,
        agency_id=agency_id,
        group_id=group_id,
        entity_type="attendance_session",
        entity_id=activity.id,
        changed_by_user_id=manager.id,
        occurred_at=activity.updated_at,
    )
    audit.record.assert_awaited_once()
    metadata = audit.record.await_args.kwargs["metadata"]
    assert metadata == {
        "group_id": str(group_id),
        "server_scanned_count": 794,
        "assigned_count": 800,
        "late_offline_reconciliation_allowed": True,
        "closeout": tour_operations._attendance_closeout_audit_metadata(  # noqa: SLF001
            closeout,
            exception_used=False,
            exception_reason=None,
        ),
    }


@pytest.mark.asyncio
async def test_idempotent_manager_close_does_not_stage_a_false_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    manager = _manager(agency_id)
    activity = SimpleNamespace(id=uuid.uuid4(), status="completed")
    response = SimpleNamespace(scanned_count=800, assigned_count=800)
    database = SimpleNamespace()
    notify = AsyncMock()
    audit = SimpleNamespace(record=AsyncMock())
    monkeypatch.setattr(
        tour_operations,
        "_get_attendance_close_group_scope",
        AsyncMock(return_value=(agency_id, SimpleNamespace(id=group_id))),
    )
    monkeypatch.setattr(
        tour_operations,
        "_get_managed_attendance_session",
        AsyncMock(return_value=activity),
    )
    monkeypatch.setattr(
        tour_operations,
        "_close_shared_attendance_activity",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        tour_operations,
        "_attendance_session_response",
        AsyncMock(return_value=response),
    )
    monkeypatch.setattr(
        tour_operations,
        "append_attendance_realtime_invalidation",
        notify,
    )
    monkeypatch.setattr(tour_operations, "AuditLogRepository", lambda _session: audit)

    result = await tour_operations.complete_managed_attendance_session(
        group_id=group_id,
        session_id=activity.id,
        request=SimpleNamespace(),  # type: ignore[arg-type]
        current_user=manager,
        session=database,  # type: ignore[arg-type]
    )

    assert result is response
    notify.assert_not_awaited()
    audit.record.assert_not_awaited()


@pytest.mark.asyncio
async def test_web_manager_close_fails_closed_for_missing_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    activity = SimpleNamespace(
        id=uuid.uuid4(),
        status="active",
        updated_at=datetime.now(tz=UTC),
    )
    close = AsyncMock()
    build_response = AsyncMock()
    monkeypatch.setattr(
        tour_operations,
        "_get_attendance_close_group_scope",
        AsyncMock(return_value=(agency_id, SimpleNamespace(id=group_id))),
    )
    monkeypatch.setattr(
        tour_operations,
        "_get_managed_attendance_session",
        AsyncMock(return_value=activity),
    )
    monkeypatch.setattr(
        tour_operations,
        "_load_attendance_closeout_status",
        AsyncMock(return_value=_closeout_response("missing")),
    )
    monkeypatch.setattr(tour_operations, "_close_shared_attendance_activity", close)
    monkeypatch.setattr(tour_operations, "_attendance_session_response", build_response)

    with pytest.raises(HTTPException) as caught:
        await tour_operations.complete_managed_attendance_session(
            group_id=group_id,
            session_id=activity.id,
            request=SimpleNamespace(),  # type: ignore[arg-type]
            current_user=_manager(agency_id),
            session=SimpleNamespace(),  # type: ignore[arg-type]
        )

    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "ATTENDANCE_CLOSEOUT_BLOCKED"
    assert caught.value.detail["closeout"]["coordinators"][0]["state"] == "missing"
    close.assert_not_awaited()
    build_response.assert_not_awaited()


@pytest.mark.asyncio
async def test_web_manager_exception_is_bounded_and_durably_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    activity = SimpleNamespace(
        id=uuid.uuid4(),
        status="active",
        updated_at=datetime.now(tz=UTC),
    )
    closeout = _closeout_response("blocked", pending_count=2)
    response = SimpleNamespace(scanned_count=798, assigned_count=800)
    audit = SimpleNamespace(record=AsyncMock())
    notify = AsyncMock()
    database = SimpleNamespace(commit=AsyncMock())
    request = SimpleNamespace(
        state=SimpleNamespace(
            auth_claims={
                "amr": ["totp"],
                "mfa_at": datetime.now(tz=UTC).timestamp(),
            }
        )
    )
    monkeypatch.setattr(
        tour_operations,
        "_get_attendance_close_group_scope",
        AsyncMock(return_value=(agency_id, SimpleNamespace(id=group_id))),
    )
    monkeypatch.setattr(
        tour_operations,
        "_get_managed_attendance_session",
        AsyncMock(return_value=activity),
    )
    monkeypatch.setattr(
        tour_operations,
        "_load_attendance_closeout_status",
        AsyncMock(return_value=closeout),
    )
    monkeypatch.setattr(
        tour_operations,
        "_close_shared_attendance_activity",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(
        tour_operations,
        "_attendance_session_response",
        AsyncMock(return_value=response),
    )
    monkeypatch.setattr(tour_operations, "AuditLogRepository", lambda _session: audit)
    monkeypatch.setattr(tour_operations, "trusted_client_ip", lambda _request: "203.0.113.12")
    monkeypatch.setattr(
        tour_operations,
        "append_attendance_realtime_invalidation",
        notify,
    )

    result = await tour_operations.complete_managed_attendance_session(
        group_id=group_id,
        session_id=activity.id,
        request=request,
        current_user=_manager(agency_id),
        session=database,
        body=AttendanceCloseRequest(
            exception_reason="approved transport emergency override",
        ),
    )

    assert result is response
    notify.assert_awaited_once()
    database.commit.assert_not_awaited()
    closeout_audit = audit.record.await_args.kwargs["metadata"]["closeout"]
    assert closeout_audit["exception_used"] is True
    assert closeout_audit["exception_reason"] == "approved transport emergency override"
    assert closeout_audit["unresolved_count"] == 2
    assert set(closeout_audit["coordinators"][0]) == {
        "coordinator_id",
        "runtime_id",
        "runtime_kind",
        "runtime_status",
        "state",
        "reported_at",
        "pending_count",
        "sending_count",
        "retryable_count",
        "needs_review_count",
        "unreviewed_rejected_count",
        "oldest_pending_age_seconds",
    }


@pytest.mark.asyncio
async def test_web_coordinator_checkpoint_uses_authenticated_identity_and_shared_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    coordinator = _coordinator(agency_id)
    activity = SimpleNamespace(id=uuid.uuid4(), group_id=group_id, status="active")
    ensure_assignment = AsyncMock()
    lookup = AsyncMock(return_value=activity)
    checkpoint = SimpleNamespace(reported_at=datetime.now(tz=UTC))
    repository = SimpleNamespace(publish=AsyncMock(return_value=checkpoint))
    database = SimpleNamespace()
    notify = AsyncMock()
    monkeypatch.setattr(
        tour_operations,
        "_ensure_group_assigned_to_coordinator",
        ensure_assignment,
    )
    monkeypatch.setattr(
        tour_operations,
        "_get_coordinator_attendance_session",
        lookup,
    )
    monkeypatch.setattr(
        tour_operations,
        "AttendanceCloseoutRepository",
        lambda _session: repository,
    )
    monkeypatch.setattr(
        tour_operations,
        "append_attendance_realtime_invalidation",
        notify,
    )
    body = AttendanceCloseoutCheckpointRequest(
        pending_count=0,
        sending_count=0,
        retryable_count=0,
        needs_review_count=0,
        unreviewed_rejected_count=1,
        oldest_pending_age_seconds=None,
    )

    response = await tour_operations.publish_my_attendance_closeout_checkpoint(
        group_id=group_id,
        session_id=activity.id,
        body=body,
        request=SimpleNamespace(cookies={}),
        current_user=coordinator,
        session=database,  # type: ignore[arg-type]
    )

    ensure_assignment.assert_awaited_once()
    lookup.assert_awaited_once_with(
        database,
        agency_id,
        activity.id,
        coordinator.id,
        lock_for_scan=True,
    )
    assert repository.publish.await_args.kwargs["coordinator_user_id"] == coordinator.id
    notify.assert_awaited_once_with(
        database,
        agency_id=agency_id,
        group_id=group_id,
        entity_type="attendance_checkpoint",
        entity_id=activity.id,
        changed_by_user_id=coordinator.id,
        occurred_at=checkpoint.reported_at,
    )
    assert response.unreviewed_rejected_count == 1


@pytest.mark.asyncio
async def test_agencyless_super_admin_resolves_target_tenant_before_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agency_id = uuid.uuid4()
    group = SimpleNamespace(id=uuid.uuid4(), agency_id=agency_id)
    database = SimpleNamespace(execute=AsyncMock(return_value=_ScalarResult(group)))
    authorization = SimpleNamespace(require_assign_coordinator=AsyncMock())
    monkeypatch.setattr(
        tour_operations,
        "AuthorizationPolicy",
        lambda _session: authorization,
    )

    resolved_agency, resolved_group = await tour_operations._get_attendance_close_group_scope(  # noqa: SLF001
        database,  # type: ignore[arg-type]
        group_id=group.id,
        current_user=_super_admin(),
    )

    assert resolved_agency == agency_id
    assert resolved_group is group
    authorization.require_assign_coordinator.assert_awaited_once()


@pytest.mark.asyncio
async def test_attendance_counts_use_full_group_and_shared_session() -> None:
    session = SimpleNamespace(execute=AsyncMock(return_value=_OneResult((700, 123))))
    session_id = uuid.uuid4()
    group_id = uuid.uuid4()

    counts = await tour_operations._attendance_counts(  # noqa: SLF001
        session,  # type: ignore[arg-type]
        session_id,
        group_id,
    )

    assert counts == {"assigned": 700, "scanned": 123}
    counts_sql = str(
        session.execute.await_args.args[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "passport_submissions.group_id" in counts_sql
    assert "coordinator_assignments" not in counts_sql
    assert "attendance_records.session_id" in counts_sql
    assert "attendance_records.coordinator_user_id" not in counts_sql
    assert "attendance_session_family.canonical_session_id" in counts_sql
    assert "count(distinct(attendance_records.passenger_id))" in counts_sql.lower()


@pytest.mark.asyncio
async def test_alias_session_id_resolves_to_canonical_activity() -> None:
    agency_id = uuid.uuid4()
    alias_id = uuid.uuid4()
    coordinator_id = uuid.uuid4()
    canonical = SimpleNamespace(id=uuid.uuid4())
    session = SimpleNamespace(
        execute=AsyncMock(return_value=_ScalarResult(canonical)),
    )

    resolved = await tour_operations._get_coordinator_attendance_session(  # noqa: SLF001
        session,  # type: ignore[arg-type]
        agency_id,
        alias_id,
        coordinator_id,
        lock_for_scan=True,
    )

    assert resolved is canonical
    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert (
        "requested_attendance_session.canonical_session_id = canonical_attendance_session.id" in sql
    )
    assert "requested_attendance_session.id" in sql
    assert "canonical_attendance_session.agency_id" in sql
    assert "FOR SHARE OF canonical_attendance_session" in sql


@pytest.mark.asyncio
async def test_family_insert_is_atomic_and_targets_canonical_session() -> None:
    canonical_id = uuid.uuid4()
    passenger_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    coordinator_id = uuid.uuid4()
    session = SimpleNamespace(
        execute=AsyncMock(return_value=_ScalarResult(None)),
    )

    inserted = await tour_operations._insert_canonical_attendance_record(  # noqa: SLF001
        session=session,  # type: ignore[arg-type]
        agency_id=agency_id,
        attendance_session=SimpleNamespace(id=canonical_id),
        passenger_id=passenger_id,
        coordinator_user_id=coordinator_id,
        scanned_at=datetime.now(tz=UTC),
        sync_source="offline",
        client_event_id="queued-alias-event",
        device_id="bus-one",
    )

    assert inserted is None
    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "INSERT INTO attendance_records" in sql
    assert "WHERE NOT (EXISTS" in sql
    assert "attendance_session_family.canonical_session_id" in sql
    assert "attendance_records.passenger_id" in sql
    assert "attendance_records.client_event_id" in sql
    assert "ON CONFLICT DO NOTHING" in sql
    assert "AS attendance_scan_source_enum)" in sql
    assert "AS VARCHAR(128))" in sql
    assert canonical_id in compiled.params.values()


@pytest.mark.asyncio
async def test_counted_scan_stages_attendance_hint_in_the_same_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical_id = uuid.uuid4()
    group_id = uuid.uuid4()
    passenger_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    coordinator_id = uuid.uuid4()
    record_id = uuid.uuid4()
    observed = datetime.now(tz=UTC)
    session = SimpleNamespace(
        execute=AsyncMock(return_value=_ScalarResult(record_id)),
    )
    append_change = AsyncMock()
    monkeypatch.setattr(
        tour_operations_attendance_scan_support,
        "append_attendance_realtime_change",
        append_change,
    )

    inserted = await tour_operations._insert_canonical_attendance_record(  # noqa: SLF001
        session=session,  # type: ignore[arg-type]
        agency_id=agency_id,
        attendance_session=SimpleNamespace(id=canonical_id, group_id=group_id),
        passenger_id=passenger_id,
        coordinator_user_id=coordinator_id,
        scanned_at=observed,
        sync_source="online",
        client_event_id="browser-event",
        device_id=None,
    )

    assert inserted == record_id
    append_change.assert_awaited_once_with(
        session,
        agency_id=agency_id,
        group_id=group_id,
        attendance_record_id=record_id,
        coordinator_user_id=coordinator_id,
        occurred_at=observed,
    )


@pytest.mark.asyncio
async def test_shared_session_list_hides_alias_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    session = SimpleNamespace(execute=AsyncMock(return_value=_RowsResult([])))
    ensure_group = AsyncMock()
    monkeypatch.setattr(
        tour_operations,
        "_ensure_group_assigned_to_coordinator",
        ensure_group,
    )

    response = await tour_operations.list_my_attendance_sessions(
        group_id=group_id,
        current_user=_coordinator(agency_id),
        session=session,  # type: ignore[arg-type]
    )

    assert response == []
    sql = str(
        session.execute.await_args.args[0].compile(
            dialect=postgresql.dialect(),
        )
    )
    assert "attendance_sessions.id = attendance_sessions.canonical_session_id" in sql


@pytest.mark.asyncio
async def test_details_dedupe_family_scans_by_passenger() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    canonical_id = uuid.uuid4()
    attendance_session = SimpleNamespace(
        id=canonical_id,
        agency_id=agency_id,
        group_id=group_id,
        name="Boarding",
        status="active",
        created_at=datetime.now(tz=UTC),
        started_at=datetime.now(tz=UTC),
        completed_at=None,
    )
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _OneResult((700, 123)),
                _RowsResult([]),
            ]
        )
    )

    response = await tour_operations._attendance_session_details_response(  # noqa: SLF001
        session,  # type: ignore[arg-type]
        attendance_session,
    )

    assert response.scanned_count == 123
    details_sql = str(
        session.execute.await_args_list[1]
        .args[0]
        .compile(
            dialect=postgresql.dialect(),
        )
    )
    assert "attendance_session_family.canonical_session_id" in details_sql
    assert "GROUP BY attendance_records.passenger_id" in details_sql


@pytest.mark.asyncio
async def test_admin_overview_dedupes_alias_passengers_and_attribution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    canonical_id = uuid.uuid4()
    coordinator_one = uuid.uuid4()
    coordinator_two = uuid.uuid4()
    passenger_one = uuid.uuid4()
    passenger_two = uuid.uuid4()
    now = datetime.now(tz=UTC)
    activity = SimpleNamespace(
        id=canonical_id,
        name="Boarding",
        status="active",
        created_at=now,
        started_at=now,
        completed_at=None,
    )
    scanned_rows = [
        SimpleNamespace(
            canonical_session_id=canonical_id,
            passenger_id=passenger_one,
            coordinator_user_id=coordinator_one,
        ),
        SimpleNamespace(
            canonical_session_id=canonical_id,
            passenger_id=passenger_one,
            coordinator_user_id=coordinator_two,
        ),
        SimpleNamespace(
            canonical_session_id=canonical_id,
            passenger_id=passenger_two,
            coordinator_user_id=coordinator_two,
        ),
    ]
    passenger_rows = [
        SimpleNamespace(
            passenger_id=passenger_one,
            client_name="Asha",
            client_email=None,
            client_phone=None,
            departure_city=None,
        ),
        SimpleNamespace(
            passenger_id=passenger_two,
            client_name="Ravi",
            client_email=None,
            client_phone=None,
            departure_city=None,
        ),
    ]
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _RowsResult([activity]),
                _RowsResult(
                    [
                        SimpleNamespace(
                            coordinator_user_id=coordinator_one,
                            full_name="One",
                        ),
                        SimpleNamespace(
                            coordinator_user_id=coordinator_two,
                            full_name="Two",
                        ),
                    ]
                ),
                _ScalarResult(2),
                _RowsResult(scanned_rows),
                _RowsResult(passenger_rows),
            ]
        )
    )
    closeout = _closeout_response()
    closeout_repository = SimpleNamespace(statuses=AsyncMock(return_value={canonical_id: closeout}))
    monkeypatch.setattr(
        tour_operations,
        "AttendanceCloseoutRepository",
        lambda _session: closeout_repository,
    )

    response = await tour_operations._group_attendance_overview(  # noqa: SLF001
        session,  # type: ignore[arg-type]
        agency_id,
        SimpleNamespace(id=group_id, name="Group"),
    )

    assert len(response.sessions) == 1
    summary = response.sessions[0]
    assert summary.id == canonical_id
    assert summary.scanned_count == 2
    assert summary.closeout.ready is True
    assert summary.missing_passengers == []
    assert {item.coordinator_id: item.scanned_count for item in summary.coordinators} == {
        coordinator_one: 1,
        coordinator_two: 1,
    }
    sessions_sql = str(
        session.execute.await_args_list[0]
        .args[0]
        .compile(
            dialect=postgresql.dialect(),
        )
    )
    records_sql = str(
        session.execute.await_args_list[3]
        .args[0]
        .compile(
            dialect=postgresql.dialect(),
        )
    )
    assert "attendance_sessions.id = attendance_sessions.canonical_session_id" in sessions_sql
    assert "attendance_session_family.canonical_session_id" in records_sql


@pytest.mark.asyncio
async def test_any_group_passenger_qr_resolves_without_individual_assignment() -> None:
    group_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    passenger = SimpleNamespace(id=uuid.uuid4(), group_id=group_id)
    token = SimpleNamespace(
        revoked_at=None,
        expires_at=datetime.now(tz=UTC) + timedelta(hours=1),
        is_active=True,
    )
    session = SimpleNamespace(execute=AsyncMock(return_value=_FirstResult((passenger, token))))

    resolved, resolved_token, rejection = await tour_operations._resolve_scannable_passenger(  # noqa: SLF001
        session=session,
        agency_id=agency_id,
        group_id=group_id,
        qr_payload="pdatt:" + ("a" * 43),
    )

    assert resolved is passenger
    assert resolved_token is token
    assert rejection is None
    assert session.execute.await_count == 1


@pytest.mark.asyncio
async def test_manager_creation_generates_one_tenant_scoped_canonical_uuid() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    inserted_id = uuid.uuid4()
    canonical = SimpleNamespace(
        id=inserted_id,
        group_id=group_id,
        normalized_name="after lunch count",
        canonical_session_id=inserted_id,
        status="active",
    )
    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[group_id, None, 0]),
        execute=AsyncMock(side_effect=[_ScalarResult(inserted_id), _ScalarResult(canonical)]),
        flush=AsyncMock(),
    )

    attendance_session, outcome = await tour_operations._create_canonical_attendance_activity(  # noqa: SLF001
        session=session,  # type: ignore[arg-type]
        agency_id=agency_id,
        group_id=group_id,
        name="  After   Lunch Count ",
        created_by_user_id=_manager(agency_id).id,
    )

    insert_statement = session.execute.await_args_list[0].args[0]
    insert_compiled = insert_statement.compile(dialect=postgresql.dialect())
    insert_sql = str(insert_compiled)
    lookup_compiled = (
        session.execute.await_args_list[1]
        .args[0]
        .compile(
            dialect=postgresql.dialect(),
        )
    )
    lock_sql = str(
        session.scalar.await_args_list[0]
        .args[0]
        .compile(
            dialect=postgresql.dialect(),
        )
    )
    assert "ON CONFLICT DO NOTHING" in insert_sql
    assert insert_compiled.params["name"] == "After Lunch Count"
    assert insert_compiled.params["normalized_name"] == "after lunch count"
    assert insert_compiled.params["canonical_session_id"] == insert_compiled.params["id"]
    assert "attendance_sessions.id = attendance_sessions.canonical_session_id" in str(
        lookup_compiled
    )
    assert "client_groups.agency_id" in lock_sql
    assert "client_groups.deleted_at IS NULL" in lock_sql
    assert "FOR UPDATE" in lock_sql
    assert attendance_session is canonical
    assert outcome == "created"


@pytest.mark.asyncio
async def test_manager_same_name_retry_reuses_stable_open_activity_id() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    canonical_id = uuid.uuid4()
    canonical = SimpleNamespace(
        id=canonical_id,
        group_id=group_id,
        canonical_session_id=canonical_id,
        status="active",
    )
    session = SimpleNamespace(
        scalar=AsyncMock(side_effect=[group_id, canonical_id]),
        execute=AsyncMock(return_value=_ScalarResult(canonical)),
        flush=AsyncMock(),
    )

    attendance_session, outcome = await tour_operations._create_canonical_attendance_activity(  # noqa: SLF001
        session=session,  # type: ignore[arg-type]
        agency_id=agency_id,
        group_id=group_id,
        name="After Lunch Count",
        created_by_user_id=uuid.uuid4(),
    )

    assert attendance_session.id == canonical_id
    assert outcome == "existing"
    assert session.scalar.await_count == 2
    assert session.execute.await_count == 1
    session.flush.assert_not_awaited()
