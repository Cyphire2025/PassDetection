"""Malformed contact containers fail before actor admission or database writes."""

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.domain.entities.entities import UserRole
from app.presentation.api.v1.routes import whatsapp_groups_manage
from app.presentation.api.v1.routes.whatsapp_contact_support import (
    _parse_imported_field_keys,
    _parse_rejected_contacts,
    _parse_support_contacts,
)


def _rejected(**changes):
    return {
        "source_file_name": "synthetic.xlsx",
        "sheet_name": "Contacts",
        "row_number": 2,
        "raw_name": "Synthetic Person",
        "raw_phone_number": None,
        "imported_fields": {},
        "reason_code": "missing_phone",
        **changes,
    }


@pytest.mark.parametrize("manual", ["{}", '""', "null", '{"unexpected":1}'])
async def test_create_rejects_non_array_manual_json_before_admission(monkeypatch, manual):
    actor = SimpleNamespace(id=uuid.uuid4(), agency_id=uuid.uuid4(), role=UserRole.AGENCY_ADMIN)
    admission, create = AsyncMock(return_value=actor), AsyncMock(return_value=object())
    monkeypatch.setattr(whatsapp_groups_manage, "_lock_active_whatsapp_actor", admission)
    monkeypatch.setattr(whatsapp_groups_manage, "create_new_broadcast", create)
    monkeypatch.setattr(whatsapp_groups_manage, "_group_detail", AsyncMock(return_value={}))
    session = MagicMock(rollback=AsyncMock())
    with pytest.raises(HTTPException) as denied:
        await whatsapp_groups_manage.create_broadcast_group(
            name="Synthetic trip",
            organizing_company_name=None,
            contacts_json=manual,
            imported_field_keys_json="[]",
            rejected_contacts_json=json.dumps([_rejected()]),
            support_contacts_json=json.dumps(
                [{"name": "Synthetic Support", "phone_number": "+919876543210"}]
            ),
            recipient_opt_in_confirmed=True,
            contacts_file=None,
            duplicate_source_files=None,
            current_user=actor,
            session=session,
        )
    assert denied.value.status_code == 400 and denied.value.detail == "Invalid manual contact list"
    admission.assert_not_awaited()
    create.assert_not_awaited()
    session.add.assert_not_called()


async def test_create_keeps_valid_empty_array_with_rejected_only_roster(monkeypatch):
    actor = SimpleNamespace(id=uuid.uuid4(), agency_id=uuid.uuid4(), role=UserRole.AGENCY_ADMIN)
    created, response = object(), object()
    create = AsyncMock(return_value=created)
    monkeypatch.setattr(
        whatsapp_groups_manage, "_lock_active_whatsapp_actor", AsyncMock(return_value=actor)
    )
    monkeypatch.setattr(whatsapp_groups_manage, "create_new_broadcast", create)
    monkeypatch.setattr(whatsapp_groups_manage, "_group_detail", AsyncMock(return_value=response))
    actual = await whatsapp_groups_manage.create_broadcast_group(
        name="Synthetic trip",
        organizing_company_name=None,
        contacts_json="[]",
        imported_field_keys_json="[]",
        rejected_contacts_json=json.dumps([_rejected()]),
        support_contacts_json=json.dumps(
            [{"name": "Synthetic Support", "phone_number": "+919876543210"}]
        ),
        recipient_opt_in_confirmed=False,
        contacts_file=None,
        duplicate_source_files=None,
        current_user=actor,
        session=MagicMock(rollback=AsyncMock()),
    )
    assert actual is response
    assert create.await_args.kwargs["contacts"] == []
    assert len(create.await_args.kwargs["rejected_contacts"]) == 1
    assert create.await_args.kwargs["recipient_opt_in_confirmed"] is False


@pytest.mark.parametrize(
    "payload",
    ["{}", '""', "null", "[{}]", "[]", '[{"name":"Synthetic Support","phone_number":"invalid"}]'],
)
def test_support_contact_json_rejects_invalid_shape_or_delivery_identity(payload):
    with pytest.raises(HTTPException) as denied:
        _parse_support_contacts(payload)
    assert denied.value.status_code == 400


def test_support_contacts_deduplicate_normalized_phones_and_reject_four_recipients():
    first = {"name": "Synthetic Support", "phone_number": "+919876543210"}
    assert (
        len(
            _parse_support_contacts(
                json.dumps([first, {**first, "phone_number": "00919876543210"}])
            )
        )
        == 1
    )
    with pytest.raises(HTTPException) as denied:
        _parse_support_contacts(
            json.dumps([{**first, "phone_number": f"+91987654321{n}"} for n in range(4)])
        )
    assert denied.value.status_code == 400


@pytest.mark.parametrize(
    "payload",
    [
        "{}",
        "not-json",
        json.dumps([_rejected(source_file_name="///")]),
        json.dumps([_rejected(sheet_name=" ")]),
    ],
)
def test_rejected_contact_json_requires_bounded_valid_source_identity(payload):
    with pytest.raises(HTTPException) as denied:
        _parse_rejected_contacts(payload)
    assert denied.value.status_code == 400


def test_rejected_rows_deduplicate_after_source_filename_normalization():
    rows = _parse_rejected_contacts(
        json.dumps([_rejected(), _rejected(source_file_name="folder/synthetic.xlsx")])
    )
    assert len(rows) == 1 and rows[0].source_file_name == "synthetic.xlsx"


@pytest.mark.parametrize(
    "payload", ["not-json", "{}", "[3]", json.dumps([f"field_{n}" for n in range(257)])]
)
def test_imported_heading_json_rejects_malformed_or_oversized_catalog(payload):
    with pytest.raises(HTTPException) as denied:
        _parse_imported_field_keys(payload)
    assert denied.value.status_code == 400
