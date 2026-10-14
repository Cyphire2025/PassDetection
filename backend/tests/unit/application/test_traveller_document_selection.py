"""Archived metadata cannot shadow a real scan or bypass a newer real revision."""

import json
import uuid
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import aliased

from app.application.travellers.accepted_source import accept_source
from app.application.travellers.authority import accepted_document
from app.application.travellers.document_selection import (
    MAX_CURRENT_DOCUMENT_CANDIDATES,
    current_document_id,
)
from app.application.travellers.enrollment import enroll_submission
from app.application.travellers.errors import ReuseError
from app.application.travellers.source_acceptance_provenance import acceptance_provenance
from app.application.travellers.versioning import EnrollmentError
from app.domain.services.traveller_suitability import (
    SuitabilityOutcome,
    TravelDocument,
    assess_document,
)
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentAssetModel as Asset,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentRevisionModel as Document,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerParticipationModel as Participation,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerPassportModel as Passport,
)
from app.infrastructure.database.traveller_reuse_models import TravellerProfileModel as Person
from tests.unit.application.test_company_history_registration import register
from tests.unit.application.test_traveller_enrollment import _fixture, _source
from tests.unit.application.test_traveller_legacy_staff_approval import approve_staff_legacy


async def ready_document(session):
    ctx = await _fixture(session)
    approve_staff_legacy(ctx.source, ctx.request.actor_id)
    await session.flush()
    person = await register(session, ctx)
    document = await session.scalar(select(Document).where(Document.traveller_id == person))
    passport = await session.get(Passport, document.passport_id)
    for asset in await session.scalars(select(Asset).where(Asset.document_revision_id == document.id)):
        asset.availability, asset.byte_size, asset.content_type = "available", 100, "image/jpeg"
        asset.source_object_key = None
    await session.flush()
    return ctx, passport, document


async def historical_placeholder(session, ctx, passport, *, number=2, availability="unreadable"):
    """Reproduce an already-stored pre-fix revision; new enrollment rejects it."""
    group = ClientGroupModel(agency_id=ctx.group.agency_id, company_id=ctx.group.company_id,
        token=uuid.uuid4().hex, name="Archived synthetic import", status="archived", company_revision=1)
    session.add(group)
    await session.flush()
    source = _source(group)
    approve_staff_legacy(source, ctx.request.actor_id)
    source.created_at = datetime.now(UTC) - timedelta(days=365)
    source.image_s3_key, source.passport_back_s3_key = f"excel-imports/{uuid.uuid4()}", None
    session.add(source)
    await session.flush()
    accepted = accept_source(source, dict(source.confirmed_fields), operator=True)
    revision = Document(agency_id=passport.agency_id, company_id=passport.company_id,
        traveller_id=passport.traveller_id, passport_id=passport.id, revision_number=number,
        status="accepted", fields_ciphertext=ctx.crypto.encrypt(json.dumps(accepted.fields)),
        source_submission_id=source.id, source_group_id=group.id,
        source_provenance={"extraction_revision": source.extraction_revision, "authority_kind": "operator_registration",
            **acceptance_provenance(accepted, source, ctx.crypto)},
        date_of_birth=date(1990, 1, 1), issue_date=date(2020, 1, 1), expiry_date=date(2030, 1, 1),
        accepted_at=datetime.now(UTC), idempotency_key=uuid.uuid4().hex)
    session.add(revision)
    await session.flush()
    session.add(Asset(agency_id=passport.agency_id, company_id=passport.company_id,
        traveller_id=passport.traveller_id, passport_id=passport.id, document_revision_id=revision.id,
        kind="original", document_side="front", source_object_key=source.image_s3_key,
        source_extraction_revision=source.extraction_revision, object_key=f"retained/{uuid.uuid4()}",
        content_type="application/octet-stream", byte_size=0, availability=availability,
        retention_basis="operator_history", copy_attempt_count=5 if availability == "unreadable" else 0))
    await session.flush()
    return source, revision


async def selected(session, ctx, passport):
    return (await accepted_document(session, agency_id=passport.agency_id, company_id=passport.company_id,
        traveller_id=passport.traveller_id, passport_id=passport.id, crypto=ctx.crypto))[1]


@pytest.mark.asyncio
@pytest.mark.parametrize("availability", ["pending", "unreadable"])
async def test_later_archived_placeholder_cannot_displace_current_real_document(db_session, availability):
    ctx, passport, real = await ready_document(db_session)
    trip = await db_session.scalar(select(Participation).where(Participation.traveller_id == passport.traveller_id))
    snapshot = trip.document_revision_id
    source, placeholder = await historical_placeholder(db_session, ctx, passport, availability=availability)
    frozen = deepcopy(placeholder.source_provenance)
    assert await selected(db_session, ctx, passport) is real
    assert await selected(db_session, ctx, passport) is real
    assert trip.document_revision_id == snapshot and placeholder.source_provenance == frozen
    assert placeholder.status == "accepted" and source.image_s3_key.startswith("excel-imports/")
    alias = aliased(Passport)
    assert await db_session.scalar(select(current_document_id(alias)).where(alias.id == passport.id)) == real.id


@pytest.mark.asyncio
async def test_reverse_registration_order_and_metadata_only_admission_are_safe(db_session):
    ctx, passport, real = await ready_document(db_session)
    real.revision_number = 2
    await db_session.flush()
    source, placeholder = await historical_placeholder(db_session, ctx, passport, number=1)
    assert await selected(db_session, ctx, passport) is real
    with pytest.raises(EnrollmentError, match="source_scan_unavailable"):
        await enroll_submission(db_session, replace(ctx.request, group_id=source.group_id, submission_id=source.id,
            idempotency_key="blocked-metadata-only", authority_kind="operator_registration"), ctx.crypto)
    assert await db_session.scalar(select(func.count()).select_from(Document)) == 2
    assert passport.is_default and placeholder.status == "accepted"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["reviewer", "review_time", "verification_revision", "fields", "image", "selected_source", "status"])
