from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.presentation.api.v1.routes.rooming import (
    _allocation_state_is_current,
    _datetime_is_after,
    _eligible_group_passengers,
    delete_room,
    generate_rooms,
    update_passenger_allocation,
    update_room,
    update_room_order,
)
from app.presentation.api.v1.schemas.rooming_schemas import (
    AutoAllocateRoomsRequest,
    CreateRoomBatchRequest,
    UpdateHotelPassengerSelectionRequest,
    UpdatePassengerAllocationRequest,
    UpdateRoomOrderRequest,
    UpdateRoomRequest,
)


def test_priority_fields_are_ordered_unique_and_limited_to_six() -> None:
    expected_revisions = {uuid.uuid4(): 0}
    request = AutoAllocateRoomsRequest(
        priority_fields=[" field:a ", "field:b"],
        expected_allocation_revisions=expected_revisions,
    )
    assert request.priority_fields == ["field:a", "field:b"]

    with pytest.raises(ValidationError, match="only once"):
        AutoAllocateRoomsRequest(
            priority_fields=["field:a", "field:a"],
            expected_allocation_revisions=expected_revisions,
        )
    with pytest.raises(ValidationError):
        AutoAllocateRoomsRequest(
            priority_fields=[f"field:{index}" for index in range(7)],
            expected_allocation_revisions=expected_revisions,
        )


def test_selection_defaults_to_safe_add_and_requires_ids_for_add_remove() -> None:
    passenger_id = uuid.uuid4()
    expected_revisions = {uuid.uuid4(): 0}
    request = UpdateHotelPassengerSelectionRequest(
        passenger_ids=[passenger_id],
        expected_allocation_revisions=expected_revisions,
    )
    assert request.mode == "add"

    with pytest.raises(ValidationError, match="require at least one"):
        UpdateHotelPassengerSelectionRequest(
            passenger_ids=[],
            mode="add",
            expected_allocation_revisions=expected_revisions,
        )
    with pytest.raises(ValidationError, match="require at least one"):
        UpdateHotelPassengerSelectionRequest(
            passenger_ids=[],
            mode="remove",
            expected_allocation_revisions=expected_revisions,
        )
    assert (
        UpdateHotelPassengerSelectionRequest(
            passenger_ids=[],
            mode="replace",
            expected_allocation_revisions=expected_revisions,
        ).mode
        == "replace"
    )


def test_selection_rejects_duplicate_passenger_ids() -> None:
    passenger_id = uuid.uuid4()
    with pytest.raises(ValidationError, match="only once"):
        UpdateHotelPassengerSelectionRequest(
            passenger_ids=[passenger_id, passenger_id],
            mode="add",
            expected_allocation_revisions={uuid.uuid4(): 0},
        )


def test_current_plan_timestamp_detects_changed_passenger_data() -> None:
    baseline = datetime.now(tz=UTC)
    assert _datetime_is_after(baseline + timedelta(seconds=1), baseline) is True
    assert _datetime_is_after(baseline, baseline) is False
    assert (
        _datetime_is_after(
            (baseline + timedelta(seconds=1)).replace(tzinfo=None),
            baseline.replace(tzinfo=None),
        )
        is True
    )


def test_workspace_current_state_requires_full_membership_assignment_and_timestamp_parity() -> None:
    passenger_id = uuid.uuid4()
    baseline = datetime.now(tz=UTC)
    hotel = SimpleNamespace(
        allocation_fingerprint="a" * 64,
        allocation_updated_at=baseline,
    )
    passenger_by_id = {
        passenger_id: SimpleNamespace(updated_at=baseline),
    }
    arguments = {
        "hotel": hotel,
        "membership_count": 1,
        "selected_ids": {passenger_id},
        "assigned_ids": {passenger_id},
        "assignment_count": 1,
        "passenger_by_id": passenger_by_id,
    }

    assert _allocation_state_is_current(**arguments) is True  # type: ignore[arg-type]
    assert (
        _allocation_state_is_current(
            **{**arguments, "membership_count": 2}  # type: ignore[arg-type]
        )
        is False
    )
    assert (
        _allocation_state_is_current(
            **{**arguments, "assigned_ids": set()}  # type: ignore[arg-type]
        )
        is False
    )
    passenger_by_id[passenger_id].updated_at = baseline + timedelta(seconds=1)
    assert _allocation_state_is_current(**arguments) is False  # type: ignore[arg-type]


class _LockedPassengerResult:
    def __init__(self, passenger: object) -> None:
        self._passenger = passenger

    def scalars(self) -> _LockedPassengerResult:
        return self

    def all(self) -> list[object]:
        return [self._passenger]


class _CapturingSession:
    def __init__(self, passenger: object) -> None:
        self.passenger = passenger
        self.statement: object | None = None

    async def execute(self, statement: object) -> _LockedPassengerResult:
        self.statement = statement
        return _LockedPassengerResult(self.passenger)


@pytest.mark.asyncio
async def test_allocation_passenger_query_uses_a_share_lock_and_locked_objects() -> None:
    group = SimpleNamespace(id=uuid.uuid4(), agency_id=uuid.uuid4())
    passenger = SimpleNamespace(id=uuid.uuid4())
    session = _CapturingSession(passenger)

    result = await _eligible_group_passengers(
        session,  # type: ignore[arg-type]
        group,  # type: ignore[arg-type]
        lock_for_allocation=True,
    )

    assert result == [passenger]
    assert session.statement is not None
    assert session.statement._for_update_arg.read is True  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_retired_manual_mutations_return_gone_without_touching_db() -> None:
    async def assert_gone(awaitable: object) -> None:
        with pytest.raises(HTTPException) as retired:
            await awaitable  # type: ignore[misc]
        assert retired.value.status_code == 410
        assert "retired" in str(retired.value.detail).casefold()

    await assert_gone(
        generate_rooms(
            uuid.uuid4(),
            CreateRoomBatchRequest(room_type="twin", count=2),
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
        )
    )
    await assert_gone(
        update_room(
            uuid.uuid4(),
            UpdateRoomRequest(room_number="101", room_type="twin"),
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
        )
    )
    await assert_gone(
        update_room_order(
            uuid.uuid4(),
            UpdateRoomOrderRequest(room_ids=[uuid.uuid4()]),
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
        )
    )
    await assert_gone(
        delete_room(
            uuid.uuid4(),
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
        )
    )
    await assert_gone(
        update_passenger_allocation(
            uuid.uuid4(),
            uuid.uuid4(),
            UpdatePassengerAllocationRequest(),
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
        )
    )
