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
    """Build an O(N log N + P*N), P<=6, stable hierarchical pairing plan.

    VIP passengers are always emitted as single rooms. Other passengers are
    partitioned by exact normalized gender, paired first on the complete
    priority tuple, then on successively shorter prefixes, and finally paired
    in stable roster order. A final odd passenger remains alone in a twin room;
    this never mixes genders and accurately exposes the spare bed.
    """

    if priority_count < 0 or priority_count > 6:
        raise ValueError("priority_count must be between 0 and 6")
    for candidate in candidates:
        if candidate.gender not in {"male", "female"}:
            raise ValueError("Every candidate must have an exact normalized gender")
        if len(candidate.priority_values) != priority_count:
            raise ValueError("Every candidate must provide every selected priority value")

    ordered = sorted(candidates, key=lambda item: (*item.stable_order, str(item.passenger_id)))
    rooms = [
        PlannedRoom(
            room_type="single",
            allocation_tag="vip",
            passenger_ids=(candidate.passenger_id,),
        )
        for candidate in ordered
        if candidate.is_vip
    ]

    non_vip_by_gender: dict[str, list[RoomingAllocationCandidate]] = defaultdict(list)
    for candidate in ordered:
        if not candidate.is_vip:
            non_vip_by_gender[candidate.gender].append(candidate)

    for gender in ("female", "male"):
        remaining = non_vip_by_gender.get(gender, [])
        paired: list[tuple[RoomingAllocationCandidate, RoomingAllocationCandidate]] = []
        for prefix_length in range(priority_count, 0, -1):
            grouped: dict[tuple[str, ...], list[RoomingAllocationCandidate]] = defaultdict(list)
            group_order: list[tuple[str, ...]] = []
            for candidate in remaining:
                key = candidate.priority_values[:prefix_length]
                if key not in grouped:
                    group_order.append(key)
                grouped[key].append(candidate)
            leftover_ids: set[uuid.UUID] = set()
            for key in group_order:
                members = grouped[key]
                for index in range(0, len(members) - 1, 2):
                    paired.append((members[index], members[index + 1]))
                if len(members) % 2:
                    leftover_ids.add(members[-1].passenger_id)
            remaining = [
                candidate
                for candidate in remaining
                if candidate.passenger_id in leftover_ids
            ]

        for index in range(0, len(remaining) - 1, 2):
            paired.append((remaining[index], remaining[index + 1]))
        unpaired = remaining[-1:] if len(remaining) % 2 else []

        rooms.extend(
            PlannedRoom(
                room_type="twin",
                allocation_tag=gender,
                passenger_ids=(first.passenger_id, second.passenger_id),
            )
            for first, second in paired
        )
        rooms.extend(
            PlannedRoom(
                room_type="twin",
                allocation_tag=gender,
                passenger_ids=(candidate.passenger_id,),
            )
            for candidate in unpaired
        )
    return rooms


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
