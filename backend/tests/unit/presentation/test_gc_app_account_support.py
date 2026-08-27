"""Characterization tests for GC client-manager persistence normalization."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.presentation.api.v1.routes.gc_app_account_support import (
    client_manager_duplicate_message,
    client_manager_status,
    integrity_constraint_name,
    organization_status,
)


class _ConstraintFailure(Exception):
    def __init__(self, constraint_name: str) -> None:
        super().__init__(constraint_name)
        self.constraint_name = constraint_name


def test_gc_account_support_maps_only_reviewed_constraints_and_statuses() -> None:
    duplicate = IntegrityError(
        "insert client manager",
        {},
        _ConstraintFailure("uq_client_manager_phone_live"),
    )
    assert integrity_constraint_name(duplicate) == "uq_client_manager_phone_live"
    assert client_manager_duplicate_message(duplicate) == (
        "Mobile number is already assigned to another Client Manager"
    )
    assert organization_status("active") == "active"
    assert client_manager_status("invited") == "invited"

    unrelated = IntegrityError("insert client manager", {}, RuntimeError("failure"))
    assert integrity_constraint_name(unrelated) is None
    assert client_manager_duplicate_message(unrelated) is None
    with pytest.raises(ValueError, match="Unsupported client organization status"):
        organization_status("deleted")
    with pytest.raises(ValueError, match="Unsupported client manager status"):
        client_manager_status("unknown")
