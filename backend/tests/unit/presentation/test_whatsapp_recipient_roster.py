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
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastRejectedContactModel,
    WhatsAppRecipientMessageStateModel,
)
from app.presentation.api.v1.routes.whatsapp import (
    WhatsAppRecipientInput,
    WhatsAppRejectedContactInput,
    _new_roster_display_orders,
    _normalized_recipient_inputs,
    _parse_excel_contact_bytes,
    _rejected_contact_fingerprint,
    get_broadcast_recipient_roster,
)


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

    group_result = MagicMock()
    group_result.scalar_one_or_none.return_value = group_id
    recipients_result = MagicMock()
    recipients_result.scalars.return_value.all.return_value = [
        sent_recipient,
        failed_recipient,
    ]
    rejected_result = MagicMock()
    rejected_result.scalars.return_value.all.return_value = [rejected]
    states_result = MagicMock()
    states_result.scalars.return_value.all.return_value = [sent_state, failed_state]
    resend_result = MagicMock()
    resend_result.scalars.return_value.all.return_value = []
    session = MagicMock()
    session.execute = AsyncMock(
        side_effect=[
            group_result,
            recipients_result,
            rejected_result,
            states_result,
            resend_result,
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

    assert [item.display_order for item in response.items] == [1, 2, 3]
    assert [item.kind for item in response.items] == [
        "recipient",
        "rejected",
        "recipient",
    ]
    assert response.items[0].recipient is not None
    assert response.items[0].recipient.message_statuses[0].status == "sent"
    assert response.items[1].rejected_contact is not None
    assert response.items[2].recipient is not None
    assert response.items[2].recipient.message_statuses[0].status == "failed"
    assert response.counts.model_dump() == {
        "all": 3,
        "sent": 1,
        "failed": 1,
        "rejected": 1,
    }


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
