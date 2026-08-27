from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories.attendance_dashboard_repository import (
    MAX_ATTENDANCE_SUMMARY_COORDINATORS,
    AttendanceDashboardRepository,
)


class _Scalars:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def all(self) -> list[object]:
        return self._values


class _Result:
    def __init__(
        self,
        *,
        scalars: list[object] | None = None,
        one: object | None = None,
        rows: list[object] | None = None,
    ) -> None:
        self._scalars = scalars or []
        self._one = one
        self._rows = rows or []

    def scalars(self) -> _Scalars:
        return _Scalars(self._scalars)

    def one(self) -> object:
        assert self._one is not None
        return self._one

    def all(self) -> list[object]:
        return self._rows


class _Session:
    def __init__(self, results: list[_Result]) -> None:
        self._results = results
        self.statements: list[object] = []

    async def execute(self, statement: object) -> _Result:
        self.statements.append(statement)
        return self._results.pop(0)


@pytest.mark.asyncio
async def test_group_summary_query_count_is_fixed_and_never_selects_passenger_pii() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    session_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    session = _Session(
        [
            _Result(
                scalars=[
                    SimpleNamespace(
                        id=session_id,
                        name="Airport reporting",
                        status="active",
                        created_at=now,
                        started_at=now,
                        completed_at=None,
                        updated_at=now,
                    )
                ]
            ),
            _Result(
                one=SimpleNamespace(
                    passenger_count=800,
                    latest_updated_at=now,
                    latest_passenger_key=str(uuid.uuid4()),
                )
            ),
            _Result(
                rows=[
                    SimpleNamespace(
                        canonical_session_id=session_id,
                        present_count=745,
                        record_count=760,
                        latest_record_created_at=now,
                    )
                ]
            ),
        ]
    )

    aggregate = await AttendanceDashboardRepository(cast(AsyncSession, session)).group_aggregate(
        agency_id=agency_id, group_id=group_id
    )

    assert len(session.statements) == 3
    assert aggregate.roster.passenger_count == 800
    assert aggregate.activities[0].present_count == 745
    compiled = "\n".join(str(statement).lower() for statement in session.statements)
    for forbidden in (
        "client_email",
        "client_phone",
        "departure_city",
        "family_group",
        "passport_number",
    ):
        assert forbidden not in compiled


@pytest.mark.asyncio
async def test_coordinator_counts_are_first_scan_only_and_input_bounded() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    session_id = uuid.uuid4()
    coordinator_id = uuid.uuid4()
    session = _Session(
        [
            _Result(
                rows=[
                    SimpleNamespace(
                        canonical_session_id=session_id,
                        coordinator_user_id=coordinator_id,
                        scanned_count=123,
                    )
                ]
            )
        ]
    )
    repository = AttendanceDashboardRepository(cast(AsyncSession, session))

    rows = await repository.coordinator_scan_counts(
        agency_id=agency_id,
        group_id=group_id,
        session_ids=(session_id,),
        coordinator_ids=(coordinator_id,),
    )

    assert rows[0].scanned_count == 123
    assert len(session.statements) == 1
    statement = str(session.statements[0]).lower()
    assert "row_number() over" in statement
    assert "logical_scan_rank" in statement
    assert "coordinator_user_id" in statement
    for forbidden in (
        "client_name",
        "client_email",
        "client_phone",
        "departure_city",
        "passport_number",
    ):
        assert forbidden not in statement

    with pytest.raises(ValueError, match="limit exceeded"):
        await repository.coordinator_scan_counts(
            agency_id=agency_id,
            group_id=group_id,
            session_ids=(session_id,),
            coordinator_ids=tuple(
                uuid.uuid4()
                for _ in range(MAX_ATTENDANCE_SUMMARY_COORDINATORS + 1)
            ),
        )
    assert len(session.statements) == 1


@pytest.mark.asyncio
async def test_missing_page_uses_limit_plus_one_and_minimal_keyset_projection() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    session_id = uuid.uuid4()
    passenger_ids = [uuid.UUID(int=index + 1) for index in range(51)]
    session = _Session(
        [
            _Result(
                rows=[
                    SimpleNamespace(
                        passenger_id=passenger_id,
                        display_name=f"Passenger {index}",
                    )
                    for index, passenger_id in enumerate(passenger_ids)
                ]
            )
        ]
    )

    page = await AttendanceDashboardRepository(cast(AsyncSession, session)).missing_passengers(
        agency_id=agency_id,
        group_id=group_id,
        canonical_session_id=session_id,
        cursor=None,
        limit=50,
        search="50%_off\\name",
    )

    assert len(session.statements) == 1
    assert len(page.items) == 50
    assert page.has_more is True
    assert page.next_cursor == passenger_ids[49]
    statement = str(session.statements[0]).lower()
    assert "not (exists" in statement or "not exists" in statement
    assert "order by passport_submissions.id asc" in statement
    assert "client_email" not in statement
    assert "client_phone" not in statement
