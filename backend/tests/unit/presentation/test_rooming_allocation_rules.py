from __future__ import annotations

import uuid

from app.application.use_cases.rooming.auto_allocator import (
    RoomingAllocationCandidate,
    build_room_plan,
    normalize_rooming_gender,
)


def _candidate(*, gender: str, is_vip: bool = False) -> RoomingAllocationCandidate:
    passenger_id = uuid.uuid4()
    return RoomingAllocationCandidate(
        passenger_id=passenger_id,
        gender=gender,
        is_vip=is_vip,
        priority_values=(),
        stable_order=(str(passenger_id),),
    )


def test_gender_normalization_accepts_only_supported_buckets() -> None:
    assert normalize_rooming_gender("M") == "male"
    assert normalize_rooming_gender("female") == "female"
    assert normalize_rooming_gender("unspecified") is None


def test_auto_allocation_never_mixes_male_and_female_passengers() -> None:
    candidates = [
        _candidate(gender="male"),
        _candidate(gender="female"),
        _candidate(gender="male"),
        _candidate(gender="female"),
    ]

    rooms = build_room_plan(candidates, priority_count=0)

    candidate_gender = {
        candidate.passenger_id: candidate.gender for candidate in candidates
    }
    assert all(
        len({candidate_gender[passenger_id] for passenger_id in room.passenger_ids})
        == 1
        for room in rooms
    )


def test_vip_passenger_always_receives_a_single_room() -> None:
    vip = _candidate(gender="female", is_vip=True)
    non_vip = _candidate(gender="female")

    rooms = build_room_plan([vip, non_vip], priority_count=0)

    vip_room = next(room for room in rooms if vip.passenger_id in room.passenger_ids)
    assert vip_room.room_type == "single"
    assert vip_room.allocation_tag == "vip"
    assert vip_room.passenger_ids == (vip.passenger_id,)
