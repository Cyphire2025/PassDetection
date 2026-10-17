import json
import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from app.application.travellers.document_lifecycle import block_passport
from app.application.travellers.errors import ReuseError
from app.application.travellers.history import read_history
from app.application.travellers.passport_selection import select_passport
from app.infrastructure.database.models import UserModel
from app.infrastructure.database.traveller_reuse_models import (
    TravellerChangeEventModel,
    TravellerDocumentAssetModel,
    TravellerDocumentRevisionModel,
    TravellerPassportModel,
)
from tests.integration.test_returning_completion import complete, completion_context
from tests.integration.traveller_reuse_fixtures import seed_person


@pytest.mark.asyncio
async def test_multiple_passports_stay_person_scoped_and_selection_requires_new_confirmation(db_session, test_settings):
    service, _, group, person, token, review = await completion_context(db_session, test_settings)
    alternate = TravellerPassportModel(id=uuid.uuid4(), agency_id=group.agency_id, company_id=group.company_id,
        traveller_id=person.profile.id, issuing_country="GBR", document_type="P", status="accepted", is_default=False,
        number_fingerprint=service.crypto.passport_fingerprint(group.agency_id, group.company_id, "ALT0001", "GBR", "P"),
        fingerprint_key_version=service.crypto.key_version, number_ciphertext=service.crypto.encrypt("ALT0001"))
    db_session.add(alternate)
    await db_session.flush()
    revision = TravellerDocumentRevisionModel(id=uuid.uuid4(), agency_id=group.agency_id, company_id=group.company_id,
        traveller_id=person.profile.id, passport_id=alternate.id, status="accepted", revision_number=1,
        fields_ciphertext=service.crypto.encrypt(json.dumps({"nationality": "GBR", "passport_number": "ALT0001"})),
        date_of_birth=date(1990, 2, 3), issue_date=date(2025, 1, 1), expiry_date=date(2036, 1, 1),
        idempotency_key=uuid.uuid4().hex, accepted_at=datetime.now(UTC))
    db_session.add(revision)
    await db_session.flush()
    db_session.add(TravellerDocumentAssetModel(id=uuid.uuid4(), agency_id=group.agency_id, company_id=group.company_id,
        traveller_id=person.profile.id, passport_id=alternate.id, document_revision_id=revision.id,
        kind="original", document_side="front", object_key="synthetic/alternate.png", content_type="image/png",
        byte_size=10, availability="available", retention_basis="synthetic"))
    other = await seed_person(service, group, 2)
    await db_session.commit()
    with pytest.raises(ReuseError):
        await select_passport(service, token, other.passport.id)
    await select_passport(service, token, alternate.id)
    changed = await read_history(service, token)
    assert changed["passport"]["number"] == "ALT0001"
    assert len(changed["available_passports"]) == 2
    assert changed["review_version"] != review["review_version"]
    assert person.passport.is_default and not alternate.is_default
    with pytest.raises(ReuseError):
        await complete(service, token, review)
    assert (await complete(service, token, changed))[1] == "submitted"


@pytest.mark.asyncio
async def test_lost_declaration_immediately_revokes_history_and_creates_impact_event(db_session, test_settings):
    service, _, group, person, token, _ = await completion_context(db_session, test_settings)
    actor = UserModel(id=uuid.uuid4(), agency_id=group.agency_id, email=f"{uuid.uuid4()}@example.invalid",
        full_name="Synthetic admin", hashed_password="hash", role="agency_admin")
    db_session.add(actor)
    await db_session.flush()
    await block_passport(db_session, profile=person.profile, passport_id=person.passport.id,
        expected_profile_revision=person.profile.revision, expected_passport_revision=person.passport.revision,
        status="lost", actor_id=actor.id)
    await db_session.commit()
    with pytest.raises(ReuseError):
        await read_history(service, token)
    assert person.passport.status == "lost" and not person.passport.is_default
    event = await db_session.scalar(select(TravellerChangeEventModel).where(TravellerChangeEventModel.event_type == "document_blocked"))
    assert event.aggregate_id == person.passport.id and event.traveller_id == person.profile.id
