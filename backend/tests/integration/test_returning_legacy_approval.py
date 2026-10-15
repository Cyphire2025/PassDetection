"""Current legacy approval can be reused; issuer uncertainty never grants access."""

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.application.travellers.document_challenge import (
    change_document_question,
    verify_document_answers,
)
from app.application.travellers.errors import ReuseError, ReuseReason
from app.application.travellers.grants import confirm_claim
from app.application.travellers.history import read_history
from app.application.travellers.identity_index import replace_identity_evidence
from app.application.travellers.passport_lookup import LEGACY_LOOKUP_KEY
from app.domain.services.traveller_identity import identity_evidence
from app.domain.services.traveller_verification import DocumentQuestion, VerificationFailure
from app.infrastructure.database.models import UserModel
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentAssetModel,
    TravellerDocumentRevisionModel,
)
from app.presentation.api.v1.schemas.returning_history_schemas import ReturningHistoryResponse
from tests.integration.traveller_reuse_fixtures import reuse_context, seed_person
from tests.unit.application.test_company_history_registration import register
from tests.unit.application.test_traveller_enrollment import _source
from tests.unit.application.test_traveller_legacy_approval import approve_legacy


async def enrolled_legacy(session, settings):
    service, _, group = await reuse_context(session, settings)
    user = UserModel(agency_id=group.agency_id, email=f"{uuid.uuid4()}@example.invalid",
        full_name="Synthetic reviewer", hashed_password="unused", role="agency_admin")
    source = _source(group)
    approve_legacy(source)
    source.staff_metadata = {"employee": "LEGACY01"}
    session.add_all([user, source])
    await session.flush()
    ctx = SimpleNamespace(group=group, source=source, crypto=service.crypto, request=SimpleNamespace(actor_id=user.id))
    await register(session, ctx)
    revision = await session.scalar(select(TravellerDocumentRevisionModel))
    # Simulate completed independent storage copies; no external I/O in this test.
    for asset in await session.scalars(select(TravellerDocumentAssetModel)):
        asset.availability, asset.byte_size = "available", 100
    await session.commit()
    return service, group, source, revision


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["P", "PASSPORT"])
async def test_enrolled_legacy_requires_passport_proof_then_exposes_allowlisted_history(db_session, test_settings, kind):
    service, group, source, revision = await enrolled_legacy(db_session, test_settings)
    secret, claim = await service.start(group_token=group.token, method="passport",
        passport_number=source.confirmed_fields["passport_number"], issuing_country="IND", document_type=kind)
    claim, questions = await service.bind_passport(secret)
    assert questions == (DocumentQuestion.DATE_OF_BIRTH,)
    with pytest.raises((ReuseError, VerificationFailure)):
        await confirm_claim(service, secret, acting_for="self", contact_change_confirmed=False)
    selected = await change_document_question(db_session, claim, revision, DocumentQuestion.ISSUE_DATE, datetime.now(UTC))
    assert selected == (DocumentQuestion.ISSUE_DATE,)
    await verify_document_answers(db_session, claim, revision, {"issue_date": "2020-01-01"}, datetime.now(UTC))
    await db_session.commit()
    token = await confirm_claim(service, secret, acting_for="self", contact_change_confirmed=False)
    result = ReturningHistoryResponse.model_validate(await read_history(service, token)).model_dump(mode="json")
    assert result["passport"]["number"] == source.confirmed_fields["passport_number"]
    assert result["passport"]["issuing_country"] == "UNK"
    assert LEGACY_LOOKUP_KEY not in claim.actor_evidence
    for private in ("source_input_digest", "source_verification_revision", "observed_value", "source_object_key"):
        assert private not in json.dumps(result)


