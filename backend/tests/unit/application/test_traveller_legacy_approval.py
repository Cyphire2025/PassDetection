"""Existing current AI decisions accept legacy fields without inventing country."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.application.interfaces.post_submission_verification import POST_SUBMISSION_PASSPORT_FIELDS
from app.application.travellers.accepted_source import accept_source, retained_source_is_current
from app.application.travellers.legacy_source_acceptance import AI_ACCEPTANCE_RULE
from app.application.travellers.versioning import EnrollmentError
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentRevisionModel,
    TravellerPassportModel,
)
from tests.unit.application.test_company_history_registration import register
from tests.unit.application.test_traveller_enrollment import _fixture


def approve_legacy(source):
    fields = {
        **source.confirmed_fields,
        "nationality": "IND",
        "place_of_issue": "DELHI",
        "sex": "M",
    }
    fields.pop("issuing_country", None)
    fields.pop("document_type", None)
    source.confirmed_fields, source.mrz_raw = fields, None
    source.status, source.client_reviewed_at = (
        "ai_approved",
        datetime.now(UTC) - timedelta(seconds=1),
    )
    source.post_submission_verified_at = datetime.now(UTC)
    source.post_submission_verification_revision = 1
    source.post_submission_verification = {
        "verification_status": "ai_approved",
        "provider_status": "verified",
        "incorrect_fields": [],
        "suspicious_fields": [],
        "fields": [
            {
                "field": key,
                "verdict": "correct",
                "observed_value": fields[key],
                "confidence": 0.99,
                "reason_code": "match",
            }
            for key in POST_SUBMISSION_PASSPORT_FIELDS
        ],
    }
    return fields


@pytest.mark.asyncio
async def test_existing_ai_approval_accepts_unknown_context_and_preserves_original_fields(
    db_session,
):
    ctx = await _fixture(db_session)
    fields = approve_legacy(ctx.source)
    await db_session.flush()
    person_id = await register(db_session, ctx)
    revision = await db_session.scalar(select(TravellerDocumentRevisionModel))
    passport = await db_session.scalar(select(TravellerPassportModel))
    assert revision.traveller_id == person_id and passport.issuing_country == "UNK"
    assert ctx.source.confirmed_fields == fields and "issuing_country" not in fields
    assert revision.source_provenance["acceptance_rule"] == AI_ACCEPTANCE_RULE
    assert revision.source_provenance["issuing_context_source"] == "not_recorded"
    assert revision.source_provenance["source_verification_revision"] == 1
    assert len(revision.source_provenance["source_input_digest"]) == 64
    assert set(revision.reliable_fields) == {"date_of_birth", "issue_date", "expiry_date"}
    assert retained_source_is_current(revision, ctx.source, ctx.crypto)


@pytest.mark.asyncio
async def test_current_exact_proof_supersedes_old_extraction_hints_without_inventing_issuer(db_session):
    ctx = await _fixture(db_session)
    fields = approve_legacy(ctx.source)
    ctx.source.extraction_conflicts = [{"field": "passport_number", "source": "old_ocr_hint"}]
    fields["staff_code"] = "STAFF01"
    fields["designation"] = "Coordinator"
    fields["meal_preference"] = "Vegetarian"
    accepted = accept_source(ctx.source, fields, operator=True)
    assert accepted.fields["issuing_country"] == "UNK"
    assert accepted.fields["staff_code"] == "STAFF01"


@pytest.mark.asyncio
async def test_explicitly_verified_absent_surname_is_supported(db_session):
    ctx = await _fixture(db_session)
    fields = approve_legacy(ctx.source)
    fields["surname"] = ""
    proof = deepcopy(ctx.source.post_submission_verification)
    row = next(item for item in proof["fields"] if item["field"] == "surname")
    row.update(observed_value=None, reason_code="not_present")
    ctx.source.post_submission_verification = proof
    assert accept_source(ctx.source, fields, operator=True).fields["surname"] == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["bad_row", "unknown_field", "incorrect_field", "missing_observation", "missing_value"])
async def test_malformed_or_unobserved_field_cannot_become_verified_identity(db_session, change):
    ctx = await _fixture(db_session)
    fields = approve_legacy(ctx.source)
    proof = deepcopy(ctx.source.post_submission_verification)
    if change == "bad_row":
        proof["fields"][0] = "invalid"
    elif change == "unknown_field":
        proof["fields"][0]["field"] = "unknown"
    elif change == "incorrect_field":
        proof["fields"][0]["verdict"] = "incorrect"
    elif change == "missing_observation":
        proof["fields"][0]["observed_value"] = None
    else:
        fields.pop(proof["fields"][0]["field"])
    ctx.source.post_submission_verification = proof
    with pytest.raises(EnrollmentError):
        accept_source(ctx.source, fields, operator=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "label_only",
        "wrong_revision",
        "missing_time",
        "stale_time",
        "provider_failure",
        "incorrect",
        "suspicious",
        "duplicate_field",
        "missing_field",
        "field_changed",
        "invalid_date",
        "mrz_conflict",
    ],
)
async def test_legacy_acceptance_requires_current_complete_matching_verification(
    db_session, change
):
    ctx = await _fixture(db_session)
    approve_legacy(ctx.source)
    source = ctx.source
    proof = deepcopy(source.post_submission_verification)
    if change == "label_only":
        source.post_submission_verification = None
    elif change == "wrong_revision":
        source.post_submission_verification_revision = 0
    elif change == "missing_time":
        source.post_submission_verified_at = None
    elif change == "stale_time":
        source.post_submission_verified_at = source.client_reviewed_at - timedelta(seconds=1)
    elif change == "provider_failure":
        proof["provider_status"] = "timeout"
    elif change in {"incorrect", "suspicious"}:
        proof[f"{change}_fields"] = ["passport_number"]
    elif change == "duplicate_field":
        proof["fields"][-1] = proof["fields"][0]
    elif change == "missing_field":
        proof["fields"].pop()
    elif change == "field_changed":
        source.confirmed_fields = {**source.confirmed_fields, "passport_number": "DIFFERENT"}
    elif change == "invalid_date":
        source.confirmed_fields = {**source.confirmed_fields, "date_of_birth": "1990-02-30"}
        next(row for row in proof["fields"] if row["field"] == "date_of_birth")[
            "observed_value"
        ] = "1990-02-30"
    elif change == "mrz_conflict":
        source.mrz_raw = "not an agreed stored MRZ"
    if change != "label_only":
        source.post_submission_verification = proof
    with pytest.raises(EnrollmentError):
        accept_source(source, source.confirmed_fields, operator=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["verification_revision", "verification_time", "image", "reviewed_fields", "status"]
)
async def test_pending_copy_rechecks_frozen_revision_time_and_input_digest(db_session, change):
    ctx = await _fixture(db_session)
    approve_legacy(ctx.source)
    await db_session.flush()
    await register(db_session, ctx)
    revision = await db_session.scalar(select(TravellerDocumentRevisionModel))
    if change == "verification_revision":
        ctx.source.post_submission_verification_revision += 1
    elif change == "verification_time":
        ctx.source.post_submission_verified_at += timedelta(seconds=1)
    elif change == "image":
        ctx.source.image_s3_key = "changed/source.jpg"
    elif change == "reviewed_fields":
        ctx.source.confirmed_fields = {**ctx.source.confirmed_fields, "nationality": "GBR"}
    else:
        ctx.source.status = "needs_review"
    assert not retained_source_is_current(revision, ctx.source, ctx.crypto)
