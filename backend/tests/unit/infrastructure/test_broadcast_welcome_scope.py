"""One welcome per broadcast, independent of the same phone in other lists."""

import uuid

import pytest

from app.infrastructure.database.models import WhatsAppBroadcastGroupModel
from app.infrastructure.whatsapp.phone_welcome import (
    assert_phone_welcome_claim,
    claim_phone_welcome,
    welcome_states_for_phones,
)
from tests.unit.infrastructure.test_phone_welcome import PHONE, _attempt


@pytest.mark.parametrize("status", ["queued", "processing", "submitted", "sent", "read", "delivered", "delivery_unknown"])
async def test_welcome_blocks_only_its_own_broadcast(db_session, status):
    previous, _ = await _attempt(db_session)
    previous.status = status
    other = WhatsAppBroadcastGroupModel(id=uuid.uuid4(), agency_id=previous.agency_id, name="Another trip")
    db_session.add(other)
    await db_session.commit()
    for group_id, expected in [(previous.broadcast_group_id, status), (other.id, "claimed")]:
        result = await claim_phone_welcome(db_session, agency_id=previous.agency_id,
            phone=PHONE, attempt_id=uuid.uuid4(), attempt_kind="broadcast",
            broadcast_group_id=group_id, batch_id=uuid.uuid4())
        assert result == expected
    assert await welcome_states_for_phones(db_session, agency_id=previous.agency_id,
        phones=[PHONE], broadcast_group_id=other.id) == {}


async def test_worker_uses_own_broadcast_even_if_global_claim_belongs_elsewhere(db_session):
    from app.infrastructure.database.models import WhatsAppPhoneWelcomeAttemptModel

    previous, _ = await _attempt(db_session)
    previous.status = "read"
    other = WhatsAppBroadcastGroupModel(id=uuid.uuid4(), agency_id=previous.agency_id, name="New trip")
    db_session.add(other)
    await db_session.flush()
    attempt_id, batch_id = uuid.uuid4(), uuid.uuid4()
    assert await claim_phone_welcome(db_session, agency_id=previous.agency_id,
        phone=PHONE, attempt_id=attempt_id, attempt_kind="traveller",
        broadcast_group_id=other.id, batch_id=batch_id) == "claimed"
    current = WhatsAppPhoneWelcomeAttemptModel(id=attempt_id, batch_id=batch_id,
        agency_id=previous.agency_id, group_id=previous.group_id,
        broadcast_group_id=other.id, normalized_phone_number=PHONE,
        passenger_ids=previous.passenger_ids, recipient_name="Traveller",
        template_name="trip_welcome", rendered_message="Welcome to the next trip",
        header_parameter_values=[], template_parameter_values=[], status="processing")
    db_session.add(current)
    await db_session.flush()
    assert await assert_phone_welcome_claim(db_session, agency_id=previous.agency_id,
        phone=PHONE, attempt_id=current.id, broadcast_group_id=other.id)
    assert await claim_phone_welcome(db_session, agency_id=previous.agency_id,
        phone=PHONE, attempt_id=uuid.uuid4(), attempt_kind="broadcast",
        broadcast_group_id=other.id, batch_id=uuid.uuid4()) == "processing"


@pytest.mark.parametrize("active_status", ["queued", "processing", "delivery_unknown"])
async def test_explicit_resend_allows_accepted_history_but_blocks_another_attempt(db_session, active_status):
    from app.infrastructure.database.models import (
        WhatsAppBroadcastRecipientModel,
        WhatsAppMessageLogModel,
    )

    previous, _ = await _attempt(db_session)
    previous.status = "read"
    recipient = WhatsAppBroadcastRecipientModel(
        id=uuid.uuid4(), agency_id=previous.agency_id,
        broadcast_group_id=previous.broadcast_group_id, name="Selected person",
        phone_number=PHONE, normalized_phone_number=PHONE,
    )
    db_session.add(recipient)
    await db_session.flush()
    batch_id, attempt_id = uuid.uuid4(), uuid.uuid4()
    kwargs = dict(agency_id=previous.agency_id, phone=PHONE, attempt_id=attempt_id,
                  attempt_kind="broadcast", broadcast_group_id=previous.broadcast_group_id,
                  batch_id=batch_id)
    assert await claim_phone_welcome(db_session, **kwargs) == "read"
    assert await claim_phone_welcome(db_session, **kwargs, explicit_resend=True) == "claimed"
    resend = WhatsAppMessageLogModel(
        id=attempt_id, batch_id=batch_id, recipient_id=recipient.id,
        agency_id=previous.agency_id, broadcast_group_id=previous.broadcast_group_id,
        normalized_phone_number=PHONE, message_type="welcome", status="queued",
        is_explicit_resend=True,
    )
    db_session.add(resend)
    await db_session.flush()
    assert await assert_phone_welcome_claim(db_session, agency_id=previous.agency_id,
        phone=PHONE, attempt_id=attempt_id, broadcast_group_id=previous.broadcast_group_id)
    resend.status = active_status
    await db_session.flush()
    assert await claim_phone_welcome(db_session, agency_id=previous.agency_id,
        phone=PHONE, attempt_id=uuid.uuid4(), attempt_kind="broadcast",
        broadcast_group_id=previous.broadcast_group_id, batch_id=uuid.uuid4(),
        explicit_resend=True) == active_status
