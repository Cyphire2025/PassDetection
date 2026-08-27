"""Request and response contracts for hotel rooming lists."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ROOM_TYPES = {"single": 1, "twin": 2, "triple": 3}
ALLOCATION_TAGS = {"mixed", "male", "female", "family", "couple", "vip"}
PASSENGER_TAGS = {"unspecified", "male", "female", "family", "couple"}
SPECIAL_REQUESTS = {"smoking", "wheelchair", "vip", "late_arrival"}
AllocationRevision = Annotated[int, Field(ge=0)]


class AllocationRevisionFenceRequest(BaseModel):
    """Optimistic concurrency fence shared by allocation-changing commands."""

    expected_allocation_revisions: dict[uuid.UUID, AllocationRevision] = Field(
        ...,
        min_length=1,
        max_length=5000,
    )


class CreateRoomingHotelRequest(BaseModel):
    hotel_name: str = Field(..., min_length=2, max_length=255)
    city: str | None = Field(default=None, max_length=120)
    check_in_date: date | None = None
    check_out_date: date | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> CreateRoomingHotelRequest:
        if self.check_in_date and self.check_out_date and self.check_out_date < self.check_in_date:
            raise ValueError("Check-out date cannot be before check-in date")
        return self


class CreateRoomBatchRequest(BaseModel):
    room_type: str = Field(..., pattern="^(single|twin|triple)$")
    count: int = Field(..., ge=1, le=500)
    starting_number: int | None = Field(default=None, ge=1, le=99_999)
    allocation_tag: str = Field(default="mixed", pattern="^(mixed|male|female|family|couple|vip)$")


class UpdateRoomingHotelRequest(CreateRoomingHotelRequest):
    room_count: int | None = Field(default=None, ge=0, le=500)


class UpdateRoomRequest(BaseModel):
    room_number: str = Field(..., min_length=1, max_length=32)
    room_type: str = Field(..., pattern="^(single|twin|triple)$")
    allocation_tag: str = Field(default="mixed", pattern="^(mixed|male|female|family|couple|vip)$")
    roommate_notes: str | None = Field(default=None, max_length=2000)
    is_saved: bool = False


class UpdateRoomOrderRequest(BaseModel):
    room_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=500)


class UpdatePassengerAllocationRequest(BaseModel):
    room_id: uuid.UUID | None = None
    allocation_tag: str = Field(default="unspecified", pattern="^(unspecified|male|female|family|couple)$")
    special_requests: list[str] = Field(default_factory=list, max_length=4)
    roommate_notes: str | None = Field(default=None, max_length=2000)

    @field_validator("special_requests")
    @classmethod
    def validate_special_requests(cls, value: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(item.strip().lower() for item in value))
        invalid = set(normalized) - SPECIAL_REQUESTS
        if invalid:
            raise ValueError("Unsupported special request")
        return normalized


class UpdateHotelPassengerSelectionRequest(AllocationRevisionFenceRequest):
    passenger_ids: list[uuid.UUID] = Field(default_factory=list, max_length=5000)
    mode: Literal["replace", "add", "remove"] = "add"

    @field_validator("passenger_ids")
    @classmethod
    def validate_unique_passengers(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(set(value)) != len(value):
            raise ValueError("Each passenger can be selected only once")
        return value

    @model_validator(mode="after")
    def validate_nonempty_mutation(self) -> UpdateHotelPassengerSelectionRequest:
        if self.mode != "replace" and not self.passenger_ids:
            raise ValueError("Add and remove operations require at least one passenger")
        return self


class UpdateHotelVipRequest(AllocationRevisionFenceRequest):
    passenger_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=5000)
    is_vip: bool

    @field_validator("passenger_ids")
    @classmethod
    def validate_unique_passengers(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(set(value)) != len(value):
            raise ValueError("Each passenger can be selected only once")
        return value


class AutoAllocateRoomsRequest(AllocationRevisionFenceRequest):
    priority_fields: list[str] = Field(default_factory=list, max_length=6)

    @field_validator("priority_fields")
    @classmethod
    def validate_priority_fields(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item or len(item) > 180 for item in normalized):
            raise ValueError("Priority field keys must contain 1 to 180 characters")
        if len(set(normalized)) != len(normalized):
            raise ValueError("Each priority field can be selected only once")
        return normalized


class RoomingPriorityFieldResponse(BaseModel):
    key: str
    label: str
    source: str
    groupable: bool = True


class RoomingPriorityFieldOptionsResponse(BaseModel):
    group_id: uuid.UUID
    fields: list[RoomingPriorityFieldResponse] = Field(default_factory=list)
    max_priority_fields: int = 6
    gender_rule: str


class RoomingRosterFieldValuesResponse(BaseModel):
    group_id: uuid.UUID
    field: RoomingPriorityFieldResponse
    values_by_passenger: dict[uuid.UUID, str | None] = Field(
        default_factory=dict
    )


class RoomingPassengerResponse(BaseModel):
    passenger_id: uuid.UUID
    client_name: str
    client_email: str | None = None
    client_phone: str | None = None
    passport_sex: str | None = None
    submission_mode: str = "single"
    family_group_id: uuid.UUID | None = None
    family_group_label: str | None = None
    family_member_index: int | None = None
    family_relation: str | None = None
    family_gender: str | None = None
    family_size: int = 1
    family_head_name: str | None = None
    allocation_tag: str
    special_requests: list[str] = Field(default_factory=list)
    roommate_notes: str | None = None
    selected_hotel_id: uuid.UUID | None = None
    selected_hotel_name: str | None = None
    is_vip: bool = False


class RoomingRoomResponse(BaseModel):
    id: uuid.UUID
    room_number: str
    room_type: str
    capacity: int
    allocation_tag: str
    roommate_notes: str | None = None
    is_saved: bool = False
    sort_order: int = 0
    occupants: list[RoomingPassengerResponse] = Field(default_factory=list)


class RoomingHotelResponse(BaseModel):
    id: uuid.UUID
    hotel_name: str
    city: str | None = None
    check_in_date: date | None = None
    check_out_date: date | None = None
    rooms: list[RoomingRoomResponse] = Field(default_factory=list)
    unallocated_passengers: list[RoomingPassengerResponse] = Field(default_factory=list)
    allocated_passenger_count: int = 0
    capacity_total: int = 0
    selected_passengers: list[RoomingPassengerResponse] = Field(default_factory=list)
    selected_passenger_count: int = 0
    allocation_priority_fields: list[RoomingPriorityFieldResponse] = Field(
        default_factory=list
    )
    allocation_revision: int = 0
    allocation_is_current: bool = False


class RoomingWorkspaceResponse(BaseModel):
    group_id: uuid.UUID
    group_name: str
    destination: str | None = None
    total_passengers: int
    hotels: list[RoomingHotelResponse] = Field(default_factory=list)
    passengers: list[RoomingPassengerResponse] = Field(default_factory=list)


class RoomingRoomAllocationDeltaResponse(BaseModel):
    id: uuid.UUID
    room_number: str
    room_type: str
    capacity: int
    allocation_tag: str
    roommate_notes: str | None = None
    is_saved: bool = False
    sort_order: int = 0
    occupant_ids: list[uuid.UUID] = Field(default_factory=list, max_length=3)


class RoomingHotelAllocationDeltaResponse(BaseModel):
    hotel_id: uuid.UUID
    rooms: list[RoomingRoomAllocationDeltaResponse] = Field(default_factory=list)
    allocation_priority_fields: list[RoomingPriorityFieldResponse] = Field(
        default_factory=list
    )
    allocation_revision: int = Field(ge=0)
    allocation_is_current: bool = False
    allocated_passenger_count: int = Field(default=0, ge=0)
    capacity_total: int = Field(default=0, ge=0)


class RoomingPassengerAllocationDeltaResponse(BaseModel):
    passenger_id: uuid.UUID
    selected_hotel_id: uuid.UUID | None = None
    is_vip: bool = False


class RoomingAllocationMutationResponse(BaseModel):
    """Bounded allocation delta; deliberately excludes the full group roster."""

    group_id: uuid.UUID
    changed: bool
    current_revisions: dict[uuid.UUID, AllocationRevision] = Field(
        default_factory=dict,
        max_length=5000,
    )
    hotels: list[RoomingHotelAllocationDeltaResponse] = Field(
        default_factory=list,
        max_length=5000,
    )
    passengers: list[RoomingPassengerAllocationDeltaResponse] = Field(
        default_factory=list,
        max_length=5000,
    )


class RoomingExportResponse(BaseModel):
    generated_at: datetime
    filename: str


class HotelCheckinScanRequest(BaseModel):
    qr_payload: str = Field(..., min_length=49, max_length=49, pattern=r"^pdatt:[A-Za-z0-9_-]{43}$")
    client_event_id: str | None = Field(default=None, max_length=128)
    device_id: str | None = Field(default=None, max_length=128)


class UpdateHotelCheckinRequest(BaseModel):
    key_issued: bool | None = None
    welcome_letter_issued: bool | None = None
    remarks: str | None = Field(default=None, max_length=4000)


class HotelCheckinPassengerResponse(BaseModel):
    checkin_id: uuid.UUID
    passenger_id: uuid.UUID
    passenger_name: str
    submission_mode: str = "single"
    family_group_id: uuid.UUID | None = None
    family_group_label: str | None = None
    family_relation: str | None = None
    family_size: int = 1
    family_head_name: str | None = None
    room_id: uuid.UUID
    room_number: str
    room_type: str
    roommates: list[str] = Field(default_factory=list)
    checked_in: bool
    checked_in_at: datetime | None = None
    key_issued: bool
    key_issued_at: datetime | None = None
    welcome_letter_issued: bool
    welcome_letter_issued_at: datetime | None = None
    remarks: str | None = None
    is_vip: bool = False
    has_special_request: bool = False
    room_has_missing_occupants: bool = False


class HotelCheckinDashboardResponse(BaseModel):
    hotel_id: uuid.UUID
    hotel_name: str
    group_id: uuid.UUID
    group_name: str
    total_allocated_passengers: int
    checked_in_count: int
    keys_issued_count: int
    welcome_letters_issued_count: int
    rooms_complete: int
    rooms_with_missing_occupants: int
    passengers: list[HotelCheckinPassengerResponse] = Field(default_factory=list)


class HotelCheckinScanResponse(BaseModel):
    status: str
    message: str
    checkin: HotelCheckinPassengerResponse | None = None
