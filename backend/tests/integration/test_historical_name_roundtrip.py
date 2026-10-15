"""Real workbook roundtrip plus canonical reindex with synthetic passenger data."""

from copy import deepcopy
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.application.travellers.historical_identity import (
    canonical_source_name,
    refresh_registered_identity,
)
from app.application.travellers.identity_index import (
    find_exact_identity,
    replace_identity_evidence,
    replace_phone_identity_evidence,
)
from app.domain.services.traveller_identity import identity_evidence
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentRevisionModel as Revision,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerIdentifierModel as Identifier,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerParticipationModel as Participation,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerProfileModel as Person,
)
from app.infrastructure.export.passport_excel_exporter import PassportExcelExporter
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.presentation.api.v1.routes.whatsapp_contact_import import _parse_excel_contact_bytes
from tests.unit.application.test_company_history_registration import register
from tests.unit.application.test_traveller_enrollment import _fixture


@pytest.mark.asyncio
@pytest.mark.parametrize("entered,given,surname", [
    ("Synthetic Family Family", "Synthetic", "Family"),
    ("Synthetic", "Synthetic Middle", "Family"),
    ("Synthetic Family", "Synthetic Middle", "Family"),
])
async def test_reviewed_passport_name_roundtrips_export_import_and_historical_index(db_session, entered, given, surname):
    ctx = await _fixture(db_session)
    ctx.source.client_name = entered
    ctx.source.confirmed_fields = {**ctx.source.confirmed_fields, "given_names": given, "surname": surname}
    ctx.source.client_email = "synthetic@example.test"
    # The export includes a phone only after the completed collection review.
    ctx.source.client_reviewed_at = datetime.now(UTC)
    await db_session.flush()
    before = deepcopy({column.key: getattr(ctx.source, column.key) for column in ctx.source.__table__.columns})
    person_id = await register(db_session, ctx)
    exported = PassportExcelExporter().export_group([PassportSubmissionRepository._to_entity(ctx.source)],
        group_name="Synthetic company trip")
    imported = _parse_excel_contact_bytes(exported, filename="synthetic-passengers.xlsx")
    assert len(imported.contacts) == 1 and not imported.rejected_rows
    contact = imported.contacts[0]
    match = await find_exact_identity(db_session, agency_id=ctx.group.agency_id, company_id=ctx.group.company_id,
        evidence=identity_evidence(contact.imported_fields, name=contact.name, phone=contact.phone_number), crypto=ctx.crypto)
    assert match.traveller_id == person_id and match.reason == "exact_three_type_match"
    person = await db_session.get(Person, person_id)
    assert ctx.crypto.decrypt(person.display_name_ciphertext) == f"{given} {surname}"
    assert before == {column.key: getattr(ctx.source, column.key) for column in ctx.source.__table__.columns}
    assert await db_session.scalar(select(func.count()).select_from(Person)) == 1


@pytest.mark.asyncio
async def test_existing_source_job_reindexes_same_person_once_without_document_or_trip_changes(db_session):
    ctx = await _fixture(db_session)
    ctx.source.client_name = "Synthetic Person Person"
    person_id = await register(db_session, ctx)
    person = await db_session.get(Person, person_id)
    await replace_identity_evidence(db_session, person=person, crypto=ctx.crypto, source={"legacy": True},
        evidence=identity_evidence(ctx.source.confirmed_fields, name=ctx.source.client_name, phone=ctx.source.client_phone))
    person.display_name_ciphertext = ctx.crypto.encrypt(ctx.source.client_name)
    await replace_phone_identity_evidence(db_session, person=person, normalized_phone="918888888888",
        crypto=ctx.crypto, source={"verified_change": True})
    await db_session.flush()
    stable_ids = set(await db_session.scalars(select(Identifier.id).where(Identifier.traveller_id==person_id,
        Identifier.identifier_type!="identity_v1:name")))
    member = await db_session.scalar(select(Participation).where(Participation.traveller_id==person_id))
    snapshot = (member.document_revision_id, member.profile_revision, deepcopy(member.confirmations))
    before_revision, before_authorization = person.revision, person.authorization_version
    assert await register(db_session, ctx) == person_id
    assert ctx.crypto.decrypt(person.display_name_ciphertext) == "Synthetic Person"
    assert (person.revision, person.authorization_version) == (before_revision+1, before_authorization+1)
    assert await register(db_session, ctx) == person_id
    assert (person.revision, person.authorization_version) == (before_revision+1, before_authorization+1)
    assert stable_ids == set(await db_session.scalars(select(Identifier.id).where(
        Identifier.traveller_id==person_id, Identifier.identifier_type!="identity_v1:name")))
    assert snapshot == (member.document_revision_id, member.profile_revision, member.confirmations)
    assert ctx.source.client_name == "Synthetic Person Person"
    assert await db_session.scalar(select(func.count()).select_from(Revision)) == 1
    assert await db_session.scalar(select(func.count()).select_from(Person)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["unapproved", "source_changed", "profile_review"])
async def test_canonical_refresh_does_not_bypass_current_source_or_profile_authority(db_session, change):
    ctx = await _fixture(db_session)
    if change == "unapproved":
        ctx.source.status = "client_submitted"
        assert canonical_source_name(ctx.source) is None
        return
    person_id = await register(db_session, ctx)
    person = await db_session.get(Person, person_id)
    if change == "source_changed":
        ctx.source.extraction_revision += 1
    else:
        person.status = "review_required"
    person.display_name_ciphertext = ctx.crypto.encrypt("Original private name")
    await db_session.flush()
    before = (person.revision, person.authorization_version)
    await refresh_registered_identity(db_session, person, ctx.crypto)
    assert ctx.crypto.decrypt(person.display_name_ciphertext) == "Original private name"
    assert (person.revision, person.authorization_version) == before
