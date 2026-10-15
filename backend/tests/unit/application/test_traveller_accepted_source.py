"""Historical acceptance validates stored MRZ bytes and actual review state."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.application.travellers.accepted_source import (
    MRZ_ACCEPTANCE_RULE,
    accept_source,
    retained_source_is_current,
)
from app.application.travellers.versioning import EnrollmentError
from app.infrastructure.database.traveller_reuse_models import TravellerDocumentRevisionModel
from tests.unit.application.test_company_history_registration import register
from tests.unit.application.test_traveller_enrollment import _fixture

MRZ = "P<INDERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<\nL898902C36UTO7408122F1204159ZE184226B<<<<<10"
FIELDS = {"passport_number": "L898902C3", "date_of_birth": "1974-08-12", "date_of_expiry": "2012-04-15",
          "date_of_issue": "2002-04-16", "nationality": "GBR"}


@pytest.mark.asyncio
async def test_client_reviewed_mrz_retains_truthful_provenance_without_staff_approval(db_session):
    ctx = await _fixture(db_session)
    ctx.source.status, ctx.source.client_reviewed_at = "client_submitted", datetime.now(UTC)
    ctx.source.confirmed_fields, ctx.source.mrz_raw = FIELDS, MRZ
    await db_session.flush()
    person_id = await register(db_session, ctx)
    revision = await db_session.scalar(select(TravellerDocumentRevisionModel))
    assert revision is not None and revision.traveller_id == person_id
    assert revision.source_provenance["acceptance_rule"] == MRZ_ACCEPTANCE_RULE
    assert revision.source_provenance["issuing_context_source"] == "validated_saved_mrz"
    assert revision.reliable_fields == {key: {"accepted": True, "source": "verified_import"}
                                        for key in ("date_of_birth", "expiry_date")}
    assert retained_source_is_current(revision, ctx.source)
    ctx.source.client_reviewed_at = None
    assert not retained_source_is_current(revision, ctx.source)


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["missing_review", "missing_mrz", "checksum", "short_header", "third_line",
                                      "passport", "birth", "expiry", "issuer", "kind", "invalid_date"])
async def test_inconsistent_or_unreviewed_mrz_never_accepts_a_retained_document(db_session, mutation):
    ctx = await _fixture(db_session)
    source = ctx.source
    source.status, source.client_reviewed_at = "client_submitted", datetime.now(UTC)
    source.confirmed_fields, source.mrz_raw = dict(FIELDS), MRZ
    if mutation == "missing_review":
        source.client_reviewed_at = None
    elif mutation == "missing_mrz":
        source.mrz_raw = None
    elif mutation == "checksum":
        source.mrz_raw = MRZ[:-1] + "9"
    elif mutation == "short_header":
        source.mrz_raw = MRZ.replace("<\n", "\n")
    elif mutation == "third_line":
        source.mrz_raw = "untrusted preceding text\n" + MRZ
    else:
        key, value = {"passport": ("passport_number", "OTHER123"), "birth": ("date_of_birth", "1974-08-13"),
            "expiry": ("date_of_expiry", "2012-04-16"), "issuer": ("issuing_country", "GBR"),
            "kind": ("document_type", "ID"), "invalid_date": ("date_of_birth", "1974-99-99")}[mutation]
        source.confirmed_fields = {**source.confirmed_fields, key: value}
    with pytest.raises(EnrollmentError):
        accept_source(source, source.confirmed_fields, operator=True)


@pytest.mark.asyncio
async def test_staff_context_fallback_is_mrz_derived_without_nationality_inference(db_session):
    ctx = await _fixture(db_session)
    ctx.source.confirmed_fields, ctx.source.mrz_raw = FIELDS, MRZ
    accepted = accept_source(ctx.source, FIELDS, operator=True)
    assert accepted.fields["issuing_country"] == "IND" and accepted.fields["nationality"] == "GBR"
    assert accepted.fields["document_type"] == "P" and accepted.reliable_source == "staff_review"
