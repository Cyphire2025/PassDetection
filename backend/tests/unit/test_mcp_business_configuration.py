"""Configuration must be explicit without placing credentials in the MCP schema."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.presentation.mcp.business_admin_tools import (
    BUSINESS_TOOL_MODELS,
    MCPClientManagerAccount,
    MCPGCGroupSettings,
    MCPGCMyPhotos,
    MCPPublishItinerary,
    MCPWorkforceAccount,
    validate_business,
    workforce_permission_sections,
)
from app.presentation.mcp.invocation import MCPInputError


def workforce():
    return dict(
        agency_id=str(uuid.uuid4()),
        account_type="coordinator",
        full_name="Invited person",
        email="person@example.com",
        credential_delivery="dashboard_activation",
    )


@pytest.mark.parametrize(
    "extra",
    [
        {"password": "private-not-to-be-reflected"},
        {"activation_token": "private-not-to-be-reflected"},
        {"mcp_authority": True},
        {"account_type": "super_admin"},
        {"full_name": " "},
        {"credential_delivery": "send_invite"},
    ],
)
def test_no_credentials_or_implicit_authority_in_account_inputs(extra):
    with pytest.raises(MCPInputError) as caught:
        validate_business("create_workforce_account", {**workforce(), **extra})
    assert "private-not-to-be-reflected" not in str(caught.value)


def test_required_account_handoff_and_duplicate_group_validation():
    body = workforce()
    del body["credential_delivery"]
    with pytest.raises(ValidationError):
        MCPWorkforceAccount.model_validate(body)
    group_id = str(uuid.uuid4())
    manager_body = workforce()
    del manager_body["account_type"]
    with pytest.raises(ValidationError):
        MCPClientManagerAccount.model_validate(
            {
                **manager_body,
                "organization_id": str(uuid.uuid4()),
                "phone_number": "+919876543210",
                "group_ids": [group_id, group_id],
            }
        )


def gc_settings():
    return dict(
        agency_id=str(uuid.uuid4()),
        group_id=str(uuid.uuid4()),
        client_organization_id=str(uuid.uuid4()),
        enabled=False,
        passenger_access_enabled=False,
        client_manager_access_enabled=False,
        coordinator_access_enabled=False,
    )


@pytest.mark.parametrize(
    "missing",
    [
        "enabled",
        "passenger_access_enabled",
        "client_manager_access_enabled",
        "coordinator_access_enabled",
        "client_organization_id",
    ],
)
def test_gc_access_choices_cannot_silently_default(missing):
    body = gc_settings()
    del body[missing]
    with pytest.raises(ValidationError):
        MCPGCGroupSettings.model_validate(body)


@pytest.mark.parametrize(
    "extra",
    [
        {"access_starts_at": "2030-01-01T00:00:00"},
        {
            "access_starts_at": "2030-01-02T00:00:00+00:00",
            "access_expires_at": "2030-01-01T00:00:00+00:00",
        },
        {"expected_revision": True},
        {"expected_revision": 0},
        {"replace_history": True},
    ],
)
def test_gc_windows_and_revisions_have_strict_meaning(extra):
    with pytest.raises(ValidationError):
        MCPGCGroupSettings.model_validate({**gc_settings(), **extra})


@pytest.mark.parametrize(
    "model,revision_field",
    [(MCPGCMyPhotos, "expected_revision"), (MCPPublishItinerary, "expected_access_revision")],
)
def test_existing_changes_require_integer_revision(model, revision_field):
    payload = dict(agency_id=str(uuid.uuid4()), group_id=str(uuid.uuid4()))
    payload.update(enabled=True) if model is MCPGCMyPhotos else payload.update(
        version_id=str(uuid.uuid4())
    )
    for invalid in (None, True, "1", 0):
        with pytest.raises(ValidationError):
            model.model_validate({**payload, revision_field: invalid})


@pytest.mark.parametrize("invalid", [None, [], {}, "super_admin"])
def test_dynamic_role_policy_fails_closed_on_missing_or_untyped_role(invalid):
    with pytest.raises(MCPInputError):
        workforce_permission_sections({"account_type": invalid})


def test_schema_describes_handoff_and_never_accepts_password_fields():
    for name in ("create_workforce_account", "create_gc_client_manager_account"):
        schema = BUSINESS_TOOL_MODELS[name].model_json_schema()
        assert schema["additionalProperties"] is False
        assert "credential_delivery" in schema["required"]
        assert (
            not {"password", "activation_token", "invite_token", "mcp_authority"}
            & schema["properties"].keys()
        )
