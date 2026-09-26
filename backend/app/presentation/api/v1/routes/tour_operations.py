"""Stable tour-operations API facade; cohesive owners register the original routes."""

from fastapi import APIRouter
from fastapi.routing import APIRoute

from app.presentation.api.v1.routes.tour_operations_attendance_projection_support import (
    attendance_activity_valid_after as _attendance_activity_valid_after,
)
from app.presentation.api.v1.routes.tour_operations_attendance_projection_support import (
    attendance_closeout_audit_metadata as _attendance_closeout_audit_metadata,
)
from app.presentation.api.v1.routes.tour_operations_attendance_projection_support import (
    attendance_closeout_counts as _attendance_closeout_counts,
)
from app.presentation.api.v1.routes.tour_operations_attendance_projection_support import (
    attendance_closeout_status_response as _attendance_closeout_status_response,
)
from app.presentation.api.v1.routes.tour_operations_attendance_projection_support import (
    close_shared_attendance_activity as _close_shared_attendance_activity,
)
from app.presentation.api.v1.routes.tour_operations_attendance_projection_support import (
    etag_matches as _etag_matches,
)
from app.presentation.api.v1.routes.tour_operations_attendance_projection_support import (
    require_attendance_closeout_clearance as _require_attendance_closeout_clearance,
)
from app.presentation.api.v1.routes.tour_operations_attendance_scan_support import (
    SCANNABLE_ATTENDANCE_STATUSES as SCANNABLE_ATTENDANCE_STATUSES,
)
from app.presentation.api.v1.routes.tour_operations_attendance_scan_support import (
    SUBMITTED_PASSENGER_STATUSES,
)
from app.presentation.api.v1.routes.tour_operations_attendance_scan_support import (
    attendance_scan_is_within_activity_window as _attendance_scan_is_within_activity_window,
)
from app.presentation.api.v1.routes.tour_operations_attendance_scan_support import (
    counted_attendance_message as _counted_attendance_message,
)
from app.presentation.api.v1.routes.tour_operations_attendance_scan_support import (
    insert_canonical_attendance_record as _insert_canonical_attendance_record,
)
from app.presentation.api.v1.routes.tour_operations_attendance_scan_support import (
    resolve_scannable_passenger as _resolve_scannable_passenger,
)
from app.presentation.api.v1.routes.tour_operations_qr_helpers import (
    get_qr_passenger as _get_qr_passenger,
)
from app.presentation.api.v1.routes.tour_operations_qr_helpers import (
    group_passenger_qr_codes as _group_passenger_qr_codes,
)
from app.presentation.api.v1.routes.tour_operations_qr_helpers import (
    issue_passenger_qr as _issue_passenger_qr,
)
from app.presentation.api.v1.routes.tour_operations_qr_helpers import (
    latest_passenger_qr as _latest_passenger_qr,
)
from app.presentation.api.v1.routes.tour_operations_qr_helpers import qr_hash
from app.presentation.api.v1.routes.tour_operations_qr_helpers import qr_payload as _qr_payload
from app.presentation.api.v1.routes.tour_operations_qr_helpers import qr_status as _qr_status
from app.presentation.api.v1.routes.tour_operations_qr_helpers import (
    qr_token_response as _qr_token_response,
)
from app.presentation.api.v1.routes.tour_operations_qr_helpers import (
    record_qr_audit as _record_qr_audit,
)
from app.presentation.api.v1.routes.tour_operations_response_support import (
    coordinator_responses as _coordinator_responses,
)
from app.presentation.api.v1.routes.tour_operations_response_support import (
    group_responses as _group_responses,
)

from . import (
    tour_operations_accounts,
    tour_operations_assignments,
    tour_operations_attendance_closeout,
    tour_operations_attendance_dashboard,
    tour_operations_attendance_scans,
    tour_operations_attendance_sessions,
    tour_operations_qr,
)
from .tour_operations_access import (
    ATTENDANCE_CLOSURE_ROLES,
    COORDINATOR_ACCOUNT_ROLES,
    COORDINATOR_MANAGEMENT_ROLES,
    TOUR_OPERATION_GROUP_STATUSES,
    TOUR_OPERATION_ROLES,
    _agency_scope,
    _ensure_group_assigned_to_coordinator,
    _get_attendance_close_group_scope,
    _get_coordinator_attendance_session,
    _get_group,
    _get_manageable_group,
    _get_managed_attendance_session,
    _lock_attendance_closeout_group,
    _require_agency,
    _require_assignable_trip,
)
from .tour_operations_accounts import (
    create_coordinator,
    get_tour_operations_architecture,
    list_coordinators,
)
from .tour_operations_activity_lifecycle import (
    _apply_initial_attendance_schedule,
    _canonical_attendance_activity_admission,
    _create_canonical_attendance_activity,
)
from .tour_operations_assignments import (
    assign_group_coordinators,
    assign_group_passengers,
    get_my_group_passenger_detail,
    list_group_passengers,
    list_my_coordinator_groups,
    list_my_group_passengers,
    list_tour_operation_groups,
)
from .tour_operations_attendance_closeout import (
    _load_attendance_closeout_status,
    complete_managed_attendance_session,
    complete_my_attendance_session,
    get_managed_attendance_closeout_status,
    publish_my_attendance_closeout_checkpoint,
)
from .tour_operations_attendance_dashboard import (
    get_group_attendance_missing_passengers,
    get_group_attendance_overview,
    get_group_attendance_summary,
)
from .tour_operations_attendance_scans import (
    record_coordinator_attendance_scan_batch,
    record_my_attendance_scan,
)
from .tour_operations_attendance_sessions import (
    create_managed_attendance_session,
    create_my_attendance_session,
    get_my_attendance_session_details,
    list_my_attendance_sessions,
    update_managed_attendance_schedule,
)
from .tour_operations_attendance_views import (
    _attendance_counts,
    _attendance_scan_response,
    _attendance_session_details_response,
    _attendance_session_response,
    _attendance_session_responses,
    _group_attendance_overview,
)
from .tour_operations_passenger_views import (
    _family_group_label,
    _family_size,
    _family_sizes,
    _group_passenger_responses,
)
from .tour_operations_qr import (
    generate_passenger_qr,
    get_group_passenger_qr_codes,
    regenerate_passenger_qr,
    revoke_passenger_qr,
    set_passenger_qr_active,
    set_passenger_qr_expiration,
)

