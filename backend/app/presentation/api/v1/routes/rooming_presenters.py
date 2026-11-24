"""Hotel rooming: presenters."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable

from app.infrastructure.database.models import (
    PassportSubmissionModel,
    RoomingCheckinModel,
    RoomingHotelPassengerModel,
    RoomingPassengerPreferenceModel,
    RoomingRoomModel,
)
from app.presentation.api.v1.schemas.rooming_schemas import (
    HotelCheckinPassengerResponse,
    RoomingPassengerResponse,
    RoomingRoomResponse,
)


def _passenger_response(
    passenger: PassportSubmissionModel,
    preference: RoomingPassengerPreferenceModel | None,
    family_sizes: dict[uuid.UUID, int] | None = None,
    *,
    membership: RoomingHotelPassengerModel | None = None,
    selected_hotel_name: str | None = None,
) -> RoomingPassengerResponse:
    fields = passenger.confirmed_fields or passenger.extracted_fields or {}
    family_size = _family_size(passenger, family_sizes)
    default_tag = _default_rooming_tag(passenger, family_size)
    return RoomingPassengerResponse(
        passenger_id=passenger.id,
        client_name=passenger.client_name,
        client_email=passenger.client_email,
        client_phone=passenger.client_phone,
        passport_sex=(str(fields["sex"]) if fields.get("sex") is not None else None),
        submission_mode=passenger.submission_mode,
        family_group_id=passenger.family_group_id,
        family_group_label=_family_group_label(passenger, family_size),
        family_member_index=passenger.family_member_index,
        family_relation=passenger.family_relation,
        family_gender=passenger.family_gender,
        family_size=family_size,
        family_head_name=passenger.family_head_name,
        allocation_tag=preference.allocation_tag if preference else default_tag,
        special_requests=preference.special_requests if preference else [],
        roommate_notes=preference.roommate_notes if preference else None,
        selected_hotel_id=membership.hotel_id if membership else None,
        selected_hotel_name=selected_hotel_name,
        is_vip=bool(membership and membership.is_vip),
    )


def _family_sizes(passengers: Iterable[PassportSubmissionModel]) -> dict[uuid.UUID, int]:
    sizes: dict[uuid.UUID, int] = defaultdict(int)
    for passenger in passengers:
        if passenger.family_group_id:
            sizes[passenger.family_group_id] += 1
    return dict(sizes)


def _family_size(
    passenger: PassportSubmissionModel, family_sizes: dict[uuid.UUID, int] | None
) -> int:
    if not passenger.family_group_id:
        return 1
    return max(1, int((family_sizes or {}).get(passenger.family_group_id, 1)))


def _default_rooming_tag(passenger: PassportSubmissionModel, family_size: int) -> str:
    if passenger.submission_mode == "family" and passenger.family_group_id:
        return "couple" if family_size == 2 else "family"
    sex = (
        str((passenger.confirmed_fields or passenger.extracted_fields or {}).get("sex") or "")
        .strip()
        .lower()
    )
    if sex in {"m", "male"}:
        return "male"
    if sex in {"f", "female"}:
        return "female"
    return "unspecified"


def _family_group_label(passenger: PassportSubmissionModel, family_size: int) -> str | None:
    if passenger.submission_mode != "family" or not passenger.family_group_id:
        return None
    head = passenger.family_head_name or passenger.client_name
    kind = "Couple" if family_size == 2 else "Family"
    return f"{head} {kind} ({family_size})"


def _room_response(
    room: RoomingRoomModel, occupants: list[RoomingPassengerResponse]
) -> RoomingRoomResponse:
    return RoomingRoomResponse(
        id=room.id,
        room_number=room.room_number,
        room_type=room.room_type,
        capacity=room.capacity,
        allocation_tag=room.allocation_tag,
        roommate_notes=room.roommate_notes,
        is_saved=room.is_saved,
        sort_order=room.sort_order,
        occupants=occupants,
    )


def _checkin_item_response(
    *,
    room: RoomingRoomModel,
    passenger: PassportSubmissionModel,
    checkin: RoomingCheckinModel | None,
    preference: RoomingPassengerPreferenceModel | None,
    occupants: list[PassportSubmissionModel],
    family_sizes: dict[uuid.UUID, int] | None = None,
) -> HotelCheckinPassengerResponse:
    is_vip = room.allocation_tag == "vip" or bool(
        preference and "vip" in (preference.special_requests or [])
    )
    family_size = _family_size(passenger, family_sizes)
    return HotelCheckinPassengerResponse(
        checkin_id=checkin.id if checkin else uuid.UUID(int=0),
        passenger_id=passenger.id,
        passenger_name=passenger.client_name,
        submission_mode=passenger.submission_mode,
        family_group_id=passenger.family_group_id,
        family_group_label=_family_group_label(passenger, family_size),
        family_relation=passenger.family_relation,
        family_size=family_size,
        family_head_name=passenger.family_head_name,
        room_id=room.id,
        room_number=room.room_number,
        room_type=room.room_type,
        roommates=[other.client_name for other in occupants if other.id != passenger.id],
        checked_in=bool(checkin and checkin.checked_in),
        checked_in_at=checkin.checked_in_at if checkin else None,
        key_issued=bool(checkin and checkin.key_issued),
        key_issued_at=checkin.key_issued_at if checkin else None,
        welcome_letter_issued=bool(checkin and checkin.welcome_letter_issued),
        welcome_letter_issued_at=(checkin.welcome_letter_issued_at if checkin else None),
        remarks=checkin.remarks if checkin else None,
        is_vip=is_vip,
        has_special_request=bool(preference and preference.special_requests),
        room_has_missing_occupants=0 < len(occupants) < room.capacity,
    )
