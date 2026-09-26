"""Stable API registration and facade identities across cohesive tour modules."""

from fastapi.routing import APIRoute

from app.presentation.api.v1.routes import tour_operations

EXPECTED_ROUTES = [
    (["GET"], "/architecture", "get_tour_operations_architecture"),
    (["GET"], "/coordinators", "list_coordinators"),
    (["POST"], "/coordinators", "create_coordinator"),
    (["GET"], "/groups", "list_tour_operation_groups"),
    (["PUT"], "/groups/{group_id}/coordinators", "assign_group_coordinators"),
    (["GET"], "/groups/{group_id}/passengers", "list_group_passengers"),
    (["GET"], "/groups/{group_id}/qr-codes", "get_group_passenger_qr_codes"),
    (["POST"], "/groups/{group_id}/passengers/{passenger_id}/qr", "generate_passenger_qr"),
    (
        ["POST"],
        "/groups/{group_id}/passengers/{passenger_id}/qr/regenerate",
        "regenerate_passenger_qr",
    ),
    (["POST"], "/groups/{group_id}/passengers/{passenger_id}/qr/revoke", "revoke_passenger_qr"),
    (
        ["PATCH"],
        "/groups/{group_id}/passengers/{passenger_id}/qr/active",
        "set_passenger_qr_active",
    ),
    (
        ["PATCH"],
        "/groups/{group_id}/passengers/{passenger_id}/qr/expiration",
        "set_passenger_qr_expiration",
    ),
    (["PUT"], "/groups/{group_id}/passengers/assign", "assign_group_passengers"),
    (["GET"], "/coordinator/groups", "list_my_coordinator_groups"),
    (["GET"], "/coordinator/groups/{group_id}/passengers", "list_my_group_passengers"),
    (
        ["GET"],
        "/coordinator/groups/{group_id}/passengers/{passenger_id}",
        "get_my_group_passenger_detail",
    ),
    (["POST"], "/coordinator/groups/{group_id}/sessions", "create_my_attendance_session"),
    (["POST"], "/groups/{group_id}/attendance/sessions", "create_managed_attendance_session"),
    (
        ["PUT"],
        "/groups/{group_id}/attendance/sessions/{session_id}/schedule",
        "update_managed_attendance_schedule",
    ),
    (["GET"], "/coordinator/groups/{group_id}/sessions", "list_my_attendance_sessions"),
    (["GET"], "/coordinator/sessions/{session_id}/details", "get_my_attendance_session_details"),
    (["POST"], "/coordinator/sessions/{session_id}/scan", "record_my_attendance_scan"),
    (
        ["POST"],
        "/coordinator/sessions/{session_id}/scan/batch",
        "record_coordinator_attendance_scan_batch",
    ),
    (
        ["PUT"],
        "/coordinator/groups/{group_id}/sessions/{session_id}/closeout-checkpoint",
        "publish_my_attendance_closeout_checkpoint",
    ),
    (["PUT"], "/coordinator/sessions/{session_id}/complete", "complete_my_attendance_session"),
    (
        ["PUT"],
        "/groups/{group_id}/attendance/sessions/{session_id}/complete",
        "complete_managed_attendance_session",
    ),
    (
        ["GET"],
        "/groups/{group_id}/attendance/sessions/{session_id}/closeout",
        "get_managed_attendance_closeout_status",
    ),
    (["GET"], "/groups/{group_id}/attendance", "get_group_attendance_overview"),
    (["GET"], "/groups/{group_id}/attendance/summary", "get_group_attendance_summary"),
    (
        ["GET"],
        "/groups/{group_id}/attendance/sessions/{session_id}/missing",
        "get_group_attendance_missing_passengers",
    ),
]


def test_tour_route_order_paths_methods_and_identities_are_preserved():
    routes = [route for route in tour_operations.router.routes if isinstance(route, APIRoute)]
    assert [(sorted(route.methods), route.path, route.name) for route in routes] == EXPECTED_ROUTES
    for route in routes:
        assert route.endpoint is getattr(tour_operations, route.name)
        assert route.endpoint.__module__ != tour_operations.__name__


def test_original_mobile_and_runtime_helper_imports_keep_defining_identities():
    from app.presentation.api.v1.routes import attendance_runtime, mobile_ops

    for name in (
        "_canonical_attendance_activity_admission",
        "_create_canonical_attendance_activity",
        "_load_attendance_closeout_status",
        "_lock_attendance_closeout_group",
    ):
        assert getattr(mobile_ops, name) is getattr(tour_operations, name)
    for name in (
        "_ensure_group_assigned_to_coordinator",
        "_get_coordinator_attendance_session",
        "_require_agency",
    ):
        assert getattr(attendance_runtime, name) is getattr(tour_operations, name)
