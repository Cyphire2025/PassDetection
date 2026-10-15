"""Strict, typed dashboard edits; resource scope and inspected revision are explicit."""

from copy import deepcopy
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from pydantic import ConfigDict, Field, create_model

from app.presentation.api.v1.schemas.client_group_schemas import UpdateClientGroupRequest
from app.presentation.api.v1.schemas.menu_schemas import (
    UpdateMealPlanEntryRequest,
    UpdateMealPlanRequest,
    UpdateMenuCategoryRequest,
    UpdateMenuDishRequest,
)
from app.presentation.api.v1.schemas.rooming_schemas import (
    AutoAllocateRoomsRequest,
    UpdateHotelPassengerSelectionRequest,
    UpdateHotelVipRequest,
    UpdateRoomingHotelRequest,
)

# These are the reviewed collection settings. Validate their types first; the
# canonical cross-field validators run after omitted values are filled from the
# locked group. Running replacement-form validators on a partial edit would
# silently discard airports or reject preserved relationship configuration.
GROUP_CONFIGURATION_FIELDS = (
    "name",
    "destination",
    "travel_date",
    "return_date",
    "timezone",
    "package_name",
    "departure_cities",
    "base_city_enabled",
    "nearest_international_airport_enabled",
    "staff_code_enabled",
    "agent_employee_code_enabled",
    "meal_preference_enabled",
    "require_selfie",
    "upload_configuration",
    "allow_files_from_device",
    "ask_nearest_domestic_airport",
    "relation_with_qualifier_enabled",
    "designation_enabled",
    "agency_dealership_name_enabled",
    "custom_questions",
    "custom_details",
    "notes",
)
if TYPE_CHECKING:
    GroupLinkConfiguration = UpdateClientGroupRequest
else:
    GroupLinkConfiguration = create_model(
        "GroupLinkConfiguration",
        __config__=ConfigDict(extra="forbid", str_strip_whitespace=True),
        **dict[str, Any]({
            name: (
                UpdateClientGroupRequest.model_fields[name].annotation,
                deepcopy(UpdateClientGroupRequest.model_fields[name]),
            )
            for name in GROUP_CONFIGURATION_FIELDS
        }),
    )


class GroupLinkEdit(GroupLinkConfiguration):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    agency_id: UUID
    group_id: UUID
    expected_configuration_revision: str = Field(pattern="^[a-f0-9]{64}$")
    collection_settings_confirmed: Literal[True]
    # Linking broadcasts has its own reviewed additive workflow.
    whatsapp_broadcast_group_ids: None = None
    matching_fields_by_broadcast: None = None


class MenuCategoryEdit(UpdateMenuCategoryRequest):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    agency_id: UUID | None = Field(..., description="Null explicitly selects the platform library.")
    category_id: UUID


class MenuDishEdit(UpdateMenuDishRequest):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    agency_id: UUID | None = Field(...)
    dish_id: UUID


class MealPlanEdit(UpdateMealPlanRequest):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    agency_id: UUID | None = Field(...)
    plan_id: UUID


class MealEntryEdit(UpdateMealPlanEntryRequest):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    agency_id: UUID | None = Field(...)
    plan_id: UUID
    entry_id: UUID


class HotelEdit(UpdateRoomingHotelRequest):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    agency_id: UUID
    group_id: UUID
    hotel_id: UUID
    expected_updated_at: datetime
    room_count: None = None


class HotelSelection(UpdateHotelPassengerSelectionRequest):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    agency_id: UUID
    group_id: UUID
    hotel_id: UUID
    # MCP retains the prior plan, but passenger removal remains a separate future workflow.
    mode: Literal["add"] = "add"
    passenger_ids: list[UUID] = Field(min_length=1, max_length=1000)
    allocation_changes_confirmed: Literal[True] = Field(
        description="User chose the passengers and has approved replacing any affected room plan."
    )


class HotelVip(UpdateHotelVipRequest):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    agency_id: UUID
    group_id: UUID
    hotel_id: UUID
    passenger_ids: list[UUID] = Field(min_length=1, max_length=1000)
    allocation_changes_confirmed: Literal[True]


class HotelAllocation(AutoAllocateRoomsRequest):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    agency_id: UUID
    group_id: UUID
    hotel_id: UUID
    allocation_changes_confirmed: Literal[True] = Field(
        description="User chose priority fields and approved creating/replacing the room plan. Physical check-ins are never created."
    )


DashboardEdit = GroupLinkEdit | MenuCategoryEdit | MenuDishEdit | MealPlanEdit | MealEntryEdit | HotelEdit | HotelSelection | HotelVip | HotelAllocation

EDIT_MODELS: dict[str, type[DashboardEdit]] = {
    "configure_group_link": GroupLinkEdit,
    "update_menu_category": MenuCategoryEdit,
    "update_menu_dish": MenuDishEdit,
    "update_meal_plan": MealPlanEdit,
    "update_meal_plan_entry": MealEntryEdit,
    "configure_rooming_hotel": HotelEdit,
    "select_rooming_passengers": HotelSelection,
    "set_rooming_vip": HotelVip,
    "allocate_rooming_rooms": HotelAllocation,
}
