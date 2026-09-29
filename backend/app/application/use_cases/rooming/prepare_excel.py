"""Canonical detached hotel workbook preparation shared by web and MCP."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections import defaultdict
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.passports.prepare_group_excel import _canonical
from app.application.use_cases.rooming.auto_allocator import (
    RoomingAllocationCandidate,
    build_room_plan,
    normalize_priority_value,
    normalize_rooming_gender,
    room_plan_fingerprint,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    PassportSubmissionModel,
    RoomingAssignmentModel,
    RoomingHotelModel,
    RoomingHotelPassengerModel,
    RoomingRoomModel,
)
from app.infrastructure.documents.storage_transfers import run_bounded_storage_operations
from app.infrastructure.export.rooming_excel_exporter import RoomingExcelExporter

RoomingExportKind = Literal["rooming_list", "checkins"]


class RoomingPreparationError(ValueError):
    def __init__(self, *, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


@dataclass(frozen=True)
class RoomingExcelSupport:
    require_current_allocation: Callable[..., Any]
    eligible_group_passengers: Callable[..., Any]
    room_number_sort_key: Callable[..., Any]
    priority_context: Callable[..., Any]
    stored_plan_matches: Callable[..., Any]
    filename: Callable[..., Any]
    checkin_dashboard: Callable[..., Any]


def _plain(value: Any) -> Any:
    if isinstance(value, SimpleNamespace):
        return _plain(vars(value))
    if isinstance(value, dict):
        return {str(key): _plain(child) for key, child in value.items()}
    if isinstance(value, (set, frozenset)):
        return [_plain(child) for child in sorted(value, key=str)]
    if isinstance(value, (list, tuple)):
        return [_plain(child) for child in value]
    return _canonical(value)


@dataclass(frozen=True)
class PreparedRoomingExcel:
    kind: RoomingExportKind
    arguments: dict[str, Any]
    scope: tuple[Any, ...]
    filename: str
    passenger_count: int
    priority_fields: list[str]

    def render_sync(self) -> bytes:
        exporter = RoomingExcelExporter()
        render = exporter.export_hotel if self.kind == "rooming_list" else exporter.export_checkins
        return render(**self.arguments)

    async def render(self) -> bytes:
        results = await run_bounded_storage_operations(
            [lambda: asyncio.to_thread(self.render_sync)], concurrency=1
        )
        return results[0]

    def revision(self, source: dict[str, Any], *, maximum_bytes: int) -> str:
        snapshot = _plain(
            {"kind": self.kind, "arguments": self.arguments, "scope": self.scope, "source": source}
        )
        digest, size = hashlib.sha256(), 0
        for part in json.JSONEncoder(
            sort_keys=True, separators=(",", ":"), allow_nan=False
        ).iterencode(snapshot):
            encoded = part.encode()
            size += len(encoded)
            if size > maximum_bytes:
                raise ValueError("Rooming export exceeds the snapshot size limit")
            digest.update(encoded)
        return digest.hexdigest()


async def prepare_rooming_list(
    session: AsyncSession,
    *,
    support: RoomingExcelSupport,
    hotel: RoomingHotelModel,
    group: ClientGroupModel,
) -> PreparedRoomingExcel:
    await support.require_current_allocation(session, hotel)
    rooms_result = await session.execute(
        select(RoomingRoomModel).where(RoomingRoomModel.hotel_id == hotel.id)
    )
    rooms = sorted(
        rooms_result.scalars().all(),
        key=lambda room: (room.sort_order, support.room_number_sort_key(room.room_number)),
    )
    assignments_result = await session.execute(
        select(RoomingAssignmentModel)
        .where(RoomingAssignmentModel.hotel_id == hotel.id)
        .order_by(RoomingAssignmentModel.position.asc())
    )
    assignments_by_room: dict[uuid.UUID, list[RoomingAssignmentModel]] = defaultdict(list)
    passenger_ids: set[uuid.UUID] = set()
    for assignment in assignments_result.scalars().all():
        assignments_by_room[assignment.room_id].append(assignment)
        passenger_ids.add(assignment.passenger_id)
    passenger_result = (
        await session.execute(
            select(PassportSubmissionModel).where(PassportSubmissionModel.id.in_(passenger_ids))
        )
        if passenger_ids
        else None
    )
    passengers = list(passenger_result.scalars().all()) if passenger_result else []
    all_passengers = await support.eligible_group_passengers(
        session,
        group,
        lock_for_allocation=True,
    )
    priority_context = await support.priority_context(
        session,
        group=group,
        passengers=all_passengers,
        required_fields=list(hotel.allocation_priority_fields or []),
        requested_keys=[field["key"] for field in (hotel.allocation_priority_fields or [])],
        lock_inputs=True,
    )
    memberships = list(
        (
            await session.execute(
                select(RoomingHotelPassengerModel).where(
                    RoomingHotelPassengerModel.hotel_id == hotel.id
                )
            )
        )
        .scalars()
        .all()
    )
    priority_fields = list(hotel.allocation_priority_fields or [])
    if hotel.allocation_fingerprint != "0" * 64:
        allocation_passenger_by_id = {passenger.id: passenger for passenger in all_passengers}
        candidates: list[RoomingAllocationCandidate] = []
        for membership in memberships:
            passenger = allocation_passenger_by_id.get(membership.passenger_id)
            if passenger is None:
                raise RoomingPreparationError(
                    status_code=409,
                    detail=(
                        "The selected passenger data changed. Run auto room "
                        "allocation again before exporting."
                    ),
                )
            passport_fields = passenger.confirmed_fields or passenger.extracted_fields or {}
            gender = normalize_rooming_gender(passport_fields.get("sex"))
            if gender is None:
                raise RoomingPreparationError(
                    status_code=409,
                    detail=(
                        "A selected passenger no longer has Gender set to Male "
                        "or Female. Correct it and run auto room allocation again."
                    ),
                )
            passenger_values = priority_context.values_by_passenger.get(
                passenger.id,
                {},
            )
            candidates.append(
                RoomingAllocationCandidate(
                    passenger_id=passenger.id,
                    gender=gender,
                    is_vip=membership.is_vip,
                    priority_values=tuple(
                        normalize_priority_value(passenger_values.get(field["key"]))
                        for field in priority_fields
                    ),
                    stable_order=(
                        passenger.created_at,
                        passenger.family_member_index or 0,
                        passenger.client_name.casefold(),
                    ),
                )
            )
        expected_plan = build_room_plan(
            candidates,
            priority_count=len(priority_fields),
        )
        expected_fingerprint = room_plan_fingerprint(
            expected_plan,
            priority_fields,
            candidates=candidates,
        )
        if (
            expected_fingerprint != hotel.allocation_fingerprint
            or not await support.stored_plan_matches(
                session,
                hotel.id,
                expected_plan,
            )
        ):
            raise RoomingPreparationError(
                status_code=409,
                detail=(
                    "Passenger grouping inputs changed after room allocation. "
                    "Run auto room allocation again before exporting."
                ),
            )
    export_group = SimpleNamespace(
        name=group.name,
        staff_code_enabled=group.staff_code_enabled,
        agent_employee_code_enabled=group.agent_employee_code_enabled,
        travel_date=group.travel_date,
    )
    export_hotel = SimpleNamespace(
        hotel_name=hotel.hotel_name,
        city=hotel.city,
        check_in_date=hotel.check_in_date,
        check_out_date=hotel.check_out_date,
    )
    export_rooms = [
        (
            SimpleNamespace(
                room_number=room.room_number,
                room_type=room.room_type,
            ),
            [
                SimpleNamespace(passenger_id=assignment.passenger_id)
                for assignment in assignments_by_room.get(room.id, [])
            ],
        )
        for room in rooms
    ]
    export_passenger_by_id = {
        passenger.id: SimpleNamespace(
            id=passenger.id,
            confirmed_fields=dict(passenger.confirmed_fields or {}),
            extracted_fields=dict(passenger.extracted_fields or {}),
            staff_metadata=dict(passenger.staff_metadata or {}),
        )
        for passenger in passengers
    }
    export_scope = (
        hotel.allocation_revision,
        hotel.allocation_fingerprint,
        hotel.hotel_name,
        hotel.city,
        hotel.check_in_date,
        hotel.check_out_date,
        group.name,
        group.staff_code_enabled,
        group.agent_employee_code_enabled,
        group.travel_date,
    )
    filename = support.filename(hotel.hotel_name)
    export_vip_passenger_ids = {
        membership.passenger_id for membership in memberships if membership.is_vip
    }
    return PreparedRoomingExcel(
        kind="rooming_list",
        arguments={
            "group": export_group,
            "hotel": export_hotel,
            "rooms": export_rooms,
            "passenger_by_id": export_passenger_by_id,
            "vip_passenger_ids": export_vip_passenger_ids,
            "priority_fields": [dict(field) for field in priority_fields],
            "priority_values": {
                passenger_id: dict(values)
                for passenger_id, values in priority_context.values_by_passenger.items()
            },
        },
        scope=export_scope,
        filename=filename,
        passenger_count=len(passengers),
        priority_fields=[field["key"] for field in priority_fields],
    )


async def prepare_checkins(
    session: AsyncSession,
    *,
    support: RoomingExcelSupport,
    hotel: RoomingHotelModel,
    group: ClientGroupModel,
) -> PreparedRoomingExcel:
    await support.require_current_allocation(session, hotel)
    dashboard = await support.checkin_dashboard(session, hotel, group)
    passengers = [
        SimpleNamespace(
            room_number=item.room_number,
            room_type=item.room_type,
            passenger_name=item.passenger_name,
            checked_in=item.checked_in,
            key_issued=item.key_issued,
            welcome_letter_issued=item.welcome_letter_issued,
            remarks=item.remarks,
            is_vip=item.is_vip,
        )
        for item in dashboard.passengers
    ]
    return PreparedRoomingExcel(
        kind="checkins",
        arguments={
            "group_name": group.name,
            "hotel_name": hotel.hotel_name,
            "passengers": passengers,
        },
        scope=(
            hotel.allocation_revision,
            hotel.allocation_fingerprint,
            hotel.hotel_name,
            group.name,
        ),
        filename=f"hotel_checkins_{support.filename(hotel.hotel_name).removeprefix('rooming_list_')}",
        passenger_count=len(passengers),
        priority_fields=[],
    )
