from __future__ import annotations

import uuid

import pytest

from app.application.use_cases.rooming.auto_allocator import (
    RoomingAllocationCandidate,
    build_room_plan,
    normalize_rooming_gender,
    room_plan_fingerprint,
)


def _id(number: int) -> uuid.UUID:
    return uuid.UUID(int=number)


def _candidate(
    number: int,
    *,
    gender: str = "female",
    vip: bool = False,
    priorities: tuple[str, ...] = (),
    order: int | None = None,
) -> RoomingAllocationCandidate:
    return RoomingAllocationCandidate(
        passenger_id=_id(number),
        gender=gender,
        is_vip=vip,
        priority_values=priorities,
        stable_order=(number if order is None else order,),
    )


def test_vip_is_single_and_non_vip_never_crosses_gender() -> None:
    plan = build_room_plan(
        [
            _candidate(1, gender="male", vip=True),
            _candidate(2, gender="male"),
            _candidate(3, gender="male"),
            _candidate(4, gender="female"),
            _candidate(5, gender="female"),
        ],
        priority_count=0,
    )

    assert plan[0].room_type == "single"
    assert plan[0].allocation_tag == "vip"
    assert plan[0].passenger_ids == (_id(1),)
    assert all(len(room.passenger_ids) <= 2 for room in plan)
    assert {
        room.allocation_tag: room.passenger_ids
        for room in plan
        if room.allocation_tag != "vip"
    } == {
        "female": (_id(4), _id(5)),
        "male": (_id(2), _id(3)),
    }


def test_odd_non_vip_uses_one_bed_in_a_twin_without_cross_gender_pairing() -> None:
    plan = build_room_plan(
        [
            _candidate(1, gender="female"),
            _candidate(2, gender="female"),
            _candidate(3, gender="female"),
        ],
        priority_count=0,
    )

    assert [room.room_type for room in plan] == ["twin", "twin"]
    assert [room.passenger_ids for room in plan] == [
        (_id(1), _id(2)),
        (_id(3),),
    ]


def test_priority_one_is_a_hard_outer_section_in_first_seen_order() -> None:
    plan = build_room_plan(
        [
            _candidate(1, priorities=("a",), order=1),
            _candidate(2, priorities=("b",), order=2),
            _candidate(3, priorities=("a",), order=3),
            _candidate(4, priorities=("a",), order=4),
        ],
        priority_count=1,
    )

    assert [room.passenger_ids for room in plan] == [
        (_id(1), _id(3)),
        (_id(4),),
        (_id(2),),
    ]


def test_lower_priorities_refine_pairing_within_priority_one_section() -> None:
    plan = build_room_plan(
        [
            _candidate(1, priorities=("north", "sales", "manager")),
            _candidate(2, priorities=("north", "support", "manager")),
            _candidate(3, priorities=("north", "sales", "manager")),
            _candidate(4, priorities=("north", "support", "executive")),
            _candidate(5, priorities=("north", "finance", "manager")),
            _candidate(6, priorities=("north", "finance", "executive")),
        ],
        priority_count=3,
    )

    assert [room.passenger_ids for room in plan] == [
        (_id(1), _id(3)),
        (_id(2), _id(4)),
        (_id(5), _id(6)),
    ]


def test_lower_priority_parent_groups_remain_contiguous_in_room_order() -> None:
    plan = build_room_plan(
        [
            _candidate(1, priorities=("north", "a", "manager")),
            _candidate(2, priorities=("north", "b", "manager")),
            _candidate(3, priorities=("north", "a", "manager")),
            _candidate(4, priorities=("north", "b", "executive")),
            _candidate(5, priorities=("north", "a", "executive")),
            _candidate(6, priorities=("north", "a", "executive")),
            _candidate(7, priorities=("north", "b", "manager")),
            _candidate(8, priorities=("north", "b", "executive")),
        ],
        priority_count=3,
    )

    assert [room.passenger_ids for room in plan] == [
        (_id(1), _id(3)),
        (_id(5), _id(6)),
        (_id(2), _id(7)),
        (_id(4), _id(8)),
    ]


def test_each_priority_one_section_orders_vip_then_female_then_male() -> None:
    plan = build_room_plan(
        [
            _candidate(1, gender="male", priorities=("gujarat",)),
            _candidate(2, gender="female", priorities=("gujarat",)),
            _candidate(3, gender="male", vip=True, priorities=("gujarat",)),
            _candidate(4, gender="female", priorities=("gujarat",)),
            _candidate(5, gender="male", priorities=("gujarat",)),
            _candidate(6, gender="female", priorities=("odisha",)),
            _candidate(7, gender="female", vip=True, priorities=("odisha",)),
        ],
        priority_count=1,
    )

    assert [
        (room.allocation_tag, room.passenger_ids)
        for room in plan
    ] == [
        ("vip", (_id(3),)),
        ("female", (_id(2), _id(4))),
        ("male", (_id(1), _id(5))),
        ("vip", (_id(7),)),
        ("female", (_id(6),)),
    ]


def test_gender_normalization_is_exact_and_unsupported_values_are_rejected() -> None:
    assert normalize_rooming_gender(" M ") == "male"
    assert normalize_rooming_gender("Female") == "female"
    assert normalize_rooming_gender("") is None
    assert normalize_rooming_gender("Other") is None

    with pytest.raises(ValueError, match="exact normalized gender"):
        build_room_plan([_candidate(1, gender="other")], priority_count=0)


def test_priority_count_is_bounded_and_fingerprint_is_repeatable() -> None:
    with pytest.raises(ValueError, match="between 0 and 6"):
        build_room_plan([], priority_count=7)

    plan = build_room_plan([_candidate(1, vip=True)], priority_count=0)
    fields = [{"key": "field:nationality", "label": "Nationality", "source": "passport"}]
    assert room_plan_fingerprint(plan, fields) == room_plan_fingerprint(plan, fields)


def test_fingerprint_changes_when_priority_inputs_change_even_if_room_shape_does_not() -> None:
    first = _candidate(1, priorities=("north",))
    second = _candidate(1, priorities=("south",))
    plan = build_room_plan([first], priority_count=1)
    fields = [{"key": "whatsapp:zone", "label": "Zone", "source": "whatsapp"}]

    assert room_plan_fingerprint(
        plan,
        fields,
        candidates=[first],
    ) != room_plan_fingerprint(
        plan,
        fields,
        candidates=[second],
    )
