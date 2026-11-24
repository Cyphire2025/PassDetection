"""Legacy GC imports resolve to the currently registered HTTP function objects."""

import importlib

import pytest
from fastapi.routing import APIRoute

ADMIN_HANDLERS = {
    "list_gc_agencies",
    "search_gc_groups",
    "get_gc_group_access",
    "configure_gc_group_access",
    "configure_gc_group_my_photos_feature",
    "refresh_mobile_passenger_identities",
    "list_client_organizations",
    "search_client_organizations",
    "create_client_organization",
    "delete_client_organization",
    "list_client_managers",
    "create_client_manager",
    "update_client_manager",
    "set_client_manager_status",
    "reset_client_manager_password",
    "force_client_manager_password_change",
    "replace_client_manager_groups",
    "revoke_client_manager_sessions",
    "list_client_manager_sessions",
    "list_client_manager_audit",
    "delete_client_manager",
}
CONTENT_HANDLERS = {
    "preview_itinerary",
    "create_itinerary_draft",
    "publish_itinerary",
    "unpublish_itinerary",
    "list_common_documents",
    "upload_common_document",
    "reorder_common_documents",
    "preview_common_document_content",
    "replace_common_document",
    "publish_common_document",
    "unpublish_common_document",
    "delete_common_document",
    "list_announcements",
    "page_announcements",
    "get_announcement_notification_status",
    "create_announcement",
    "update_announcement",
    "publish_announcement",
    "unpublish_announcement",
    "delete_announcement",
    "list_group_gc_audit",
}


@pytest.mark.parametrize(
    "facade,expected", [("gc_app", ADMIN_HANDLERS), ("gc_app_content", CONTENT_HANDLERS)]
)
def test_legacy_router_exports_the_registered_endpoint_identity(facade, expected):
    module = importlib.import_module(f"app.presentation.api.v1.routes.{facade}")
    routes = [route for route in module.router.routes if isinstance(route, APIRoute)]
    assert {route.name for route in routes} == expected
    assert len(routes) == len(expected)
    for route in routes:
        assert getattr(module, route.name) is route.endpoint