_qr_hash = qr_hash

router = APIRouter()

_routes = {
    route.endpoint: route
    for module in (
        tour_operations_accounts,
        tour_operations_assignments,
        tour_operations_qr,
        tour_operations_attendance_sessions,
        tour_operations_attendance_scans,
        tour_operations_attendance_closeout,
        tour_operations_attendance_dashboard,
    )
    for route in module.router.routes
    if isinstance(route, APIRoute)
}

_ordered_endpoints = (
    get_tour_operations_architecture,
    list_coordinators,
    create_coordinator,
    list_tour_operation_groups,
    assign_group_coordinators,
    list_group_passengers,
    get_group_passenger_qr_codes,
    generate_passenger_qr,
    regenerate_passenger_qr,
    revoke_passenger_qr,
    set_passenger_qr_active,
    set_passenger_qr_expiration,
    assign_group_passengers,
    list_my_coordinator_groups,
    list_my_group_passengers,
    get_my_group_passenger_detail,
    create_my_attendance_session,
    create_managed_attendance_session,
    update_managed_attendance_schedule,
    list_my_attendance_sessions,
    get_my_attendance_session_details,
    record_my_attendance_scan,
    record_coordinator_attendance_scan_batch,
    publish_my_attendance_closeout_checkpoint,
    complete_my_attendance_session,
    complete_managed_attendance_session,
    get_managed_attendance_closeout_status,
    get_group_attendance_overview,
    get_group_attendance_summary,
    get_group_attendance_missing_passengers,
)

for endpoint in _ordered_endpoints:
    router.routes.append(_routes[endpoint])

__all__ = [
    "_require_agency",
    "_agency_scope",
    "get_tour_operations_architecture",
    "list_coordinators",
    "create_coordinator",
    "list_tour_operation_groups",
    "assign_group_coordinators",
    "list_group_passengers",
    "get_group_passenger_qr_codes",
    "generate_passenger_qr",
    "regenerate_passenger_qr",
    "revoke_passenger_qr",
    "set_passenger_qr_active",
    "set_passenger_qr_expiration",
    "assign_group_passengers",
    "list_my_coordinator_groups",
    "list_my_group_passengers",
    "get_my_group_passenger_detail",
    "create_my_attendance_session",
    "create_managed_attendance_session",
    "update_managed_attendance_schedule",
    "list_my_attendance_sessions",
    "get_my_attendance_session_details",
    "record_my_attendance_scan",
    "record_coordinator_attendance_scan_batch",
    "_load_attendance_closeout_status",
    "publish_my_attendance_closeout_checkpoint",
    "complete_my_attendance_session",
    "complete_managed_attendance_session",
    "get_managed_attendance_closeout_status",
    "get_group_attendance_overview",
    "get_group_attendance_summary",
    "get_group_attendance_missing_passengers",
    "_get_group",
    "_lock_attendance_closeout_group",
    "_require_assignable_trip",
    "_get_manageable_group",
    "_canonical_attendance_activity_admission",
    "_create_canonical_attendance_activity",
    "_apply_initial_attendance_schedule",
    "_get_managed_attendance_session",
    "_get_attendance_close_group_scope",
    "_ensure_group_assigned_to_coordinator",
    "_get_coordinator_attendance_session",
    "_attendance_session_response",
    "_attendance_session_responses",
    "_attendance_scan_response",
    "_attendance_session_details_response",
    "_attendance_counts",
    "_group_attendance_overview",
    "_group_passenger_responses",
    "_family_sizes",
    "_family_size",
    "_family_group_label",
    "TOUR_OPERATION_ROLES",
    "COORDINATOR_MANAGEMENT_ROLES",
    "COORDINATOR_ACCOUNT_ROLES",
    "ATTENDANCE_CLOSURE_ROLES",
    "TOUR_OPERATION_GROUP_STATUSES",
    "_attendance_activity_valid_after",
    "_attendance_closeout_audit_metadata",
    "_attendance_closeout_counts",
    "_attendance_closeout_status_response",
    "_close_shared_attendance_activity",
    "_etag_matches",
    "_require_attendance_closeout_clearance",
    "SCANNABLE_ATTENDANCE_STATUSES",
    "SUBMITTED_PASSENGER_STATUSES",
    "_attendance_scan_is_within_activity_window",
    "_counted_attendance_message",
    "_insert_canonical_attendance_record",
    "_resolve_scannable_passenger",
    "_get_qr_passenger",
    "_group_passenger_qr_codes",
    "_issue_passenger_qr",
    "_latest_passenger_qr",
    "qr_hash",
    "_qr_payload",
    "_qr_status",
    "_qr_token_response",
    "_record_qr_audit",
    "_coordinator_responses",
    "_group_responses",
    "_qr_hash",
    "router",
]
