"""A current staff decision accepts legacy context and binds its immutable proof."""

import uuid
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.application.travellers.accepted_source import accept_source, retained_source_is_current
from app.application.travellers.historical_document_generation import (
    historical_enrollment_key,
    registration_is_current,
)
from app.application.travellers.legacy_staff_acceptance import STAFF_ACCEPTANCE_RULE
from app.application.travellers.versioning import EnrollmentError
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentRevisionModel as Document,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerParticipationModel as Participation,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerPassportModel as Passport,
)
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from tests.unit.application.test_company_history_registration import register
from tests.unit.application.test_traveller_enrollment import _fixture


def approve_staff_legacy(source, reviewer_id):
    fields = {**source.confirmed_fields, "nationality": "IND"}
    fields.pop("issuing_country", None)
    fields.pop("document_type", None)
    source.confirmed_fields, source.mrz_raw = fields, None
    reviewed = datetime.now(UTC)
    source.status = "staff_approved"
    source.verification_reviewed_by_user_id = reviewer_id
    source.verification_reviewed_at = source.confirmed_at = reviewed
    source.client_reviewed_at = reviewed - timedelta(seconds=2)
    source.post_submission_verified_at = reviewed - timedelta(seconds=1)
    source.post_submission_verification_revision = 2
    source.post_submission_verification = {"verification_status": "needs_review", "provider_status": "verified",
        "incorrect_fields": ["given_names"], "suspicious_fields": [], "fields": []}
    return fields


@pytest.mark.asyncio
async def test_staff_override_accepts_unknown_context_without_relabeling_ai_or_editing_source(db_session):
    ctx = await _fixture(db_session)
    fields = approve_staff_legacy(ctx.source, ctx.request.actor_id)
    ai = deepcopy(ctx.source.post_submission_verification)
    await db_session.flush()
    person_id = await register(db_session, ctx)
    revision = await db_session.scalar(select(Document))
    passport = await db_session.scalar(select(Passport))
    assert revision.traveller_id == person_id and passport.issuing_country == "UNK"
    assert passport.document_type == "P" and ctx.source.confirmed_fields == fields
    assert ctx.source.post_submission_verification == ai
    assert revision.source_provenance["acceptance_rule"] == STAFF_ACCEPTANCE_RULE
    assert revision.source_provenance["issuing_context_source"] == "not_recorded"
    assert revision.source_provenance["source_extraction_revision"] == 1
    assert revision.source_provenance["source_verification_revision"] == 2
    assert revision.source_provenance["source_reviewed_by_user_id"] == str(ctx.request.actor_id)
    assert len(revision.source_provenance["source_input_digest"]) == 64
    assert set(revision.reliable_fields) == {"date_of_birth", "issue_date", "expiry_date"}
    assert retained_source_is_current(revision, ctx.source, ctx.crypto)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["reviewer", "review_time", "confirmation", "unequal_confirmation",
    "extraction_revision", "verification_revision", "bool_revision", "needs_review", "bare_confirmed",
    "newer_client_review", "newer_ai"])
async def test_legacy_staff_label_without_current_decision_is_rejected(db_session, change):
    ctx = await _fixture(db_session)
    source = ctx.source
    fields = approve_staff_legacy(source, ctx.request.actor_id)
    updates = {"reviewer": ("verification_reviewed_by_user_id", None),
        "review_time": ("verification_reviewed_at", None), "confirmation": ("confirmed_at", None),
        "unequal_confirmation": ("confirmed_at", source.confirmed_at - timedelta(seconds=1)),
        "extraction_revision": ("extraction_revision", 0),
        "verification_revision": ("post_submission_verification_revision", 0),
        "bool_revision": ("post_submission_verification_revision", True),
        "needs_review": ("status", "needs_review"), "bare_confirmed": ("status", "confirmed"),
        "newer_client_review": ("client_reviewed_at", source.confirmed_at + timedelta(seconds=1)),
        "newer_ai": ("post_submission_verified_at", source.confirmed_at + timedelta(seconds=1))}
    key, value = updates[change]
    setattr(source, key, value)
    with pytest.raises(EnrollmentError):
        accept_source(source, fields, operator=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("passport_number", ""), ("date_of_birth", "1990-02-30"),
    ("date_of_expiry", ""), ("document_type", "V"), ("issuing_country", "ZZZ")])
async def test_staff_approval_requires_valid_passport_identity_fields(db_session, field, value):
    ctx = await _fixture(db_session)
    fields = approve_staff_legacy(ctx.source, ctx.request.actor_id)
    fields[field] = value
    with pytest.raises(EnrollmentError):
        accept_source(ctx.source, fields, operator=True)


