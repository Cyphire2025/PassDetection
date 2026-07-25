from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.domain.entities.entities import User, UserRole
from app.presentation.api.v1.routes import tour_operations
from app.presentation.api.v1.schemas.tour_operations_schemas import (
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


def _coordinator(agency_id: uuid.UUID) -> User:
    return User(
        id=uuid.uuid4(),
        email="coordinator@example.test",
        hashed_password="hash",
        full_name="Coordinator",
        role=UserRole.AGENCY_COORDINATOR,
        agency_id=agency_id,
    )


@pytest.mark.parametrize("name", ["  ", " a "])
def test_attendance_activity_name_is_validated_after_whitespace_normalization(
    name: str,
) -> None:
    with pytest.raises(ValidationError, match="at least 2 characters"):
        CreateAttendanceSessionRequest(name=name)


def test_completed_shared_activity_remains_scannable_for_other_coordinators() -> None:
    assert "completed" in tour_operations.SCANNABLE_ATTENDANCE_STATUSES
    assert tour_operations._counted_attendance_message(  # noqa: SLF001
        "completed",
        "Asha",
    ) == "Asha counted as a late scan after completion."


@pytest.mark.asyncio
async def test_attendance_counts_use_full_group_and_shared_session() -> None:
    session = SimpleNamespace(
        execute=AsyncMock(return_value=_OneResult((700, 123)))
    )
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
    )

    assert resolved is canonical
    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "requested_attendance_session.canonical_session_id = canonical_attendance_session.id" in sql
    assert "requested_attendance_session.id" in sql
    assert "canonical_attendance_session.agency_id" in sql


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
        session.execute.await_args_list[1].args[0].compile(
            dialect=postgresql.dialect(),
        )
    )
    assert "attendance_session_family.canonical_session_id" in details_sql
    assert "GROUP BY attendance_records.passenger_id" in details_sql


@pytest.mark.asyncio
async def test_admin_overview_dedupes_alias_passengers_and_attribution() -> None:
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
                _RowsResult([
                    SimpleNamespace(
                        coordinator_user_id=coordinator_one,
                        full_name="One",
                    ),
                    SimpleNamespace(
                        coordinator_user_id=coordinator_two,
                        full_name="Two",
                    ),
                ]),
                _ScalarResult(2),
                _RowsResult(scanned_rows),
                _RowsResult(passenger_rows),
            ]
        )
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
    assert summary.missing_passengers == []
    assert {
        item.coordinator_id: item.scanned_count
        for item in summary.coordinators
    } == {
        coordinator_one: 1,
        coordinator_two: 1,
    }
    sessions_sql = str(
        session.execute.await_args_list[0].args[0].compile(
            dialect=postgresql.dialect(),
        )
    )
    records_sql = str(
        session.execute.await_args_list[3].args[0].compile(
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
    session = SimpleNamespace(
        execute=AsyncMock(return_value=_FirstResult((passenger, token)))
    )

    resolved, resolved_token, rejection = (
        await tour_operations._resolve_scannable_passenger(  # noqa: SLF001
            session=session,  # type: ignore[arg-type]
            agency_id=agency_id,
            group_id=group_id,
            qr_payload="pdatt:" + ("a" * 43),
        )
    )

    assert resolved is passenger
    assert resolved_token is token
    assert rejection is None
    assert session.execute.await_count == 1


@pytest.mark.asyncio
async def test_concurrent_same_name_activity_returns_existing_shared_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    existing = SimpleNamespace(
        id=uuid.uuid4(),
        group_id=group_id,
        normalized_name="after lunch count",
        canonical_session_id=None,
        status="active",
    )
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[_ScalarResult(None), _ScalarResult(existing)]
        ),
        flush=AsyncMock(),
    )
    expected = SimpleNamespace(id=existing.id)
    ensure_group = AsyncMock()
    build_response = AsyncMock(return_value=expected)
    monkeypatch.setattr(
        tour_operations,
        "_ensure_group_assigned_to_coordinator",
        ensure_group,
    )
    monkeypatch.setattr(
        tour_operations,
        "_attendance_session_response",
        build_response,
    )

    response = await tour_operations.create_my_attendance_session(
        group_id=group_id,
        body=CreateAttendanceSessionRequest(name="  After   Lunch Count "),
        current_user=_coordinator(agency_id),
        session=session,  # type: ignore[arg-type]
    )

    insert_statement = session.execute.await_args_list[0].args[0]
    insert_compiled = insert_statement.compile(dialect=postgresql.dialect())
    insert_sql = str(insert_compiled)
    lookup_compiled = session.execute.await_args_list[1].args[0].compile(
        dialect=postgresql.dialect(),
    )
    assert "ON CONFLICT DO NOTHING" in insert_sql
    assert insert_compiled.params["name"] == "After Lunch Count"
    assert insert_compiled.params["normalized_name"] == "after lunch count"
    assert insert_compiled.params["canonical_session_id"] == insert_compiled.params["id"]
    assert "attendance_sessions.normalized_name" in str(lookup_compiled)
    assert "attendance_sessions.id = attendance_sessions.canonical_session_id" in str(lookup_compiled)
    assert "after lunch count" in lookup_compiled.params.values()
    assert ["draft", "active"] in lookup_compiled.params.values()
    assert "completed" not in lookup_compiled.params.values()
    assert response is expected
    ensure_group.assert_awaited_once()
    build_response.assert_awaited_once_with(session, existing)
