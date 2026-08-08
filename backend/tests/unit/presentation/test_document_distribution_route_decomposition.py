"""Compatibility contracts for the document-distribution route facade."""

from __future__ import annotations

import ast
import inspect

from app.presentation.api.v1.routes import (
    document_distribution,
    document_distribution_delivery_support,
    document_distribution_review_support,
)

_EXPECTED_ROUTES = [
    (("GET",), "/groups", "list_document_groups"),
    (("GET",), "/groups/{group_id}/{document_type}", "get_document_review"),
    (("POST",), "/groups/{group_id}/{document_type}/verify", "verify_documents"),
    (("POST",), "/groups/{group_id}/{document_type}/upload", "upload_documents"),
    (
        ("POST",),
        "/groups/{group_id}/{document_type}/uploads/{batch_id}/abort",
        "abort_incomplete_distribution_upload",
    ),
    (
        ("POST",),
        "/groups/{group_id}/{document_type}/passengers/{passenger_id}/reupload",
        "reupload_passenger_document",
    ),
    (
        ("POST",),
        "/groups/{group_id}/{document_type}/documents/unassign",
        "unassign_distribution_documents",
    ),
    (
        ("POST",),
        "/groups/{group_id}/{document_type}/documents/delete",
        "delete_distribution_documents",
    ),
    (("POST",), "/batches/{batch_id}/save", "save_batch"),
    (
        ("GET",),
        "/groups/{group_id}/{document_type}/whatsapp-preview",
        "preview_document_whatsapp_broadcast",
    ),
    (
        ("POST",),
        "/batches/{batch_id}/whatsapp-send",
        "send_document_whatsapp_broadcast",
    ),
    (
        ("GET",),
        "/groups/{group_id}/whatsapp-deliveries/tracking",
        "get_document_delivery_tracking",
    ),
]

_FACADE_NAMES = {
    document_distribution_delivery_support: (
        "DOCUMENT_DELIVERY_ACCEPTED_STATUSES",
        "DOCUMENT_DELIVERY_IN_PROGRESS_STATUSES",
        "DOCUMENT_DELIVERY_STORAGE_REQUIRED_STATUSES",
        "DOCUMENT_DELIVERY_WEBHOOK_GRACE",
        "DOCUMENT_DELIVERY_ACTIVE_POLL_SECONDS",
        "DOCUMENT_DELIVERY_WEBHOOK_POLL_SECONDS",
        "SHARED_WHATSAPP_DESTINATION_REASON",
        "DocumentDeliveryDecision",
        "_document_delivery_poll_after_seconds",
        "_document_delivery_decision",
        "_preferred_document_message_content",
        "_processing_batch_response",
    ),
    document_distribution_review_support: (
        "_LinkedDocumentMatchSource",
        "_owner_scope_for",
        "_submitted_statuses",
        "_passport_number",
        "_safe_filename",
        "_snapshot_value",
        "_linked_document_match_source_from_models",
        "_document_match_roster_snapshot",
        "_passenger_review_rows",
        "_physical_file_accounting",
    ),
}


def _decorated_route_names(module: object) -> list[str]:
    tree = ast.parse(inspect.getsource(module))
    names: list[str] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            function = decorator.func
            if (
                isinstance(function, ast.Attribute)
                and isinstance(function.value, ast.Name)
                and function.value.id == "router"
            ):
                names.append(node.name)
                break
    return names


def test_document_distribution_route_order_and_names_remain_stable() -> None:
    actual = [
        (tuple(sorted(route.methods or ())), route.path, route.name)
        for route in document_distribution.router.routes
    ]
    assert actual == _EXPECTED_ROUTES
    assert _decorated_route_names(document_distribution) == [
        route_name for _, _, route_name in actual
    ]


def test_document_distribution_support_modules_do_not_register_routes() -> None:
    for module in _FACADE_NAMES:
        assert _decorated_route_names(module) == []


def test_document_distribution_facade_preserves_helper_identities() -> None:
    for support_module, names in _FACADE_NAMES.items():
        for name in names:
            assert getattr(document_distribution, name) is getattr(support_module, name)
