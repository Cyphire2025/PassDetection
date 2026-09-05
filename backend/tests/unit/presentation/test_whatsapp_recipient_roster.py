from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from openpyxl import Workbook

from app.domain.entities.entities import UserRole
from app.infrastructure.database.models import (
    ClientGroupModel,
    PassportRosterResolutionModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastRejectedContactModel,
    WhatsAppRecipientMessageStateModel,
)
from app.presentation.api.v1.routes import whatsapp as whatsapp_routes
from app.presentation.api.v1.routes.whatsapp import (
    WhatsAppRecipientInput,
    WhatsAppRejectedContactInput,
    _new_roster_display_orders,
    _normalized_recipient_inputs,
    _parse_excel_contact_bytes,
    _rejected_contact_fingerprint,
    get_broadcast_recipient_roster,
    list_broadcast_groups,
)
from tests.route_dependencies import set_route_dependency


def _excel_payload() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Delegates"
    sheet.append(["Name", "Mobile"])
    sheet.append(["Accepted First", "9876543210"])
    sheet.append(["Rejected Middle", "919726092"])
    sheet.append(["Accepted Last", "9876543211"])
    payload = BytesIO()
    workbook.save(payload)
    return payload.getvalue()


def test_excel_source_order_preserves_accepted_and_rejected_interleaving() -> None:
    parsed = _parse_excel_contact_bytes(
        _excel_payload(),
        filename=r"C:\uploads\delegates.xlsx",
    )

    assert [contact.imported_fields["source_order"] for contact in parsed.contacts] == [
        "1",
        "3",
    ]
    assert len(parsed.rejected_rows) == 1
    rejected_row = parsed.rejected_rows[0]
    assert rejected_row.imported_fields["source_file"] == "delegates.xlsx"
    assert rejected_row.imported_fields["source_sheet"] == "Delegates"
    assert rejected_row.imported_fields["source_row"] == "3"
    assert rejected_row.imported_fields["source_order"] == "2"

    rejected_contact = WhatsAppRejectedContactInput(
        source_file_name="delegates.xlsx",
        sheet_name=rejected_row.sheet_name,
        row_number=rejected_row.row_number,
        raw_name=rejected_row.raw_name,
        raw_phone_number=rejected_row.raw_phone_number,
        imported_fields=rejected_row.imported_fields,
        reason_code=rejected_row.reason_code,
    )
    recipient_orders, rejected_orders = _new_roster_display_orders(
        normalized_contacts=_normalized_recipient_inputs(parsed.contacts),
        rejected_contacts=[rejected_contact],
        existing_by_phone={},
        existing_by_fingerprint={},
        start_order=1,
    )

    assert sorted(recipient_orders.values()) == [1, 3]
    assert list(rejected_orders.values()) == [2]


