"""Stable rooming API facade; focused modules own each workflow boundary."""

from fastapi import APIRouter
from fastapi.routing import APIRoute

from . import rooming_auto_allocation as _rooming_auto_allocation
from . import rooming_checkins as _rooming_checkins
from . import rooming_exports as _rooming_exports
from . import rooming_hotels as _rooming_hotels
from . import rooming_selection as _rooming_selection
from . import rooming_workspace as _rooming_workspace
from .rooming_access import _allocation_state_is_current as _allocation_state_is_current
from .rooming_access import _audit as _audit
from .rooming_access import _datetime_is_after as _datetime_is_after
from .rooming_access import _eligible_group_passengers as _eligible_group_passengers
from .rooming_access import _export_filename as _export_filename
from .rooming_access import _get_checkin_hotel as _get_checkin_hotel
from .rooming_access import _get_rooming_group as _get_rooming_group
from .rooming_access import _get_rooming_hotel as _get_rooming_hotel
from .rooming_access import _require_current_allocation as _require_current_allocation
from .rooming_access import _stored_room_plan_matches as _stored_room_plan_matches
from .rooming_auto_allocation import auto_allocate_hotel_rooms as auto_allocate_hotel_rooms
from .rooming_checkin_reads import _checkin_dashboard as _checkin_dashboard
from .rooming_checkin_reads import _checkin_item as _checkin_item
from .rooming_checkins import get_hotel_checkins as get_hotel_checkins
from .rooming_checkins import scan_hotel_checkin as scan_hotel_checkin
from .rooming_checkins import update_hotel_checkin as update_hotel_checkin
from .rooming_exports import export_hotel_checkins as export_hotel_checkins
from .rooming_exports import export_hotel_rooming_list as export_hotel_rooming_list
from .rooming_exports import rooming_excel_support as rooming_excel_support
from .rooming_hotels import create_rooming_hotel as create_rooming_hotel
from .rooming_hotels import delete_room as delete_room
from .rooming_hotels import generate_rooms as generate_rooms
from .rooming_hotels import update_passenger_allocation as update_passenger_allocation
from .rooming_hotels import update_room as update_room
from .rooming_hotels import update_room_order as update_room_order
from .rooming_hotels import update_rooming_hotel as update_rooming_hotel
from .rooming_policy import CHECKIN_ROLES as CHECKIN_ROLES
from .rooming_policy import ROOMING_PASSENGER_STATUSES as ROOMING_PASSENGER_STATUSES
from .rooming_policy import ROOMING_ROLES as ROOMING_ROLES
from .rooming_presenters import _checkin_item_response as _checkin_item_response
from .rooming_presenters import _default_rooming_tag as _default_rooming_tag
from .rooming_presenters import _family_group_label as _family_group_label
from .rooming_presenters import _family_size as _family_size
from .rooming_presenters import _family_sizes as _family_sizes
from .rooming_presenters import _passenger_response as _passenger_response
from .rooming_presenters import _room_response as _room_response
from .rooming_selection import update_hotel_passenger_selection as update_hotel_passenger_selection
from .rooming_selection import update_hotel_vip_status as update_hotel_vip_status
from .rooming_workspace import _workspace_response as _workspace_response
from .rooming_workspace import get_rooming_priority_fields as get_rooming_priority_fields
from .rooming_workspace import get_rooming_roster_field_values as get_rooming_roster_field_values
from .rooming_workspace import get_rooming_workspace as get_rooming_workspace

router = APIRouter()
_route_modules = (
    _rooming_workspace,
    _rooming_hotels,
    _rooming_selection,
    _rooming_auto_allocation,
    _rooming_exports,
    _rooming_checkins,
)
_routes = {
    route.endpoint: route
    for module in _route_modules
    for route in module.router.routes
    if isinstance(route, APIRoute)
}
_ordered_endpoints = (
    get_rooming_workspace,
    get_rooming_priority_fields,
    get_rooming_roster_field_values,
    create_rooming_hotel,
    update_hotel_passenger_selection,
    update_hotel_vip_status,
    auto_allocate_hotel_rooms,
    update_rooming_hotel,
    generate_rooms,
    update_room,
    update_room_order,
    delete_room,
    update_passenger_allocation,
    export_hotel_rooming_list,
    get_hotel_checkins,
    scan_hotel_checkin,
    update_hotel_checkin,
    export_hotel_checkins,
)
router.routes.extend(_routes[endpoint] for endpoint in _ordered_endpoints)

__all__ = [
    "get_rooming_workspace",
    "get_rooming_priority_fields",
    "get_rooming_roster_field_values",
    "create_rooming_hotel",
    "update_hotel_passenger_selection",
    "update_hotel_vip_status",
    "auto_allocate_hotel_rooms",
    "update_rooming_hotel",
    "generate_rooms",
    "update_room",
    "update_room_order",
    "delete_room",
    "update_passenger_allocation",
    "rooming_excel_support",
    "export_hotel_rooming_list",
    "get_hotel_checkins",
    "scan_hotel_checkin",
    "update_hotel_checkin",
    "export_hotel_checkins",
    "_require_current_allocation",
    "_eligible_group_passengers",
    "_stored_room_plan_matches",
    "_get_rooming_group",
    "_get_rooming_hotel",
    "_get_checkin_hotel",
    "_checkin_dashboard",
    "_checkin_item",
    "_checkin_item_response",
    "_workspace_response",
    "_passenger_response",
    "_family_sizes",
    "_family_size",
    "_default_rooming_tag",
    "_family_group_label",
    "_room_response",
    "_audit",
    "_export_filename",
    "_datetime_is_after",
    "_allocation_state_is_current",
    "ROOMING_ROLES",
    "CHECKIN_ROLES",
    "ROOMING_PASSENGER_STATUSES",
    "router",
]
