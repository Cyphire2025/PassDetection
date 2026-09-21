"""Cross-list and direct welcome history produces truthful existing-list UI state."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.application.use_cases.whatsapp.welcome_policy import requires_prior_welcome
from app.infrastructure.database.models import (
    WhatsAppBroadcastRecipientModel,
    WhatsAppPhoneWelcomeModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.whatsapp.phone_welcome import (
    claim_phone_welcome,
    sync_phone_welcome,
    sync_welcome_from_log,
)
from app.infrastructure.whatsapp.private_delivery_policy import validate_private_delivery_welcome
from app.presentation.api.v1.routes.whatsapp_contact_support import _recipient_response
from app.presentation.api.v1.routes.whatsapp_phone_welcome import (
    enforce_broadcast_welcome_prerequisite,
)
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


@pytest.mark.parametrize("status", [None, "failed", "queued", "processing", "submitted", "sent", "delivery_unknown", "delivered", "read"])
async def test_invite_exemption_never_unlocks_other_message_types_or_mutates_welcome(db_session, status):
    agency = await _agency(db_session)
    if status is not None:
        db_session.add(WhatsAppPhoneWelcomeModel(
            agency_id=agency, normalized_phone_number=PHONE, status=status,
            attempt_id=uuid.uuid4(), attempt_kind="broadcast",
        ))
        await db_session.commit()
    recipient = WhatsAppBroadcastRecipientModel(
        id=uuid.uuid4(), agency_id=agency, broadcast_group_id=uuid.uuid4(),
        name="Traveller", phone_number=PHONE, normalized_phone_number=PHONE,
    )
    await enforce_broadcast_welcome_prerequisite(
        db_session, agency_id=agency, message_type="group_invite", recipients=[recipient],
    )
    preview = await welcome_preview_values(
        db_session, agency_id=agency, recipients=[recipient], message_type="group_invite",
    )
    assert preview == {"welcome_required_count": 0, "welcome_required_reason": None}
    assert welcome_resend_skip_reason("group_invite", status) is None
    for invite_status in ("queued", "submitted", "delivered", "read", "failed"):
        await sync_welcome_from_log(db_session, SimpleNamespace(
            message_type="group_invite", normalized_phone_number=PHONE, status=invite_status,
        ))
    current = await db_session.scalar(select(WhatsAppPhoneWelcomeModel))
    assert (current.status if current else None) == status
    welcomed = status in {"delivered", "read"}
    for message_type in ("passport_link", "reminder"):
        assert requires_prior_welcome(message_type)
        if welcomed:
            await enforce_broadcast_welcome_prerequisite(
                db_session, agency_id=agency, message_type=message_type, recipients=[recipient],
            )
        else:
            with pytest.raises(HTTPException) as exc:
                await enforce_broadcast_welcome_prerequisite(
                    db_session, agency_id=agency, message_type=message_type, recipients=[recipient],
                )
            assert exc.value.status_code == 409
        assert (welcome_resend_skip_reason(message_type, status) is None) == welcomed
    private = await validate_private_delivery_welcome(
        db_session, agency_id=agency, normalized_phone_number=PHONE,
    )
    assert private.allowed == welcomed
    states = [
        WhatsAppRecipientMessageStateModel(
            message_type=message_type, status="failed", status_updated_at=datetime.now(UTC),
        ) for message_type in ("group_invite", "passport_link", "reminder")
    ]
    if status is not None:
        states.append(WhatsAppRecipientMessageStateModel(
            message_type="welcome", status=status, status_updated_at=datetime.now(UTC),
        ))
    response = _recipient_response(recipient, states)
    by_type = {item.message_type: item for item in response.message_statuses}
    assert not by_type["group_invite"].resend_blocked
    assert by_type["passport_link"].resend_blocked == (not welcomed)
    assert by_type["reminder"].resend_blocked == (not welcomed)
    still_blocked = _recipient_response(recipient, states, {"group_invite": "delivery_unknown"})
    assert next(item for item in still_blocked.message_statuses if item.message_type == "group_invite").resend_blocked


def test_only_invites_and_welcome_itself_are_exempt_from_prior_welcome():
    assert not requires_prior_welcome("welcome")
    assert not requires_prior_welcome("group_invite")
    assert all(requires_prior_welcome(message_type) for message_type in (
        "passport_link", "reminder", "qr", "document", "unknown_future_message",
    ))