@pytest.mark.asyncio
async def test_recipient_roster_merges_rows_and_reports_delivery_counts() -> None:
    group_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    group = WhatsAppBroadcastGroupModel(
        id=group_id,
        agency_id=agency_id,
        name="Delegates",
        organizing_company_name="Global Connect Travels",
        created_at=now,
        updated_at=now,
    )
    sent_recipient = WhatsAppBroadcastRecipientModel(
        id=uuid.uuid4(),
        broadcast_group_id=group_id,
        agency_id=agency_id,
        name="Accepted First",
        phone_number="+919876543210",
        normalized_phone_number="+919876543210",
        imported_fields={"source_order": "1"},
        display_order=1,
        removed_at=None,
        created_at=now,
    )
    failed_recipient = WhatsAppBroadcastRecipientModel(
        id=uuid.uuid4(),
        broadcast_group_id=group_id,
        agency_id=agency_id,
        name="Accepted Last",
        phone_number="+919876543211",
        normalized_phone_number="+919876543211",
        imported_fields={"source_order": "3"},
        display_order=3,
        removed_at=None,
        created_at=now + timedelta(seconds=2),
    )
    never_sent_recipient = WhatsAppBroadcastRecipientModel(
        id=uuid.uuid4(),
        broadcast_group_id=group_id,
        agency_id=agency_id,
        name="Accepted Never Sent",
        phone_number="+919876543212",
        normalized_phone_number="+919876543212",
        imported_fields={"source_order": "4"},
        display_order=4,
        removed_at=None,
        created_at=now + timedelta(seconds=3),
    )
    rejected = WhatsAppBroadcastRejectedContactModel(
        id=uuid.uuid4(),
        broadcast_group_id=group_id,
        agency_id=agency_id,
        source_file_name="delegates.xlsx",
        sheet_name="Delegates",
        row_number=3,
        raw_name="Rejected Middle",
        raw_phone_number="919726092",
        imported_fields={"source_order": "2"},
        reason_code="invalid_phone",
        reason="Invalid phone",
        fingerprint="a" * 64,
        display_order=2,
        created_at=now + timedelta(seconds=1),
    )
    resolution_id = uuid.uuid4()
    client_group_id = uuid.uuid4()
    replacement_submission_id = uuid.uuid4()
    replaced_recipient = WhatsAppBroadcastRecipientModel(
        id=uuid.uuid4(),
        broadcast_group_id=group_id,
        agency_id=agency_id,
        name="Edited After Replacement",
        phone_number="+919111111111",
        normalized_phone_number="+919876543299",
        imported_fields={"source_order": "5", "staff_code": "EDITED"},
        display_order=5,
        removed_at=now + timedelta(seconds=4),
        suppressed_by_roster_resolution_id=resolution_id,
        created_at=now + timedelta(seconds=4),
    )
    resolution = PassportRosterResolutionModel(
        id=resolution_id,
        agency_id=agency_id,
        client_group_id=client_group_id,
        submission_id=replacement_submission_id,
        broadcast_recipient_id=replaced_recipient.id,
        replaced_recipient_normalized_phone="+919876543299",
        original_recipient_name="Original Traveller",
        original_recipient_phone="+919876543299",
        original_recipient_imported_fields={
            "source_order": "5",
            "staff_code": "OLD-5",
        },
        resolution_type="replacement",
        request_id=uuid.uuid4(),
        suppressed_recipient_ids=[str(replaced_recipient.id)],
        excluded_submission_ids=[],
        status="active",
        created_at=now + timedelta(seconds=5),
    )
    client_group = ClientGroupModel(
        id=client_group_id,
        agency_id=agency_id,
        name="Vietnam 2026",
        token="test-roster-replacement",
        status="active",
        created_at=now,
    )
    replacement_submission = PassportSubmissionModel(
        id=replacement_submission_id,
        group_id=client_group_id,
        agency_id=agency_id,
        client_name="Replacement Traveller",
        client_phone="+919876543288",
    )
    sent_state = WhatsAppRecipientMessageStateModel(
        id=uuid.uuid4(),
        broadcast_group_id=group_id,
        recipient_id=sent_recipient.id,
        agency_id=agency_id,
        message_type="welcome",
        status="sent",
        submitted_at=now,
        status_updated_at=now,
        created_at=now,
        updated_at=now,
    )
    failed_state = WhatsAppRecipientMessageStateModel(
        id=uuid.uuid4(),
        broadcast_group_id=group_id,
        recipient_id=failed_recipient.id,
        agency_id=agency_id,
        message_type="welcome",
        status="failed",
        submitted_at=now,
        status_updated_at=now,
        created_at=now,
        updated_at=now,
    )
    mixed_failure_state = WhatsAppRecipientMessageStateModel(
        id=uuid.uuid4(),
        broadcast_group_id=group_id,
        recipient_id=sent_recipient.id,
        agency_id=agency_id,
        message_type="passport_link",
        status="failed",
        submitted_at=now,
        status_updated_at=now,
        created_at=now,
        updated_at=now,
    )

    group_result = MagicMock()
    group_result.scalar_one_or_none.return_value = group
    recipients_result = MagicMock()
    recipients_result.scalars.return_value.all.return_value = [
        sent_recipient,
        failed_recipient,
        never_sent_recipient,
    ]
    rejected_result = MagicMock()
    rejected_result.scalars.return_value.all.return_value = [rejected]
    replaced_result = MagicMock()
    replaced_result.all.return_value = [
        (
            replaced_recipient,
            resolution,
            client_group,
            replacement_submission,
        )
    ]
    states_result = MagicMock()
    states_result.scalars.return_value.all.return_value = [
        sent_state,
        mixed_failure_state,
        failed_state,
    ]
    resend_result = MagicMock()
    resend_result.scalars.return_value.all.return_value = []
    linked_client_groups_result = MagicMock()
    linked_client_groups_result.scalars.return_value.all.return_value = []
    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=[
            group_result,
            recipients_result,
            rejected_result,
            replaced_result,
            states_result,
            resend_result,
            linked_client_groups_result,
        ]
    )

    response = await get_broadcast_recipient_roster(
        group_id=group_id,
        current_user=SimpleNamespace(
            role=UserRole.AGENCY_ADMIN,
            agency_id=agency_id,
        ),
        session=session,
    )

    assert [item.display_order for item in response.items] == [1, 2, 3, 4, 5]
    assert [item.kind for item in response.items] == [
        "recipient",
        "rejected",
        "recipient",
        "recipient",
        "replaced",
    ]
    assert response.items[0].recipient is not None
    assert {status.status for status in response.items[0].recipient.message_statuses} == {
        "sent",
        "failed",
    }
    assert response.items[1].rejected_contact is not None
    assert response.items[2].recipient is not None
    assert response.items[2].recipient.message_statuses[0].status == "failed"
    assert response.items[3].recipient is not None
    assert response.items[3].recipient.message_statuses == []
    assert response.items[4].replaced_recipient is not None
    assert response.items[4].replaced_recipient.model_dump() == {
        "recipient_id": replaced_recipient.id,
        "resolution_id": resolution.id,
        "client_group_id": client_group.id,
        "client_group_name": "Vietnam 2026",
        "name": "Original Traveller",
        "phone_number": "+919876543299",
        "normalized_phone_number": "+919876543299",
        "imported_fields": {"source_order": "5", "staff_code": "OLD-5"},
        "replacement_submission_id": replacement_submission.id,
        "replacement_name": "Replacement Traveller",
        "replacement_phone": "+919876543288",
        "replaced_at": resolution.created_at,
    }
    assert response.counts.model_dump() == {
        # All counts unique roster rows. It is deliberately not derived from
        # Sent + Failed because those filters overlap and never-sent rows exist.
        "all": 4,
        "sent": 1,
        "failed": 2,
        "rejected": 1,
        "replaced": 1,
        "unidentified": 0,
    }


