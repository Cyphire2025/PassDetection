from __future__ import annotations

import inspect
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.domain.entities.entities import UserRole
from app.presentation.api.v1.routes.rooming import (
    _checkin_dashboard,
    _get_rooming_group,
    _get_rooming_hotel,
    export_hotel_checkins,
    export_hotel_rooming_list,
    router,
    scan_hotel_checkin,
)


class _ScalarResult:
    def __init__(self, values: list[object]) -> None:
        self._values = values

    def scalars(self) -> _ScalarResult:
        return self

    def all(self) -> list[object]:
        return self._values


class _CountingSession:
    def __init__(self, results: list[_ScalarResult]) -> None:
        self._results = iter(results)
        self.execute_count = 0

    async def execute(self, _statement: object) -> _ScalarResult:
        self.execute_count += 1
        return next(self._results)


class _OneResult:
    def __init__(self, value: object | None) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object | None:
        return self._value


class _SequenceSession:
    def __init__(self, values: list[object | None]) -> None:
        self._values = iter(values)

    async def execute(self, _statement: object) -> _OneResult:
        return _OneResult(next(self._values))


def _checkin_fixture(
    passenger_count: int,
) -> tuple[
    _CountingSession,
    SimpleNamespace,
    SimpleNamespace,
]:
    hotel_id = uuid.uuid4()
    group_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    rooms: list[SimpleNamespace] = []
    assignments: list[SimpleNamespace] = []
    passengers: list[SimpleNamespace] = []
    for index in range(passenger_count):
        room_index = index // 2
        if index % 2 == 0:
            rooms.append(
                SimpleNamespace(
                    id=uuid.uuid4(),
                    hotel_id=hotel_id,
                    room_number=str(room_index + 1),
                    room_type="twin",
                    capacity=2,
                    allocation_tag="mixed",
                )
            )
        passenger_id = uuid.uuid4()
        assignments.append(
            SimpleNamespace(
                hotel_id=hotel_id,
                room_id=rooms[room_index].id,
                passenger_id=passenger_id,
                position=(index % 2) + 1,
            )
        )
        passengers.append(
            SimpleNamespace(
                id=passenger_id,
                client_name=f"Passenger {index + 1}",
                submission_mode="single",
                family_group_id=None,
                family_head_name=None,
                family_relation=None,
            )
        )
    session = _CountingSession(
        [
            _ScalarResult(assignments),
            _ScalarResult(rooms),
            _ScalarResult(passengers),
            _ScalarResult([]),
            _ScalarResult([]),
        ]
    )
    hotel = SimpleNamespace(
        id=hotel_id,
        hotel_name="Hotel",
        group_id=group_id,
        agency_id=agency_id,
    )
    group = SimpleNamespace(
        id=group_id,
        agency_id=agency_id,
        name="Group",
    )
    return session, hotel, group


@pytest.mark.asyncio
@pytest.mark.parametrize("passenger_count", [2, 200])
async def test_checkin_dashboard_query_count_is_constant(
    passenger_count: int,
) -> None:
    session, hotel, group = _checkin_fixture(passenger_count)

    dashboard = await _checkin_dashboard(
        session,  # type: ignore[arg-type]
        hotel,  # type: ignore[arg-type]
        group,  # type: ignore[arg-type]
    )

    assert session.execute_count == 5
    assert dashboard.total_allocated_passengers == passenger_count
    assert dashboard.rooms_complete == passenger_count // 2
    assert dashboard.rooms_with_missing_occupants == passenger_count % 2
    assert len(dashboard.passengers[0].roommates) == 1


def test_every_rooming_state_mutation_requires_cookie_csrf() -> None:
    mutation_routes = [
        route
        for route in router.routes
        if route.methods & {"POST", "PUT", "PATCH", "DELETE"}
    ]
    assert len(mutation_routes) == 12
    for route in mutation_routes:
        dependencies = {
            dependency.call.__name__ for dependency in route.dependant.dependencies
        }
        assert "require_cookie_csrf" in dependencies, route.path


def test_first_checkin_serializes_on_stable_assignment_before_insert() -> None:
    source = inspect.getsource(scan_hotel_checkin)
    assignment_query = source.index("assignment_result =")
    assignment_lock = source.index(".with_for_update()", assignment_query)
    checkin_lookup = source.index("checkin_result =", assignment_query)

    assert assignment_query < assignment_lock < checkin_lookup


def test_rooming_exports_are_offloaded_from_the_async_event_loop() -> None:
    for export_route in (export_hotel_rooming_list, export_hotel_checkins):
        source = inspect.getsource(export_route)
        rollback = source.index("await session.rollback()")
        generation = source.index("await asyncio.to_thread")
        reauthorization = source.rindex("await _require_current_allocation")
        detached_generation = source[rollback:reauthorization]

        assert rollback < generation < reauthorization
        assert "membership." not in detached_generation
        assert "group.name" not in detached_generation
        assert "hotel.hotel_name" not in detached_generation


@pytest.mark.asyncio
async def test_coordinator_group_access_fails_closed_across_agencies() -> None:
    group = SimpleNamespace(id=uuid.uuid4(), agency_id=uuid.uuid4())
    coordinator = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        role=UserRole.AGENCY_COORDINATOR,
    )

    with pytest.raises(HTTPException) as denied:
        await _get_rooming_group(
            _SequenceSession([group]),  # type: ignore[arg-type]
            group.id,
            coordinator,  # type: ignore[arg-type]
        )

    assert denied.value.status_code == 403


@pytest.mark.asyncio
async def test_hotel_group_agency_mismatch_is_hidden() -> None:
    group = SimpleNamespace(id=uuid.uuid4(), agency_id=uuid.uuid4())
    hotel = SimpleNamespace(
        id=uuid.uuid4(),
        group_id=group.id,
        agency_id=uuid.uuid4(),
    )
    super_admin = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=None,
        role=UserRole.SUPER_ADMIN,
    )

    with pytest.raises(HTTPException) as denied:
        await _get_rooming_hotel(
            _SequenceSession([hotel, group]),  # type: ignore[arg-type]
            hotel.id,
            super_admin,  # type: ignore[arg-type]
        )

    assert denied.value.status_code == 404