@pytest.mark.asyncio
async def test_staff_context_is_truthful_and_saved_mrz_conflicts_are_not_bypassed(db_session):
    ctx = await _fixture(db_session)
    fields = approve_staff_legacy(ctx.source, ctx.request.actor_id)
    fields["issuing_country"] = "GBR"
    accepted = accept_source(ctx.source, fields, operator=True)
    assert accepted.fields["issuing_country"] == "GBR"
    assert accepted.fields["document_type"] == "P"
    fields["document_type"] = "PASSPORT"
    assert accept_source(ctx.source, fields, operator=True).acceptance_rule == "staff_review"
    fields.pop("issuing_country")
    ctx.source.mrz_raw = "conflicting or malformed stored MRZ"
    with pytest.raises(EnrollmentError, match="reliable_issuing_context_required"):
        accept_source(ctx.source, fields, operator=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["reviewer", "review_time", "extraction_revision", "verification_revision",
    "image", "fields", "status", "missing_digest", "missing_reviewer"])
async def test_staff_copy_authority_rechecks_frozen_decision_and_source_content(db_session, change):
    ctx = await _fixture(db_session)
    source = ctx.source
    approve_staff_legacy(source, ctx.request.actor_id)
    await db_session.flush()
    await register(db_session, ctx)
    revision = await db_session.scalar(select(Document))
    if change == "reviewer":
        source.verification_reviewed_by_user_id = uuid.uuid4()
    elif change == "review_time":
        source.verification_reviewed_at = source.confirmed_at = source.confirmed_at + timedelta(seconds=1)
    elif change == "extraction_revision":
        source.extraction_revision += 1
    elif change == "verification_revision":
        source.post_submission_verification_revision += 1
    elif change == "image":
        source.image_s3_key = "changed/front.jpg"
    elif change == "fields":
        source.confirmed_fields = {**source.confirmed_fields, "nationality": "GBR"}
    elif change == "status":
        source.status = "needs_review"
    else:
        provenance = dict(revision.source_provenance)
        provenance.pop("source_input_digest" if change == "missing_digest" else "source_reviewed_by_user_id")
        revision.source_provenance = provenance
    assert not retained_source_is_current(revision, source, ctx.crypto)
    assert not registration_is_current(revision, source, ctx.crypto)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["verification_revision", "review_time"])
async def test_new_staff_generation_preserves_old_trip_and_retries_idempotently(db_session, change):
    ctx = await _fixture(db_session)
    source = ctx.source
    approve_staff_legacy(source, ctx.request.actor_id)
    await db_session.flush()
    person_id = await register(db_session, ctx)
    original = await db_session.scalar(select(Document))
    snapshot = await db_session.scalar(select(Participation))
    proof = deepcopy(original.source_provenance)
    old_key = historical_enrollment_key(source, ctx.group.company_id, ctx.crypto)
    if change == "verification_revision":
        source.post_submission_verification_revision += 1
    else:
        source.verification_reviewed_at = source.confirmed_at = source.confirmed_at + timedelta(seconds=1)
    await db_session.flush()
    new_key = historical_enrollment_key(source, ctx.group.company_id, ctx.crypto)
    assert old_key != new_key and new_key.startswith("history-staff:") and len(new_key) <= 128
    assert source.extraction_revision == 1
    assert await register(db_session, ctx) == person_id
    assert await register(db_session, ctx) == person_id
    assert await db_session.scalar(select(func.count()).select_from(Document)) == 2
    latest = await db_session.scalar(select(Document).order_by(Document.revision_number.desc()).limit(1))
    assert latest.id != original.id and latest.revision_number == original.revision_number + 1
    assert original.source_provenance == proof and snapshot.document_revision_id == original.id
    assert retained_source_is_current(latest, source, ctx.crypto)
    assert not retained_source_is_current(original, source, ctx.crypto)


@pytest.mark.asyncio
async def test_domain_reviewed_edit_revokes_approval_until_explicit_staff_reapproval(db_session):
    ctx = await _fixture(db_session)
    source = ctx.source
    approve_staff_legacy(source, ctx.request.actor_id)
    await db_session.flush()
    await register(db_session, ctx)
    original = await db_session.scalar(select(Document))
    original_key = historical_enrollment_key(source, ctx.group.company_id, ctx.crypto)
    entity = PassportSubmissionRepository._to_entity(source)
    entity.update_reviewed_fields({"nationality": "GBR"})
    edited = PassportSubmissionRepository._to_model(entity)
    assert edited.status == "needs_review"
    assert edited.verification_reviewed_by_user_id is None
    assert edited.verification_reviewed_at is None and edited.confirmed_at is None
    assert not retained_source_is_current(original, edited, ctx.crypto)
    with pytest.raises(EnrollmentError):
        accept_source(edited, edited.confirmed_fields, operator=True)
    entity.staff_approve_verification(reviewer_id=ctx.request.actor_id, reviewer_name="Reviewer",
        expected_extraction_revision=entity.extraction_revision)
    reapproved = PassportSubmissionRepository._to_model(entity)
    assert accept_source(reapproved, reapproved.confirmed_fields, operator=True).acceptance_rule == STAFF_ACCEPTANCE_RULE
    assert reapproved.extraction_revision == source.extraction_revision + 2
    assert reapproved.post_submission_verification_revision == source.post_submission_verification_revision + 1
    assert reapproved.confirmed_at == reapproved.verification_reviewed_at
    assert not retained_source_is_current(original, reapproved, ctx.crypto)
    assert historical_enrollment_key(reapproved, ctx.group.company_id, ctx.crypto) != original_key
