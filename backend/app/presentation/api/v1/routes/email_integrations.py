"""Stable email router facade; cohesive modules own policy and lifecycle code."""

from fastapi import APIRouter
from fastapi.routing import APIRoute

from . import (
    email_integration_activity,
    email_integration_connections,
    email_integration_gmail,
    email_integration_outlook,
    email_integration_review_decisions,
    email_integration_review_queries,
)
from .email_integration_access import (
    _ACTIVE_CONNECTION_STATUSES,
    _ACTIVE_REVIEW_STATUSES,
    EMAIL_INTEGRATION_ROLES,
    _agency_scope,
    _current_email_user,
    _default_organization_agency_id,
    _email_owner_filters,
    _enqueue_connection_sync,
    _group_role_visibility_filter,
    _owned_connection,
    _passport_role_visibility_filter,
    _provider_instance,
    _require_provider_account_owner,
)
from .email_integration_activity import (
    email_activity,
    email_integration_summary,
    email_message_detail,
)
from .email_integration_connections import (
    disconnect_email_connection,
    email_integration_status,
    list_email_connections,
    pause_connection,
    remove_email_connection_and_data,
    resume_connection,
    sync_connection,
    update_connection_ai_settings,
)
from .email_integration_gmail import authorize_gmail, gmail_oauth_callback
from .email_integration_outlook import authorize_outlook, outlook_oauth_callback
from .email_integration_policy_support import (
    _allowed_connection_actions as _allowed_connection_actions,
)
from .email_integration_policy_support import (
    _email_removal_confirmation_matches as _email_removal_confirmation_matches,
)
from .email_integration_policy_support import _oauth_return_url as _oauth_return_url
from .email_integration_policy_support import _provider_configured as _provider_configured
from .email_integration_policy_support import _provider_scopes as _provider_scopes
from .email_integration_policy_support import _require_feature as _require_feature
from .email_integration_policy_support import _secret_is_set as _secret_is_set
from .email_integration_review_decisions import resolve_email_review
from .email_integration_review_queries import email_review_options, list_email_reviews
from .email_integration_review_support import _allowed_review_actions as _allowed_review_actions
from .email_integration_review_support import _artifact_source_host as _artifact_source_host
from .email_integration_review_support import _bounded_event_value as _bounded_event_value
from .email_integration_review_support import _display_conflicts as _display_conflicts
from .email_integration_review_support import _event_detail as _event_detail
from .email_integration_review_support import _event_title as _event_title
from .email_integration_review_support import _original_email_url as _original_email_url
from .email_integration_review_support import _passport_number_hint as _passport_number_hint
from .email_integration_review_support import _string_list as _string_list

router = APIRouter()
_routes = {
    route.endpoint: route
    for module in (
        email_integration_gmail,
        email_integration_outlook,
        email_integration_connections,
        email_integration_review_queries,
        email_integration_review_decisions,
        email_integration_activity,
    )
    for route in module.router.routes
    if isinstance(route, APIRoute)
}
_ordered_endpoints = (
    email_integration_status,
    list_email_connections,
    authorize_gmail,
    gmail_oauth_callback,
    authorize_outlook,
    outlook_oauth_callback,
    sync_connection,
    pause_connection,
    resume_connection,
    disconnect_email_connection,
    remove_email_connection_and_data,
    update_connection_ai_settings,
    email_integration_summary,
    list_email_reviews,
    email_review_options,
    resolve_email_review,
    email_activity,
    email_message_detail,
)
for endpoint in _ordered_endpoints:
    router.routes.append(_routes[endpoint])

__all__ = [
    "_provider_instance",
    "_agency_scope",
    "_email_owner_filters",
    "_group_role_visibility_filter",
    "_passport_role_visibility_filter",
    "_require_provider_account_owner",
    "_default_organization_agency_id",
    "_owned_connection",
    "_enqueue_connection_sync",
    "EMAIL_INTEGRATION_ROLES",
    "_current_email_user",
    "_ACTIVE_CONNECTION_STATUSES",
    "_ACTIVE_REVIEW_STATUSES",
    "authorize_gmail",
    "gmail_oauth_callback",
    "authorize_outlook",
    "outlook_oauth_callback",
    "email_integration_status",
    "list_email_connections",
    "sync_connection",
    "pause_connection",
    "resume_connection",
    "disconnect_email_connection",
    "remove_email_connection_and_data",
    "update_connection_ai_settings",
    "list_email_reviews",
    "email_review_options",
    "resolve_email_review",
    "email_integration_summary",
    "email_activity",
    "email_message_detail",
    "_provider_configured",
    "_provider_scopes",
    "_secret_is_set",
    "_require_feature",
    "_oauth_return_url",
    "_allowed_connection_actions",
    "_email_removal_confirmation_matches",
    "_original_email_url",
    "_string_list",
    "_allowed_review_actions",
    "_display_conflicts",
    "_passport_number_hint",
    "_artifact_source_host",
    "_event_title",
    "_event_detail",
    "_bounded_event_value",
    "router",
]
