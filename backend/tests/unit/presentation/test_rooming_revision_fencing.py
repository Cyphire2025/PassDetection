from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.presentation.api.v1.routes.rooming import (
    auto_allocate_hotel_rooms,
    router,
    update_hotel_passenger_selection,
    update_hotel_vip_status,
)
from app.presentation.api.v1.routes.rooming_allocation_support import (
    advance_allocation_revisions as _advance_allocation_revisions,
)
from app.presentation.api.v1.routes.rooming_allocation_support import (
    allocation_mutation_response as _allocation_mutation_response,
)
from app.presentation.api.v1.routes.rooming_allocation_support import (
    require_expected_allocation_revisions as _require_expected_allocation_revisions,
)
from app.presentation.api.v1.schemas.rooming_schemas import (
    AutoAllocateRoomsRequest,
    RoomingAllocationMutationResponse,
    UpdateHotelPassengerSelectionRequest,
    UpdateHotelVipRequest,
)


def test_every_allocation_command_requires_a_nonnegative_revision_fence() -> None:
    passenger_id = uuid.uuid4()
    request_builders = [
        lambda revisions: UpdateHotelPassengerSelectionRequest(
            passenger_ids=[passenger_id],
            expected_allocation_revisions=revisions,
        ),
        lambda revisions: UpdateHotelVipRequest(
            passenger_ids=[passenger_id],
            is_vip=True,
            expected_allocation_revisions=revisions,
        ),
        lambda revisions: AutoAllocateRoomsRequest(
            priority_fields=[],
            expected_allocation_revisions=revisions,
        ),
    ]

    for build_request in request_builders:
        with pytest.raises(ValidationError):
            build_request({})
        with pytest.raises(ValidationError):
            build_request({uuid.uuid4(): -1})


def test_revision_fence_reports_all_current_revisions_and_missing_sources() -> None:
    target_id = uuid.uuid4()
    source_id = uuid.uuid4()
    hotels = [
        SimpleNamespace(id=target_id, allocation_revision=4),
        SimpleNamespace(id=source_id, allocation_revision=9),
    ]

    assert _require_expected_allocation_revisions(
        hotels=hotels,  # type: ignore[arg-type]
        expected={target_id: 4, source_id: 9},
    ) == {target_id: 4, source_id: 9}

    with pytest.raises(HTTPException) as conflict:
        _require_expected_allocation_revisions(
            hotels=hotels,  # type: ignore[arg-type]
            expected={target_id: 3},
        )

    ordered_ids = sorted((target_id, source_id), key=str)
    assert conflict.value.status_code == 409
    assert conflict.value.detail == {
        "code": "ROOMING_ALLOCATION_REVISION_CONFLICT",
        "message": (
            "Rooming changed in another session. The latest allocation "
            "is being refreshed; review it and try again."
        ),
        "current_revisions": {
            str(hotel_id): 4 if hotel_id == target_id else 9
            for hotel_id in ordered_ids
        },
        "conflicting_hotel_ids": [str(hotel_id) for hotel_id in ordered_ids],
    }


def test_revision_increment_is_exactly_once_per_changed_hotel() -> None:
    target = SimpleNamespace(id=uuid.uuid4(), allocation_revision=2)
    source = SimpleNamespace(id=uuid.uuid4(), allocation_revision=7)

    _advance_allocation_revisions(  # type: ignore[arg-type]
        [target, source, target]
    )

    assert target.allocation_revision == 3
    assert source.allocation_revision == 8


def test_revision_check_precedes_plan_clearing_in_every_active_command() -> None:
    for command in (
        update_hotel_passenger_selection,
        update_hotel_vip_status,
        auto_allocate_hotel_rooms,
    ):
        source = inspect.getsource(command)
        revision_check = source.index("_require_expected_allocation_revisions")
        plan_clear = source.index("_clear_room_plans")
        assert revision_check < plan_clear


def test_active_allocation_routes_return_bounded_delta_contract() -> None:
    active_paths = {
        "/hotels/{hotel_id}/passenger-selection",
        "/hotels/{hotel_id}/vip",
        "/hotels/{hotel_id}/auto-allocate",
    }
    response_models = {
        route.path: route.response_model
        for route in router.routes
        if route.path in active_paths
    }

    assert response_models == {
        path: RoomingAllocationMutationResponse for path in active_paths
    }
    assert "group_name" not in RoomingAllocationMutationResponse.model_fields
    assert "total_passengers" not in RoomingAllocationMutationResponse.model_fields
    assert "passengers" in RoomingAllocationMutationResponse.model_fields


class _ScalarRows:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> _ScalarRows:
        return self

    def all(self) -> list[object]:
        return self._rows


class _ProjectionSession:
    def __init__(self, result_rows: list[list[object]]) -> None:
        self._result_rows = iter(result_rows)
        self.execute_count = 0

    async def execute(self, _statement: object) -> _ScalarRows:
        self.execute_count += 1
        return _ScalarRows(next(self._result_rows))


@pytest.mark.asyncio
async def test_mutation_delta_projection_is_bounded_and_uses_occupant_ids() -> None:
    hotel_id = uuid.uuid4()
    passenger_id = uuid.uuid4()
    room_id = uuid.uuid4()
    hotel = SimpleNamespace(
        id=hotel_id,
        allocation_revision=6,
        allocation_fingerprint="a" * 64,
        allocation_updated_at=datetime.now(tz=UTC),
        allocation_priority_fields=[],
    )
    room = SimpleNamespace(
        id=room_id,
        hotel_id=hotel_id,
        room_number="1",
        room_type="single",
        capacity=1,
        allocation_tag="male",
        roommate_notes=None,
        is_saved=True,
        sort_order=0,
    )
    assignment = SimpleNamespace(
        hotel_id=hotel_id,
        room_id=room_id,
        passenger_id=passenger_id,
    )
    membership = SimpleNamespace(
        hotel_id=hotel_id,
        passenger_id=passenger_id,
        is_vip=False,
    )
    session = _ProjectionSession([[room], [assignment], [membership]])

    response = await _allocation_mutation_response(
        session,  # type: ignore[arg-type]
        group=SimpleNamespace(id=uuid.uuid4()),  # type: ignore[arg-type]
        changed_hotels=[hotel],  # type: ignore[list-item]
        changed_passenger_ids={passenger_id},
    )

    assert session.execute_count == 3
    assert response.changed is True
    assert response.current_revisions == {hotel_id: 6}
    assert response.hotels[0].rooms[0].occupant_ids == [passenger_id]
    assert "group_name" not in response.model_dump()
    assert "total_passengers" not in response.model_dump()
