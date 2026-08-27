from __future__ import annotations

from collections.abc import Callable
from types import MappingProxyType

import pytest

from app.domain.exceptions.exceptions import AuthorizationError
from app.presentation.api.v1.routes.gc_app import (
    _client_manager_status,
    _organization_status,
)
from app.presentation.api.v1.routes.gc_app_content import (
    _content_status,
    _itinerary_status,
)
from app.presentation.api.v1.routes.mobile_ops import _attendance_session_status
from app.presentation.api.v1.routes.mobile_ops_notification_support import (
    _mobile_priority,
)
from app.presentation.api.v1.routes.mobile_resources import (
    _mobile_document_content_type,
    _mobile_meal_preference,
    _mobile_principal_type,
    _mobile_sync_operation,
)


@pytest.mark.parametrize(
    ("stored_operation", "expected_operation"),
    [
        ("publish", "upsert"),
        ("upsert", "upsert"),
        ("delete", "delete"),
        ("revoke", "revoke"),
    ],
)
def test_mobile_sync_operation_preserves_installed_client_contract(
    stored_operation: str,
    expected_operation: str,
) -> None:
    assert _mobile_sync_operation(stored_operation) == expected_operation


@pytest.mark.parametrize(
    ("validator", "accepted_values"),
    [
        (_organization_status, ("active", "inactive")),
        (
            _client_manager_status,
            ("active", "suspended", "deleted", "invited"),
        ),
        (_itinerary_status, ("draft", "published", "retired")),
        (
            _content_status,
            ("draft", "published", "retired", "revoked"),
        ),
        (
            _attendance_session_status,
            ("draft", "active", "completed", "cancelled"),
        ),
        (
            _mobile_document_content_type,
            ("application/pdf", "image/jpeg", "image/png", "image/webp"),
        ),
    ],
)
def test_persisted_mobile_enum_boundaries_accept_only_contract_values(
    validator: Callable[[str], str],
    accepted_values: tuple[str, ...],
) -> None:
    for value in accepted_values:
        assert validator(value) == value


@pytest.mark.parametrize(
    "validator",
    [
        _organization_status,
        _client_manager_status,
        _itinerary_status,
        _content_status,
        _attendance_session_status,
        _mobile_document_content_type,
        _mobile_sync_operation,
    ],
)
def test_persisted_mobile_enum_boundaries_fail_closed(
    validator: Callable[[str], str],
) -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        validator("unexpected")


def test_mobile_principal_boundary_is_authorization_safe() -> None:
    for role in ("passenger", "client_manager", "coordinator"):
        assert _mobile_principal_type(role) == role

    with pytest.raises(AuthorizationError, match="not available"):
        _mobile_principal_type("agency_admin")


@pytest.mark.parametrize(
    ("stored_priority", "public_priority"),
    [
        ("normal", "normal"),
        ("high", "important"),
        ("emergency", "emergency"),
        ("unknown-legacy-value", "normal"),
    ],
)
def test_mobile_notification_priority_preserves_legacy_normalization(
    stored_priority: str,
    public_priority: str,
) -> None:
    assert _mobile_priority(stored_priority) == public_priority


def test_mobile_meal_preference_accepts_read_only_validated_mappings() -> None:
    confirmed = MappingProxyType({"meal_preference": "Vegetarian"})

    assert _mobile_meal_preference(confirmed, None) == "Vegetarian"
