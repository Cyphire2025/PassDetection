"""Compatibility contracts for the decomposed email-integration route facade."""

from __future__ import annotations

import ast
import inspect

from app.presentation.api.v1.routes import (
    email_integration_policy_support,
    email_integration_review_support,
    email_integrations,
)

_EXPECTED_ROUTES = [
    (("GET",), "/status", "email_integration_status"),
    (("GET",), "/connections", "list_email_connections"),
    (("POST",), "/oauth/gmail/authorize", "authorize_gmail"),
    (("GET",), "/oauth/gmail/callback", "gmail_oauth_callback"),
    (("POST",), "/oauth/outlook/authorize", "authorize_outlook"),
    (("GET",), "/oauth/outlook/callback", "outlook_oauth_callback"),
    (("POST",), "/connections/{connection_id}/sync", "sync_connection"),
    (("POST",), "/connections/{connection_id}/pause", "pause_connection"),
    (("POST",), "/connections/{connection_id}/resume", "resume_connection"),
    (("DELETE",), "/connections/{connection_id}", "disconnect_email_connection"),
    (
        ("DELETE",),
        "/connections/{connection_id}/data",
        "remove_email_connection_and_data",
    ),
    (
        ("PUT",),
        "/connections/{connection_id}/ai-settings",
        "update_connection_ai_settings",
    ),
    (("GET",), "/summary", "email_integration_summary"),
    (("GET",), "/reviews", "list_email_reviews"),
    (("GET",), "/review-options", "email_review_options"),
    (("POST",), "/reviews/{review_id}/resolve", "resolve_email_review"),
    (("GET",), "/activity", "email_activity"),
    (("GET",), "/messages/{message_id}", "email_message_detail"),
]

_FACADE_NAMES = {
    email_integration_policy_support: (
        "_provider_configured",
        "_provider_scopes",
        "_secret_is_set",
        "_require_feature",
        "_oauth_return_url",
        "_allowed_connection_actions",
        "_email_removal_confirmation_matches",
    ),
    email_integration_review_support: (
        "_original_email_url",
        "_string_list",
        "_allowed_review_actions",
        "_display_conflicts",
        "_passport_number_hint",
        "_artifact_source_host",
        "_event_title",
        "_event_detail",
        "_bounded_event_value",
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


def test_email_integration_route_order_and_names_remain_stable() -> None:
    actual = [
        (tuple(sorted(route.methods or ())), route.path, route.name)
        for route in email_integrations.router.routes
    ]
    assert actual == _EXPECTED_ROUTES
    assert _decorated_route_names(email_integrations) == [route_name for _, _, route_name in actual]


def test_email_integration_support_modules_do_not_register_routes() -> None:
    for module in _FACADE_NAMES:
        assert _decorated_route_names(module) == []


def test_email_integration_facade_preserves_helper_identities() -> None:
    for support_module, names in _FACADE_NAMES.items():
        for name in names:
            assert getattr(email_integrations, name) is getattr(support_module, name)
