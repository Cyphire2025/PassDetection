"""Verified current contact applies to future reuse, never old trips or broadcasts."""

import uuid
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.application.travellers.contact_change import finish_contact_change
from app.application.travellers.history import read_history
from app.application.travellers.matching import phone_candidates
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastSourceContactModel,
    WhatsAppMessageLogModel,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerGroupReuseConfigModel,
    TravellerParticipationModel,
)
from tests.integration.test_returning_claims import phone_claim, successful_claim
from tests.integration.test_returning_completion import complete, completion_context
from tests.integration.test_returning_contact_change import NEW_PHONE, pending_change
from tests.integration.traveller_reuse_fixtures import seed_person


@pytest.mark.asyncio
async def test_changed_phone_removes_only_selected_person_from_old_phone_lookup(db_session, test_settings):
    service, _, group, person, token, _ = await completion_context(db_session, test_settings)
    family = await seed_person(service, group, 2, phone=person.phone)
    pending, provider = await pending_change(service, token)
    changed = await finish_contact_change(service, token, pending, provider.code)
    assert (await read_history(service, changed))["contact_phone"] == NEW_PHONE

    secret, _ = await phone_claim(service, group, person)
    claim, scope = await service.locked(secret)
    candidates, narrowing = await phone_candidates(db_session, scope, claim, service.crypto, datetime.now(UTC))
    assert narrowing is False
    assert [item.handle for item in candidates] == [
        service.crypto.digest("candidate-handle", claim.secret_hash, str(family.profile.id))
    ]
    # Historical possession cannot use the established-contact shortcut. The
    # separately allowed recovery route still requires its document questions.
    claim, questions = await service.bind_passport(secret, passport_number=person.number, issuing_country="IND")
    assert len(questions) == claim.required_question_count == 2
    assert claim.status != "authorized"
    _, _, family_token = await successful_claim(service, group, family, "phone")
    assert (await read_history(service, family_token))["contact_phone"] == family.phone
    assert family.profile.contact_revision == 1
    _, new_claim, new_token = await successful_claim(service, group, replace(person, phone=NEW_PHONE), "phone")
    assert new_claim.required_question_count == 0
    assert (await read_history(service, new_token))["contact_phone"] == NEW_PHONE


async def _snapshot(session, model):
    return deepcopy((await session.execute(select(model.__table__).order_by(model.id))).mappings().all())


@pytest.mark.asyncio
async def test_future_reuse_copies_new_phone_without_rewriting_old_trip_or_linked_broadcast(db_session, test_settings):
    service, _, old_group, person, token, review = await completion_context(db_session, test_settings)
    old_participation_id, _ = await complete(service, token, review)
    old_participation = await db_session.get(TravellerParticipationModel, old_participation_id)
    old_source = await db_session.get(PassportSubmissionModel, old_participation.source_submission_id)
    assert old_source.client_phone == person.phone
    old_group.status = "closed"
    # Contact change is initiated from a different active future group.
    future = ClientGroupModel(agency_id=old_group.agency_id, company_id=old_group.company_id,
        company_revision=1, token=uuid.uuid4().hex, name="Future synthetic trip",
        travel_date=old_group.travel_date + timedelta(days=30),
        upload_configuration={"passport_upload_pages": ["front"], "visa_photo_required": False})
    broadcast = WhatsAppBroadcastGroupModel(agency_id=old_group.agency_id, name="Independent broadcast")
    db_session.add_all([future, broadcast])
    await db_session.flush()
    recipient = WhatsAppBroadcastRecipientModel(agency_id=old_group.agency_id, broadcast_group_id=broadcast.id,
        name="Shared original recipient", phone_number=person.phone, normalized_phone_number=person.phone,
        imported_fields={"phone_number": person.phone, "source": "original roster"})
    db_session.add_all([recipient, TravellerGroupReuseConfigModel(agency_id=future.agency_id,
        company_id=future.company_id, group_id=future.id, roster_mode="open", individual_identifier_type="employee")])
    await db_session.flush()
    db_session.add_all([
        ClientGroupWhatsAppBroadcastLinkModel(agency_id=old_group.agency_id, client_group_id=group.id,
            broadcast_group_id=broadcast.id, sync_contacts_from_group=True)
        for group in (old_group, future)
    ])
    db_session.add_all([
        WhatsAppBroadcastSourceContactModel(agency_id=old_group.agency_id, broadcast_group_id=broadcast.id,
            source_group_id=old_group.id, source_submission_id=old_source.id, recipient_id=recipient.id,
            name="Original source", raw_phone_number=person.phone, normalized_phone_number=person.phone),
        WhatsAppMessageLogModel(agency_id=old_group.agency_id, broadcast_group_id=broadcast.id,
            recipient_id=recipient.id, message_type="template", status="delivered",
            normalized_phone_number=person.phone, provider_message_id="synthetic-historical-receipt"),
    ])
    await db_session.commit()
    models = (WhatsAppBroadcastGroupModel, WhatsAppBroadcastRecipientModel,
              WhatsAppBroadcastSourceContactModel, WhatsAppMessageLogModel, ClientGroupWhatsAppBroadcastLinkModel)
    frozen_broadcast = {model: await _snapshot(db_session, model) for model in models}
    frozen_source = (await _snapshot(db_session, PassportSubmissionModel))[0]
    frozen_participation = (await _snapshot(db_session, TravellerParticipationModel))[0]

    _, _, future_token = await successful_claim(service, future, person, "code")
    pending, provider = await pending_change(service, future_token)
    updated_token = await finish_contact_change(service, future_token, pending, provider.code)
    current = await read_history(service, updated_token)
    assert current["contact_phone"] == NEW_PHONE
    participation_id, _ = await complete(service, updated_token, current)
    participation = await db_session.get(TravellerParticipationModel, participation_id)
    source = await db_session.get(PassportSubmissionModel, participation.source_submission_id)
    assert source.group_id == future.id and source.client_phone == NEW_PHONE
    assert participation.contact_revision == person.profile.contact_revision == 2
    assert provider.calls == 1  # Only the requested new-number OTP was sent.

    assert {model: await _snapshot(db_session, model) for model in models} == frozen_broadcast
    assert next(row for row in await _snapshot(db_session, PassportSubmissionModel)
                if row.id == old_source.id) == frozen_source
    assert next(row for row in await _snapshot(db_session, TravellerParticipationModel)
                if row.id == old_participation_id) == frozen_participation