@pytest.mark.asyncio
async def test_broadcast_unidentified_uploads_use_shared_group_matching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broadcast_group_id = uuid.uuid4()
    client_group_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    submission_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    client_group = ClientGroupModel(
        id=client_group_id,
        agency_id=agency_id,
        name="Vietnam 2026",
        token="unidentified-roster",
        status="active",
        created_at=now,
    )
    submission = PassportSubmissionModel(
        id=submission_id,
        group_id=client_group_id,
        agency_id=agency_id,
        client_name="Unexpected Traveller",
        client_phone="+919800000001",
        client_email="traveller@example.com",
        family_head_name="Family Head",
        confirmed_fields={"passport_number": "P1234567"},
        extracted_fields={"place_of_issue": "Chennai"},
        staff_metadata={"staff_code": "STF-9"},
        updated_at=now,
    )
    linked_group_result = MagicMock()
    linked_group_result.scalars.return_value.all.return_value = [client_group]
    session = MagicMock()
    session.execute = AsyncMock(return_value=linked_group_result)
    shared_loader = AsyncMock(
        return_value=(
            {broadcast_group_id: "Delegates"},
            [],
            [submission],
            [
                SimpleNamespace(
                    status="unmatched_submission",
                    submission_ids=(submission_id,),
                )
            ],
        )
    )
    set_route_dependency(
        monkeypatch,
        whatsapp_routes,
        "load_unresolved_passport_whatsapp_match_context",
        shared_loader,
    )

    uploads = await whatsapp_routes._unidentified_uploads_for_broadcast(
        session,
        broadcast_group_id=broadcast_group_id,
        agency_id=agency_id,
    )

    assert len(uploads) == 1
    assert uploads[0].model_dump() == {
        "submission_id": submission_id,
        "client_group_id": client_group_id,
        "client_group_name": "Vietnam 2026",
        "name": "Unexpected Traveller",
        "phone_number": "+919800000001",
        "email": "traveller@example.com",
        "details": {
            "family_head_name": "Family Head",
            "staff_code": "STF-9",
            "place_of_issue": "Chennai",
            "passport_number": "P1234567",
        },
        "updated_at": now,
    }
    shared_loader.assert_awaited_once_with(
        session,
        group_id=client_group_id,
        agency_id=agency_id,
        broadcast_group_ids=[broadcast_group_id],
    )


@pytest.mark.asyncio
async def test_broadcast_list_exposes_total_roster_without_changing_send_count() -> None:
    group_id = uuid.uuid4()
    agency_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    group = WhatsAppBroadcastGroupModel(
        id=group_id,
        agency_id=agency_id,
        name="Delegates",
        organizing_company_name="Global Connect Travels",
        recipient_opt_in_confirmed_at=now,
        created_at=now,
        updated_at=now,
    )
    result = MagicMock()
    result.all.return_value = [(group, 162, 3)]
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    response = await list_broadcast_groups(
        current_user=SimpleNamespace(
            role=UserRole.AGENCY_ADMIN,
            agency_id=agency_id,
        ),
        session=session,
    )

    assert len(response) == 1
    assert response[0].recipient_count == 162
    assert response[0].total_contact_count == 165


def test_existing_rows_keep_their_roster_order_when_reimported() -> None:
    normalized_phone = "+919876543210"
    existing_recipient = WhatsAppBroadcastRecipientModel(
        normalized_phone_number=normalized_phone,
        display_order=4,
    )
    existing_rejected = WhatsAppBroadcastRejectedContactModel(
        fingerprint="b" * 64,
        display_order=5,
    )
    rejected_contact = WhatsAppRejectedContactInput(
        source_file_name="delegates.xlsx",
        sheet_name="Delegates",
        row_number=3,
        raw_name="Rejected",
        raw_phone_number="919726092",
        imported_fields={},
        reason_code="invalid_phone",
    )
    existing_rejected.fingerprint = _rejected_contact_fingerprint(rejected_contact)
    recipient_orders, rejected_orders = _new_roster_display_orders(
        normalized_contacts={
            normalized_phone: WhatsAppRecipientInput(
                name="Existing",
                phone_number=normalized_phone,
            )
        },
        rejected_contacts=[rejected_contact],
        existing_by_phone={normalized_phone: existing_recipient},
        existing_by_fingerprint={
            existing_rejected.fingerprint: existing_rejected,
        },
        start_order=9,
    )

    assert recipient_orders == {}
    assert rejected_orders == {}
    assert existing_recipient.display_order == 4
    assert existing_rejected.display_order == 5
