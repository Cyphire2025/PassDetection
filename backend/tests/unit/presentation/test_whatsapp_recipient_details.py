"""Manual imported metadata edits preserve scope, identity and provenance."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.domain.entities.entities import UserRole
from app.infrastructure.whatsapp.private_delivery_policy import PrivateDeliveryMutationBlocked
from app.presentation.api.v1.routes import whatsapp_recipient_details as route
from app.presentation.api.v1.schemas.whatsapp_recipient_details_schemas import (
    WhatsAppRecipientDetailsUpdateRequest as Edit,
)


def recipient(**overrides):
    return SimpleNamespace(
        **(
            dict(
                id=uuid.uuid4(),
                name="Annapurna",
                is_source_managed=False,
                imported_fields={
                    "name": "Annapurna",
                    "email": "old@example.com",
                    "bdm_code": "25343",
                    "phone_number": "+919900000001",
                    "source_file": "contacts.xlsx",
                    "source_sheet": "Sheet1",
                    "source_row": "12",
                    "source_order": "4",
                },
                merged_contacts=[],
                phone_number="+919900000001",
                normalized_phone_number="+919900000001",
                suppressed_by_roster_resolution_id=None,
            )
            | overrides
        )
    )


def edit(row, **overrides):
    return Edit(
        **(
            dict(
                expected_name=row.name,
                expected_imported_fields=dict(row.imported_fields),
                name="Annapurna Rao",
                imported_fields={"email": "NEW@EXAMPLE.COM", "bdm_code": "25344"},
            )
            | overrides
        )
    )


def test_edits_existing_fields_and_name_preserving_provenance_phone_and_original():
    row = recipient()
    name, fields, contacts = route.edited_contact_values(row, edit(row))
    assert name == fields["name"] == "Annapurna Rao"
    assert fields["email"] == "new@example.com"
    assert fields["bdm_code"] == "25344"
    assert {
        key: fields[key]
        for key in ("source_file", "source_sheet", "source_row", "source_order", "phone_number")
    } == {
        key: row.imported_fields[key]
        for key in ("source_file", "source_sheet", "source_row", "source_order", "phone_number")
    }
    assert row.imported_fields["email"] == "old@example.com"
    assert contacts is None


def test_blank_detail_clears_only_that_field():
    row = recipient()
    _, fields, _ = route.edited_contact_values(row, edit(row, imported_fields={"email": " "}))
    assert "email" not in fields
    assert fields["bdm_code"] == "25343"


@pytest.mark.parametrize(
    "key",
    [
        "source_file",
        "source_sheet",
        "source_order",
        "source_row",
        "phone_number",
        "name",
        "new_field",
        "Phone Number",
    ],
)
def test_cannot_change_provenance_phone_or_add_keys(key):
    row = recipient()
    with pytest.raises(HTTPException) as error:
        route.edited_contact_values(row, edit(row, imported_fields={key: "changed"}))
    assert error.value.status_code == 400


@pytest.mark.parametrize(
    "changes",
    [
        {"expected_name": "Stale"},
        {"expected_imported_fields": {}},
        {"merged_contact_id": uuid.uuid4()},
    ],
)
def test_rejects_stale_or_missing_identity(changes):
    row = recipient()
    with pytest.raises(HTTPException) as error:
        route.edited_contact_values(row, edit(row, **changes))
    assert error.value.status_code == 409


def test_source_managed_primary_must_be_edited_at_source():
    row = recipient(is_source_managed=True)
    with pytest.raises(HTTPException, match="source record"):
        route.edited_contact_values(row, edit(row))


def test_merged_manual_contact_edit_does_not_change_primary_or_other_snapshot():
    contact_id = uuid.uuid4()
    contact = {
        "id": str(contact_id),
        "source_recipient_id": str(uuid.uuid4()),
        "name": "Other",
        "imported_fields": {"bdm_code": "100", "source_row": "9"},
    }
    untouched = {"id": str(uuid.uuid4()), "name": "Third", "imported_fields": {}}
    row = recipient(is_source_managed=True, merged_contacts=[contact, untouched])
    name, fields, contacts = route.edited_contact_values(
        row,
        edit(
            row,
            merged_contact_id=contact_id,
            expected_name="Other",
            expected_imported_fields=contact["imported_fields"],
            name="Other corrected",
            imported_fields={"bdm_code": "101"},
        ),
    )
    assert name == "Other corrected"
    assert fields == {"bdm_code": "101", "source_row": "9"}
    assert contacts[0]["source_recipient_id"] == contact["source_recipient_id"]
    assert contacts[1] == untouched
    assert row.name == "Annapurna"
    assert contact["name"] == "Other"


def test_request_rejects_oversize_values_extra_fields_and_empty_name():
    row = recipient()
    for changes in (
        {"imported_fields": {"email": "x" * 257}},
        {"phone_number": "+919900000002"},
        {"name": ""},
    ):
        with pytest.raises(ValidationError):
            edit(row, **changes)
    with pytest.raises(HTTPException):
        route.edited_contact_values(row, edit(row, name="   "))


@pytest.fixture
def setup_route(monkeypatch):
    row = recipient()
    group = SimpleNamespace(id=uuid.uuid4(), agency_id=uuid.uuid4(), archived_at=None)
    user = SimpleNamespace(id=uuid.uuid4(), agency_id=group.agency_id, role=UserRole.AGENCY_ADMIN)
    def result(value):
        return MagicMock(scalar_one_or_none=MagicMock(return_value=value))
    session = SimpleNamespace(
        execute=AsyncMock(side_effect=[result(group), result(group), result(row)]),
        flush=AsyncMock(),
    )
    helpers = {}
    for name in (
        "_lock_active_whatsapp_actor",
        "_prepare_private_recipient_mutation",
        "prepare_private_delivery_identity_mutation",
        "suppress_active_replacement_recipients",
        "reconcile_mobile_passenger_access_for_broadcast",
    ):
        helpers[name] = AsyncMock()
        monkeypatch.setattr(route, name, helpers[name])
    monkeypatch.setattr(route, "linked_recipient_source_group_ids", AsyncMock(return_value=set()))
    monkeypatch.setattr(
        route, "active_replacement_resolution_id_for_recipient", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(route, "_group_detail", AsyncMock(return_value="updated-group"))
    return row, group, user, session, helpers


async def test_route_enforces_identity_policy_then_reconciles_access(setup_route):
    row, group, user, session, helpers = setup_route
    result = await route.update_broadcast_recipient_details(
        group.id, row.id, edit(row), user, session
    )
    assert result == "updated-group"
    assert row.name == "Annapurna Rao"
    assert row.normalized_phone_number == "+919900000001"
    assert row.is_source_managed is False
    helpers["_lock_active_whatsapp_actor"].assert_awaited_once()
    helpers["_prepare_private_recipient_mutation"].assert_awaited_once()
    helpers["reconcile_mobile_passenger_access_for_broadcast"].assert_awaited_once()
    # Both tenant and active agency predicates are used for mutation scope.
    query = str(session.execute.call_args_list[1].args[0])
    assert "agency_id" in query and "is_active IS true" in query
    query = str(session.execute.call_args_list[2].args[0])
    assert "broadcast_group_id" in query and "removed_at IS NULL" in query


@pytest.mark.parametrize("block", ["archived", "replacement", "stale", "private_send"])
async def test_blocked_route_leaves_details_untouched(setup_route, block):
    row, group, user, session, helpers = setup_route
    body = edit(row)
    if block == "archived":
        group.archived_at = datetime.now(UTC)
    if block == "replacement":
        row.suppressed_by_roster_resolution_id = uuid.uuid4()
    if block == "stale":
        body.expected_name = "Stale"
    if block == "private_send":
        helpers["_prepare_private_recipient_mutation"].side_effect = HTTPException(
            status_code=409, detail="Delivery is processing"
        )
    with pytest.raises(HTTPException) as error:
        await route.update_broadcast_recipient_details(group.id, row.id, body, user, session)
    assert error.value.status_code == 409
    assert row.name == "Annapurna"
    assert row.imported_fields["email"] == "old@example.com"
    session.flush.assert_not_awaited()


async def test_linked_source_group_policy_blocks_before_edit(setup_route, monkeypatch):
    row, group, user, session, helpers = setup_route
    source_id = uuid.uuid4()
    results = session.execute.side_effect
    # Insert the source-group lock between initial discovery and broadcast lock.
    session.execute.side_effect = [next(results), MagicMock(), next(results), next(results)]
    monkeypatch.setattr(
        route, "linked_recipient_source_group_ids", AsyncMock(return_value={source_id})
    )
    helpers[
        "prepare_private_delivery_identity_mutation"
    ].side_effect = PrivateDeliveryMutationBlocked("Delivery needs review")
    with pytest.raises(HTTPException) as error:
        await route.update_broadcast_recipient_details(group.id, row.id, edit(row), user, session)
    assert error.value.status_code == 409
    assert row.name == "Annapurna"


async def test_missing_or_unauthorized_group_does_not_mutate(setup_route):
    row, group, user, session, helpers = setup_route
    session.execute.side_effect = [MagicMock(scalar_one_or_none=MagicMock(return_value=None))]
    with pytest.raises(HTTPException) as error:
        await route.update_broadcast_recipient_details(group.id, row.id, edit(row), user, session)
    assert error.value.status_code == 404
    helpers["_prepare_private_recipient_mutation"].assert_not_awaited()
