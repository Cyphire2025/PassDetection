"""Cross-list and direct welcome history produces truthful existing-list UI state."""

from __future__ import annotations

import uuid

import pytest

from app.infrastructure.database.models import WhatsAppBroadcastRecipientModel
from app.infrastructure.whatsapp.phone_welcome import claim_phone_welcome, sync_phone_welcome
from app.presentation.api.v1.routes.whatsapp_contact_support import _recipient_response
from app.presentation.api.v1.routes.whatsapp_welcome_view import (
    overlay_phone_welcome_states,
    welcome_preview_values,
    welcome_resend_skip_reason,
)
from tests.unit.infrastructure.test_phone_welcome import PHONE, _agency


@pytest.mark.parametrize(
    "status",
    [
        "queued",
        "processing",
        "submitted",
        "sent",
        "delivered",
        "read",
        "delivery_unknown",
        "failed",
    ],
)
async def test_existing_roster_and_preview_project_welcome_from_another_list_or_traveller(
    db_session, status
):
    agency = await _agency(db_session)
    attempt = uuid.uuid4()
    await claim_phone_welcome(
        db_session, agency_id=agency, phone=PHONE, attempt_id=attempt, attempt_kind="traveller"
    )
    await sync_phone_welcome(
        db_session, agency_id=agency, phone=PHONE, attempt_id=attempt, status=status
    )
    await db_session.commit()
    recipient = WhatsAppBroadcastRecipientModel(
        id=uuid.uuid4(),
        agency_id=agency,
        broadcast_group_id=uuid.uuid4(),
        name="Traveller",
        phone_number=PHONE,
        normalized_phone_number=PHONE,
    )
    states = {}
    await overlay_phone_welcome_states(db_session, [recipient], states)
    response = _recipient_response(recipient, states[recipient.id])
    assert response.welcome_status == status
    assert response.welcome_delivered == (status in {"delivered", "read"})
    assert response.message_statuses[0].resend_blocked == (status != "failed")
    preview = await welcome_preview_values(
        db_session, agency_id=agency, recipients=[recipient], message_type="welcome"
    )
    assert preview["eligible_recipient_count"] == int(status == "failed")
    next_message = await welcome_preview_values(
        db_session, agency_id=agency, recipients=[recipient], message_type="passport_link"
    )
    assert next_message["welcome_required_count"] == int(status not in {"delivered", "read"})
    assert (
        welcome_resend_skip_reason("welcome", status) is None
        if status == "failed"
        else welcome_resend_skip_reason("welcome", status) is not None
    )


async def test_same_phone_in_other_tenant_does_not_project_welcome(db_session):
    agency = await _agency(db_session)
    other = await _agency(db_session)
    attempt = uuid.uuid4()
    await claim_phone_welcome(
        db_session, agency_id=agency, phone=PHONE, attempt_id=attempt, attempt_kind="traveller"
    )
    await sync_phone_welcome(
        db_session, agency_id=agency, phone=PHONE, attempt_id=attempt, status="delivered"
    )
    recipient = WhatsAppBroadcastRecipientModel(
        id=uuid.uuid4(),
        agency_id=other,
        broadcast_group_id=uuid.uuid4(),
        name="Other tenant",
        phone_number=PHONE,
        normalized_phone_number=PHONE,
    )
    states = {}
    await overlay_phone_welcome_states(db_session, [recipient], states)
    response = _recipient_response(recipient, states[recipient.id])
    assert response.welcome_status is None
    assert not response.welcome_delivered
    preview = await welcome_preview_values(
        db_session, agency_id=other, recipients=[recipient], message_type="reminder"
    )
    assert preview["welcome_required_count"] == 1
    assert preview["eligible_recipient_count"] == 0