async def test_skipped_metadata_and_selected_source_must_keep_frozen_proof(db_session, change):
    ctx, passport, real = await ready_document(db_session)
    source, _ = await historical_placeholder(db_session, ctx, passport)
    if change == "reviewer":
        source.verification_reviewed_by_user_id = None
    elif change == "review_time":
        source.verification_reviewed_at = source.confirmed_at = source.confirmed_at + timedelta(seconds=1)
    elif change == "verification_revision":
        source.post_submission_verification_revision += 1
    elif change == "fields":
        source.confirmed_fields = {**source.confirmed_fields, "nationality": "GBR"}
    elif change == "image":
        source.image_s3_key = "excel-imports/changed-placeholder"
    elif change == "selected_source":
        ctx.source.confirmed_fields = {**ctx.source.confirmed_fields, "date_of_birth": "1991-01-01"}
    else:
        ctx.source.status = "needs_review"
    await db_session.flush()
    with pytest.raises(ReuseError):
        await selected(db_session, ctx, passport)


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["pending", "unreadable", "missing", "expired", "corrected"])
async def test_newer_real_revision_never_falls_back_to_old_usable_details(db_session, state):
    ctx, passport, real = await ready_document(db_session)
    source = _source(ctx.group)
    approve_staff_legacy(source, ctx.request.actor_id)
    if state == "expired":
        source.confirmed_fields = {**source.confirmed_fields, "date_of_expiry": "2025-01-01"}
    if state == "corrected":
        source.confirmed_fields = {**source.confirmed_fields, "given_names": "Corrected"}
    db_session.add(source)
    await db_session.flush()
    person = await db_session.get(Person, passport.traveller_id)
    result = await enroll_submission(db_session, replace(ctx.request, submission_id=source.id,
        idempotency_key=f"real-{state}", traveller_id=passport.traveller_id,
        expected_profile_revision=person.revision, authority_kind="operator_registration"), ctx.crypto)
    latest = await db_session.get(Document, result.document_revision_id)
    assets = list(await db_session.scalars(select(Asset).where(Asset.document_revision_id == latest.id)))
    for asset in assets:
        if state == "missing":
            await db_session.delete(asset)
        elif state == "unreadable":
            asset.availability = "unreadable"
    await db_session.flush()
    assert await selected(db_session, ctx, passport) is latest and latest.id != real.id
    if state == "expired":
        outcome = assess_document(TravelDocument("UNK", "IND", "P", latest.issue_date, latest.expiry_date,
            True, True, "accepted"), travel_date=date(2026, 10, 20), today=date(2026, 10, 14), destinations=(), rules=())
        assert outcome.outcome == SuitabilityOutcome.REPLACEMENT_REQUIRED


@pytest.mark.asyncio
async def test_bounded_window_fails_closed_and_scope_cannot_select_another_person(db_session):
    ctx, passport, _ = await ready_document(db_session)
    for number in range(2, MAX_CURRENT_DOCUMENT_CANDIDATES + 2):
        await historical_placeholder(db_session, ctx, passport, number=number)
    with pytest.raises(ReuseError):
        await selected(db_session, ctx, passport)
    for changes in ({"agency_id": uuid.uuid4()}, {"company_id": uuid.uuid4()}, {"traveller_id": uuid.uuid4()}):
        with pytest.raises(ReuseError):
            await accepted_document(db_session, **{"agency_id": passport.agency_id, "company_id": passport.company_id,
                "traveller_id": passport.traveller_id, "passport_id": passport.id, "crypto": ctx.crypto, **changes})


@pytest.mark.asyncio
async def test_current_proof_read_refreshes_previously_loaded_source(db_session):
    ctx, passport, _ = await ready_document(db_session)
    source, _ = await historical_placeholder(db_session, ctx, passport)
    revision = source.post_submission_verification_revision
    await db_session.execute(update(PassportSubmissionModel).where(PassportSubmissionModel.id == source.id)
        .values(post_submission_verification_revision=revision + 1).execution_options(synchronize_session=False))
    assert source.post_submission_verification_revision == revision
    with pytest.raises(ReuseError):
        await selected(db_session, ctx, passport)
    assert source.post_submission_verification_revision == revision + 1


@pytest.mark.asyncio
async def test_new_default_real_passport_does_not_fall_back_to_previous_passport(db_session):
    ctx, previous, old = await ready_document(db_session)
    await historical_placeholder(db_session, ctx, previous)
    source = _source(ctx.group, number="009999999", issue="2024-01-01", expiry="2025-01-01")
    approve_staff_legacy(source, ctx.request.actor_id)
    db_session.add(source)
    await db_session.flush()
    person = await db_session.get(Person, previous.traveller_id)
    result = await enroll_submission(db_session, replace(ctx.request, submission_id=source.id,
        idempotency_key="new-default-expired", traveller_id=person.id, expected_profile_revision=person.revision,
        authority_kind="operator_registration", change_kind="renewal"), ctx.crypto)
    current = await db_session.get(Passport, result.passport_id)
    assert current.is_default and not previous.is_default
    chosen = await selected(db_session, ctx, current)
    assert chosen.id == result.document_revision_id and chosen.id != old.id
    assert chosen.expiry_date == date(2025, 1, 1)
    current.status, current.is_default = "cancelled", False
    await db_session.flush()
    with pytest.raises(ReuseError):
        await selected(db_session, ctx, current)
