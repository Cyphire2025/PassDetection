"""Invitation name validation honors trimmed minimums and original raw bounds."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.presentation.api.v1.schemas.operations_schemas import (
    CreateManagerRequest,
    CreateStaffRequest,
)

INVITATION_TYPES = [CreateManagerRequest, CreateStaffRequest]


@pytest.mark.parametrize("request_type", INVITATION_TYPES)
@pytest.mark.parametrize("name", ["  ", " \t\n ", " A "])
def test_invitation_rejects_name_below_minimum_after_trimming(request_type, name):
    with pytest.raises(ValidationError) as invalid:
        request_type(full_name=name, email="synthetic@example.com")
    assert invalid.value.errors()[0]["loc"] == ("full_name",)


@pytest.mark.parametrize("request_type", INVITATION_TYPES)
@pytest.mark.parametrize("name", ["  Ada Lovelace  ", "  निपुण शर्मा  ", "A" * 255])
def test_valid_invitation_names_keep_unicode_and_original_length_contract(request_type, name):
    request = request_type(full_name=name, email="synthetic@example.com")
    assert request.full_name.strip() == name.strip()
    assert request.email == "synthetic@example.com"


@pytest.mark.parametrize("request_type", INVITATION_TYPES)
def test_invitation_raw_length_bound_is_applied_before_normalization(request_type):
    with pytest.raises(ValidationError) as invalid:
        request_type(full_name=" " * 255 + "AB", email="synthetic@example.com")
    assert invalid.value.errors()[0]["type"] == "string_too_long"


@pytest.mark.parametrize("request_type", INVITATION_TYPES)
def test_invitation_preserves_unknown_field_rejection(request_type):
    with pytest.raises(ValidationError):
        request_type.model_validate({"full_name": "Synthetic staff", "email": "synthetic@example.com", "role": "super_admin"})
