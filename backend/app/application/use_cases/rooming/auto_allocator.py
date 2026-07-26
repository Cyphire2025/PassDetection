"""Deterministic, gender-safe hotel room allocation."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RoomingAllocationCandidate:
    """A selected hotel passenger prepared for deterministic allocation."""

    passenger_id: uuid.UUID
    gender: str
    is_vip: bool
    priority_values: tuple[str, ...]
    stable_order: tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class PlannedRoom:
    """One generated room and its ordered occupants."""

    room_type: str
    allocation_tag: str
    passenger_ids: tuple[uuid.UUID, ...]


def normalize_rooming_gender(value: object) -> str | None:
    """Return the only two passport-sex buckets allowed for shared rooms."""

    normalized = " ".join(str(value or "").strip().split()).casefold()
    if normalized in {"m", "male"}:
        return "male"
    if normalized in {"f", "female"}:
        return "female"
    return None


def normalize_priority_value(value: object) -> str:
    """Normalize grouping values while retaining deterministic empty buckets."""

    return " ".join(str(value or "").strip().split()).casefold()


def build_room_plan(
    candidates: list[RoomingAllocationCandidate],
    *,
    priority_count: int,
) -> list[PlannedRoom]:
    """Build an O(N log N + P*N), P<=6, stable hierarchical room plan.

    Priority 1 is a hard outer section: occupants from different Priority 1
    values never share a room. Inside each section, VIP passengers are emitted
    first as singles, followed by female rooms and then male rooms. Priorities
    2-6 refine pairing using the complete remaining tuple, successively shorter
    prefixes, and finally stable roster order. A final odd passenger remains
    alone in a twin room, which preserves the same-gender rule and exposes the
    spare bed.
    """

    if priority_count < 0 or priority_count > 6:
        raise ValueError("priority_count must be between 0 and 6")
    for candidate in candidates:
        if candidate.gender not in {"male", "female"}:
            raise ValueError("Every candidate must have an exact normalized gender")
        if len(candidate.priority_values) != priority_count:
            raise ValueError("Every candidate must provide every selected priority value")

    ordered = sorted(
        candidates,
        key=lambda item: (*item.stable_order, str(item.passenger_id)),
    )
    sectioned: dict[str, list[RoomingAllocationCandidate]] = defaultdict(list)
    section_order: list[str] = []
    for candidate in ordered:
        section_key = candidate.priority_values[0] if priority_count else ""
        if section_key not in sectioned:
            section_order.append(section_key)
        sectioned[section_key].append(candidate)

    rooms: list[PlannedRoom] = []
    for section_key in section_order:
        section = sectioned[section_key]
        rooms.extend(
            PlannedRoom(
                room_type="single",
                allocation_tag="vip",
                passenger_ids=(candidate.passenger_id,),
            )
            for candidate in section
            if candidate.is_vip
        )

        non_vip_by_gender: dict[
            str,
            list[RoomingAllocationCandidate],
        ] = defaultdict(list)
        for candidate in section:
            if not candidate.is_vip:
                non_vip_by_gender[candidate.gender].append(candidate)

        for gender in ("female", "male"):
            rooms.extend(
                _pair_section_gender(
                    non_vip_by_gender.get(gender, []),
                    gender=gender,
                    priority_count=priority_count,
                )
            )
    return rooms


def _pair_section_gender(
    candidates: list[RoomingAllocationCandidate],
    *,
    gender: str,
    priority_count: int,
) -> list[PlannedRoom]:
    """Pair one Priority 1 and gender bucket without crossing its boundary."""

    paired, unpaired = _pair_priority_hierarchy(
        candidates,
        priority_position=1,
        priority_count=priority_count,
    )

    rooms = [
        PlannedRoom(
            room_type="twin",
            allocation_tag=gender,
            passenger_ids=(first.passenger_id, second.passenger_id),
        )
        for first, second in paired
    ]
    rooms.extend(
        PlannedRoom(
            room_type="twin",
            allocation_tag=gender,
            passenger_ids=(candidate.passenger_id,),
        )
        for candidate in unpaired
    )
    return rooms


def _pair_priority_hierarchy(
    candidates: list[RoomingAllocationCandidate],
    *,
    priority_position: int,
    priority_count: int,
) -> tuple[
    list[tuple[RoomingAllocationCandidate, RoomingAllocationCandidate]],
    list[RoomingAllocationCandidate],
]:
    """Pair deepest matches first while keeping every parent group contiguous."""

    if priority_position >= priority_count:
        return _pair_adjacent(candidates)

    grouped: dict[str, list[RoomingAllocationCandidate]] = defaultdict(list)
    group_order: list[str] = []
    for candidate in candidates:
        key = candidate.priority_values[priority_position]
        if key not in grouped:
            group_order.append(key)
        grouped[key].append(candidate)

    paired: list[
        tuple[RoomingAllocationCandidate, RoomingAllocationCandidate]
    ] = []
    carry: list[RoomingAllocationCandidate] = []
    for key in group_order:
        child_pairs, child_carry = _pair_priority_hierarchy(
            grouped[key],
            priority_position=priority_position + 1,
            priority_count=priority_count,
        )
        paired.extend(child_pairs)
        carry.extend(child_carry)

    carry_pairs, remaining = _pair_adjacent(carry)
    paired.extend(carry_pairs)
    return paired, remaining


def _pair_adjacent(
    candidates: list[RoomingAllocationCandidate],
) -> tuple[
    list[tuple[RoomingAllocationCandidate, RoomingAllocationCandidate]],
    list[RoomingAllocationCandidate],
]:
    paired = [
        (candidates[index], candidates[index + 1])
        for index in range(0, len(candidates) - 1, 2)
    ]
    unpaired = candidates[-1:] if len(candidates) % 2 else []
    return paired, unpaired


def room_plan_fingerprint(
    plan: list[PlannedRoom],
    priority_fields: list[dict[str, str]],
    *,
    candidates: list[RoomingAllocationCandidate] | None = None,
) -> str:
    """Return a stable digest of allocation inputs and the resulting rooms."""

    payload = {
        "priority_fields": priority_fields,
        "candidates": [
            {
                "passenger_id": str(candidate.passenger_id),
                "gender": candidate.gender,
                "is_vip": candidate.is_vip,
                "priority_values": list(candidate.priority_values),
            }
            for candidate in sorted(
                candidates or [],
                key=lambda item: (*item.stable_order, str(item.passenger_id)),
            )
        ],
        "rooms": [
            {
                "room_type": room.room_type,
                "allocation_tag": room.allocation_tag,
                "passenger_ids": [str(passenger_id) for passenger_id in room.passenger_ids],
            }
            for room in plan
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
