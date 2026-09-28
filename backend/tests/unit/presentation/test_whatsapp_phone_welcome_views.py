"""Cross-list and direct welcome history produces truthful existing-list UI state."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.application.use_cases.whatsapp.welcome_policy import requires_prior_welcome
from app.domain.entities.entities import UserRole
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
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
from app.presentation.api.v1.routes.whatsapp_recipient_roster import get_broadcast_recipient_roster
from app.presentation.api.v1.routes.whatsapp_roster_support import _recipient_delivery_state_maps
from app.presentation.api.v1.routes.whatsapp_welcome_view import (
    phone_welcome_statuses_by_recipient,
    welcome_preview_values,
    welcome_resend_skip_reason,
)
from tests.unit.infrastructure.test_phone_welcome import PHONE, _agency, _attempt


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
async def test_other_list_welcome_does_not_affect_this_broadcast(
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
    phone_statuses = await phone_welcome_statuses_by_recipient(db_session, [recipient])
    response = _recipient_response(recipient, [], phone_welcome_statuses=phone_statuses)
    assert response.welcome_status is None
    assert not response.welcome_delivered
    assert response.message_statuses == []
    assert response.sent_message_types == []
    preview = await welcome_preview_values(
        db_session, agency_id=agency, recipients=[recipient], message_type="welcome"
    )
    assert preview["eligible_recipient_count"] == 1
    next_message = await welcome_preview_values(
        db_session, agency_id=agency, recipients=[recipient], message_type="passport_link"
    )
    assert next_message["welcome_required_count"] == 1
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
    phone_statuses = await phone_welcome_statuses_by_recipient(db_session, [recipient])
    response = _recipient_response(recipient, [], phone_welcome_statuses=phone_statuses)
    assert response.welcome_status is None
    assert not response.welcome_delivered
    preview = await welcome_preview_values(
        db_session, agency_id=other, recipients=[recipient], message_type="reminder"
    )
    assert preview["welcome_required_count"] == 1
    assert preview["eligible_recipient_count"] == 0


@pytest.mark.parametrize("current_status", [None, "failed", "read"])
async def test_roster_counts_only_current_broadcast_with_prior_welcome_elsewhere(
    db_session, current_status
):
    agency = await _agency(db_session)
    groups = [
        WhatsAppBroadcastGroupModel(id=uuid.uuid4(), agency_id=agency, name=name)
        for name in ("Earlier broadcast", "Current broadcast")
    ]
    db_session.add_all(groups)
    await db_session.flush()
    recipients = [
        WhatsAppBroadcastRecipientModel(
            id=uuid.uuid4(), agency_id=agency, broadcast_group_id=group.id,
            name="Traveller", phone_number=PHONE, normalized_phone_number=PHONE,
        )
        for group in groups
    ]
    db_session.add_all(recipients)
    await db_session.flush()
    for recipient, delivery_status in zip(recipients, ("read", current_status), strict=True):
        if delivery_status is not None:
            db_session.add(WhatsAppRecipientMessageStateModel(
                recipient_id=recipient.id, agency_id=agency,
                broadcast_group_id=recipient.broadcast_group_id,
                message_type="welcome", status=delivery_status,
            ))
    await claim_phone_welcome(
        db_session, agency_id=agency, phone=PHONE,
        attempt_id=(attempt := uuid.uuid4()), attempt_kind="broadcast",
    )
    await sync_phone_welcome(
        db_session, agency_id=agency, phone=PHONE, attempt_id=attempt, status="read",
    )
    await db_session.commit()

    roster = await get_broadcast_recipient_roster(
        groups[1].id,
        current_user=SimpleNamespace(role=UserRole.AGENCY_ADMIN, agency_id=agency),
        session=db_session,
    )
    assert roster.counts.all == 1
    assert roster.counts.sent == int(current_status == "read")
    assert roster.counts.failed == int(current_status == "failed")
    recipient_response = roster.items[0].recipient
    assert recipient_response is not None
    assert recipient_response.welcome_status == current_status
    assert recipient_response.welcome_delivered == (current_status == "read")
    assert recipient_response.sent_message_types == (["welcome"] if current_status == "read" else [])
    assert [state.status for state in recipient_response.message_statuses] == (
        [current_status] if current_status is not None else []
    )
    if current_status is not None:
        assert not recipient_response.message_statuses[0].resend_blocked
    # Viewing another list must neither erase history nor permit duplicate welcomes.
    assert await claim_phone_welcome(
        db_session, agency_id=agency, phone=PHONE,
        attempt_id=uuid.uuid4(), attempt_kind="broadcast",
    ) == "read"


@pytest.mark.parametrize("same_broadcast", [True, False])
async def test_actual_traveller_welcome_only_projects_into_its_own_broadcast(
    db_session, same_broadcast
):
    attempt, _ = await _attempt(db_session)
    attempt.status = "read"
    await sync_phone_welcome(
        db_session, agency_id=attempt.agency_id, phone=PHONE,
        attempt_id=attempt.id, status="read",
    )
    broadcast_id = attempt.broadcast_group_id if same_broadcast else uuid.uuid4()
    if not same_broadcast:
        db_session.add(WhatsAppBroadcastGroupModel(
            id=broadcast_id, agency_id=attempt.agency_id, name="Another broadcast",
        ))
        await db_session.flush()
    recipient = WhatsAppBroadcastRecipientModel(
        id=uuid.uuid4(), agency_id=attempt.agency_id, broadcast_group_id=broadcast_id,
        name="Traveller", phone_number=PHONE, normalized_phone_number=PHONE,
    )
    db_session.add(recipient)
    await db_session.flush()
    if same_broadcast:
        db_session.add(WhatsAppRecipientMessageStateModel(
            recipient_id=recipient.id, agency_id=attempt.agency_id,
            broadcast_group_id=broadcast_id, message_type="welcome", status="failed",
            status_updated_at=datetime.now(UTC) + timedelta(days=1),
        ))
    await db_session.commit()
    states, resends, global_statuses = await _recipient_delivery_state_maps(db_session, [recipient])
    response = _recipient_response(
        recipient, states.get(recipient.id, []), resends.get(recipient.id, {}),
        phone_welcome_statuses=global_statuses,
    )
    assert response.welcome_delivered == same_broadcast
    assert response.sent_message_types == (["welcome"] if same_broadcast else [])
    assert [state.status for state in response.message_statuses] == (["read"] if same_broadcast else [])


def test_changed_phone_prerequisite_does_not_reuse_old_recipient_delivery():
    recipient = WhatsAppBroadcastRecipientModel(
        id=uuid.uuid4(), agency_id=uuid.uuid4(), broadcast_group_id=uuid.uuid4(),
        name="Traveller", phone_number="+919876543299",
        normalized_phone_number="+919876543299",
    )
    response = _recipient_response(
        recipient,
        [WhatsAppRecipientMessageStateModel(
            message_type="welcome", status="read", status_updated_at=datetime.now(UTC),
        )],
        phone_welcome_statuses={recipient.id: None},
    )
    assert response.message_statuses[0].status == "read"
    assert response.welcome_status is None
    assert not response.welcome_delivered
    assert response.welcome_required_reason is not None


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