@pytest.mark.asyncio
async def test_unknown_context_does_not_relax_wrong_answer_or_identifier_proof(db_session, test_settings):
    service, group, source, revision = await enrolled_legacy(db_session, test_settings)
    number = source.confirmed_fields["passport_number"]
    secret, _ = await service.start(group_token=group.token, method="passport", passport_number=number, issuing_country="IND")
    claim, _ = await service.bind_passport(secret)
    with pytest.raises(ReuseError) as wrong_date:
        await verify_document_answers(db_session, claim, revision, {"date_of_birth": "2000-01-01"}, datetime.now(UTC))
    assert wrong_date.value.reason == ReuseReason.VERIFICATION_FAILED
    with pytest.raises((ReuseError, VerificationFailure)):
        await confirm_claim(service, secret, acting_for="self", contact_change_confirmed=False)
    secret, _ = await service.start(group_token=group.token, method="code", individual_code="WRONG")
    with pytest.raises(ReuseError):
        await service.bind_passport(secret, passport_number=number, issuing_country="IND")
    secret, _ = await service.start(group_token=group.token, method="code", individual_code="LEGACY01")
    _, questions = await service.bind_passport(secret, passport_number=number, issuing_country="IND")
    assert questions == ()


@pytest.mark.asyncio
async def test_known_and_unknown_context_collision_fails_before_binding(db_session, test_settings):
    service, group, source, _ = await enrolled_legacy(db_session, test_settings)
    other = await seed_person(service, group, 2)
    number = source.confirmed_fields["passport_number"]
    other.passport.number_fingerprint = service.crypto.passport_fingerprint(group.agency_id, group.company_id, number, "IND", "P")
    await db_session.commit()
    secret, claim = await service.start(group_token=group.token, method="passport", passport_number=number, issuing_country="IND")
    with pytest.raises(ReuseError) as failure:
        await service.bind_passport(secret)
    assert failure.value.reason == ReuseReason.VERIFICATION_FAILED
    assert claim.traveller_id is None and claim.passport_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("eligible", [True, False])
async def test_unknown_issuer_rejects_other_eligible_owner_even_for_unsubmitted_country(db_session, test_settings, eligible):
    service, group, source, _ = await enrolled_legacy(db_session, test_settings)
    other = await seed_person(service, group, 2)
    number = source.confirmed_fields["passport_number"]
    other.passport.issuing_country = "GBR"
    other.passport.number_fingerprint = service.crypto.passport_fingerprint(group.agency_id, group.company_id, number, "GBR", "P")
    other.document.date_of_birth = datetime(1990, 1, 1).date()
    await replace_identity_evidence(db_session, person=other.profile,
        evidence=identity_evidence({"passport_number": number}, name="Another Person"),
        crypto=service.crypto, source={"kind": "synthetic-review"})
    if not eligible:
        other.profile.deleted_at = datetime.now(UTC)
    await db_session.commit()
    secret, claim = await service.start(group_token=group.token, method="passport", passport_number=number, issuing_country="IND")
    if eligible:
        with pytest.raises(ReuseError) as failure:
            await service.bind_passport(secret)
        assert failure.value.reason == ReuseReason.VERIFICATION_FAILED
        assert claim.traveller_id is None and claim.passport_id is None
    else:
        _, questions = await service.bind_passport(secret)
        assert questions == (DocumentQuestion.DATE_OF_BIRTH,)


@pytest.mark.asyncio
async def test_legacy_lookup_stays_company_scoped_and_requires_valid_document_type(db_session, test_settings):
    service, _, source, _ = await enrolled_legacy(db_session, test_settings)
    _, _, other_group = await reuse_context(db_session, test_settings)
    secret, claim = await service.start(group_token=other_group.token, method="passport",
        passport_number=source.confirmed_fields["passport_number"], issuing_country="IND")
    with pytest.raises(ReuseError):
        await service.bind_passport(secret)
    assert claim.traveller_id is None
    # Other document kinds cannot claim the canonical legacy passport fallback.
    secret, claim = await service.start(group_token=other_group.token, method="passport",
        passport_number=source.confirmed_fields["passport_number"], issuing_country="IND", document_type="V")
    assert LEGACY_LOOKUP_KEY not in claim.actor_evidence
