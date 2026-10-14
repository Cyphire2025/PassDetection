"""Current projections agree while frozen trips and real newer evidence survive."""

import json
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.application.companies.export_source import EXCEL_HEADERS, people_export_page
from app.application.companies.people import current_document, current_person
from app.application.travellers.accepted_source import accept_source
from app.application.travellers.enrollment import enroll_submission
from app.application.travellers.impact import process_impact_page
from app.application.travellers.passport_selection import available_passports
from app.application.travellers.source_acceptance_provenance import acceptance_provenance
from app.infrastructure.database.company_data_export_models import CompanyDataExportJobModel as Job
from app.infrastructure.database.traveller_reuse_models import (
    TravellerChangeEventModel as Event,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentAssetModel as Asset,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentReviewTaskModel as Review,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentRevisionModel as Document,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerParticipationModel as Participation,
)
from app.infrastructure.database.traveller_reuse_models import TravellerProfileModel as Person
from app.infrastructure.repositories.user_repository import UserRepository
from tests.unit.application.test_traveller_document_selection import (
    historical_placeholder,
    ready_document,
)
from tests.unit.application.test_traveller_enrollment import _source
from tests.unit.application.test_traveller_legacy_staff_approval import approve_staff_legacy


async def consumer_fixture(session, availability="unreadable"):
    ctx, passport, real = await ready_document(session)
    source, placeholder = await historical_placeholder(session, ctx, passport, availability=availability)
    # The metadata has different details: a consumer must not accidentally use
    # its expiry simply because it was registered after the photographed copy.
    source.confirmed_fields = {**source.confirmed_fields, "date_of_expiry": "2039-01-01"}
    accepted = accept_source(source, dict(source.confirmed_fields), operator=True)
    placeholder.fields_ciphertext = ctx.crypto.encrypt(json.dumps(accepted.fields))
    placeholder.expiry_date = date(2039, 1, 1)
    placeholder.source_provenance = {
        **placeholder.source_provenance, **acceptance_provenance(accepted, source, ctx.crypto),
    }
    await session.flush()
    person = await session.get(Person, passport.traveller_id)
    user = await UserRepository(session).get_by_id(ctx.request.actor_id)
    return ctx, passport, real, placeholder, person, user


async def newer_real_document(session, ctx, person, state):
    source = _source(ctx.group, expiry="2025-01-01" if state == "expired" else "2035-01-01")
    approve_staff_legacy(source, ctx.request.actor_id)
    session.add(source)
    await session.flush()
    result = await enroll_submission(session, replace(ctx.request, submission_id=source.id,
        idempotency_key=f"consumer-real-{state}", traveller_id=person.id,
        expected_profile_revision=person.revision, authority_kind="operator_registration"), ctx.crypto)
    document = await session.get(Document, result.document_revision_id)
    for asset in await session.scalars(select(Asset).where(Asset.document_revision_id == document.id)):
        if state == "missing":
            await session.delete(asset)
        elif state == "unreadable":
            asset.availability = "unreadable"
    await session.flush()
    return document


def export_page_request(person, user):
    return Job(agency_id=person.agency_id, company_id=person.company_id,
        requested_by_user_id=user.id, created_at=datetime.now(UTC), cursor=None)


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["placeholder_pending", "placeholder_unreadable",
    "real_pending", "real_unreadable", "real_missing", "real_expired"])
async def test_profile_excel_and_passport_choices_select_the_same_current_evidence(db_session, state):
    ctx, passport, real, placeholder, person, user = await consumer_fixture(
        db_session, availability="pending" if state == "placeholder_pending" else "unreadable")
    trip = await db_session.scalar(select(Participation).where(Participation.traveller_id == person.id))
    frozen_trip = trip.document_revision_id
    expected = (await newer_real_document(db_session, ctx, person, state.removeprefix("real_"))
        if state.startswith("real_") else real)

    chosen = await current_document(db_session, person)
    assert chosen is not None and chosen[1].id == expected.id
    profile = await current_person(db_session, person, ctx.crypto, user=user)
    assert profile.current_document.id == expected.id
    rows, cursor = await people_export_page(db_session, export_page_request(person, user), user, ctx.crypto)
    assert len(rows) == 1 and cursor == person.id
    row = dict(zip(EXCEL_HEADERS, rows[0], strict=True))
    assert row["Source record ID"] == str(expected.id)
    assert row["Record source"] == "accepted_current_document"
    assert row["date_of_expiry"] == expected.expiry_date.isoformat()
    options = await available_passports(SimpleNamespace(session=db_session, crypto=ctx.crypto),
        agency_id=person.agency_id, company_id=person.company_id, traveller_id=person.id)
    assert len(options) == 1 and options[0]["id"] == passport.id
    assert options[0]["expiry_date"] == expected.expiry_date != placeholder.expiry_date
    assert trip.document_revision_id == frozen_trip
    assert placeholder.status == "accepted" and ctx.source.confirmed_fields["date_of_expiry"] == "2030-01-01"


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["agency_id", "company_id", "id"])
async def test_current_projection_and_passport_choices_cannot_cross_scope(db_session, changed):
    ctx, _, _, _, person, user = await consumer_fixture(db_session)
    values = {"id": person.id, "agency_id": person.agency_id, "company_id": person.company_id}
    values[changed] = uuid.uuid4()
    other_scope = Person(**values)
    assert await current_document(db_session, other_scope) is None
    assert await available_passports(SimpleNamespace(session=db_session, crypto=ctx.crypto),
        agency_id=other_scope.agency_id, company_id=other_scope.company_id, traveller_id=other_scope.id) == []
    if changed != "id":
        rows, cursor = await people_export_page(db_session, export_page_request(other_scope, user), user, ctx.crypto)
        assert rows == [] and cursor is None


@pytest.mark.asyncio
async def test_impact_ignores_metadata_shadow_but_records_a_real_pending_replacement(db_session):
    ctx, passport, real, placeholder, person, _ = await consumer_fixture(db_session)
    trip = await db_session.scalar(select(Participation).where(Participation.traveller_id == person.id))
    # Historical registration may leave the original membership submitted; both
    # accepted and submitted participate in operational review.
    assert trip.status in {"accepted", "submitted"} and trip.document_revision_id == real.id
    event = Event(agency_id=person.agency_id, company_id=person.company_id, traveller_id=person.id,
        event_type="document_promoted", aggregate_id=passport.id, aggregate_revision=passport.revision,
        idempotency_key="metadata-consumer-impact", reason_code="operator_registered_scan")
    db_session.add(event)
    await db_session.flush()
    assert await process_impact_page(db_session, event.id) == 1
    assert await db_session.scalar(select(func.count()).select_from(Review)) == 0

    replacement = await newer_real_document(db_session, ctx, person, "pending")
    promoted = await db_session.scalar(select(Event).where(Event.idempotency_key == f"enrollment:{replacement.id}"))
    assert await process_impact_page(db_session, promoted.id) == 1
    review = await db_session.scalar(select(Review).where(Review.event_id == promoted.id))
    assert review.old_document_revision_id == real.id and review.new_document_revision_id == replacement.id
    assert review.new_document_revision_id != placeholder.id and trip.document_revision_id == real.id
    assert await process_impact_page(db_session, promoted.id) == 0
    assert await db_session.scalar(select(func.count()).select_from(Review)) == 1


@pytest.mark.asyncio
async def test_original_image_pages_preserve_sides_and_skip_stale_or_hidden_sources(db_session, monkeypatch):
    from app.application.companies import export_source
    from app.infrastructure.database.traveller_reuse_models import (
        TravellerMatchCaseModel as MatchCase,
    )
    from tests.integration.test_company_people import people_fixture

    ctx, person, user = await people_fixture(db_session)
    sources = [ctx.source, *[_source(ctx.group) for _ in range(3)]]
    db_session.add_all(sources[1:])
    await db_session.flush()
    sources[2].image_s3_key = "travellers/unavailable/front.jpg"
    sources[2].passport_back_s3_key = "travellers/unavailable/back.jpg"
    sources[3].status = "rejected"
    cases = [MatchCase(agency_id=person.agency_id, company_id=person.company_id,
        group_id=ctx.group.id, traveller_id=person.id, source_kind="passport_submission",
        source_row_key=str(source.id), status="resolved", reason_code="operator_historical_registration")
        for source in sources]
    db_session.add_all(cases)
    await db_session.flush()
    monkeypatch.setattr(export_source, "IMAGE_PAGE_SIZE", 2)
    job = export_page_request(person, user)
    for side, field in (("front", "image_s3_key"), ("back", "passport_back_s3_key")):
        job.phase, job.cursor = f"source_{side}", None
        rows = []
        page_sizes = []
        for _ in range(3):
            page = await export_source.source_image_page(db_session, job, user)
            page_sizes.append(len(page))
            if not page:
                break
            rows.extend(page)
            job.cursor = page[-1].identifier
        assert page_sizes == [2, 2, 0]
        assert len({row.identifier for row in rows}) == 4
        assert {row.revision_id for row in rows} == {source.id for source in sources}
        available = [row for row in rows if row.key]
        assert {row.key for row in available} == {getattr(source, field) for source in sources[:2]}
        assert all(row.side == side and row.person_id == person.id for row in rows)
        assert all(row.source_kind == "original_submission" for row in rows)
        assert all(row.key == "" and row.size == 0 for row in rows if row.revision_id in {sources[2].id, sources[3].id})
    # Original source export never follows a retained locator or revives a
    # rejected upload, and source history itself remains untouched.
    assert sources[2].image_s3_key == "travellers/unavailable/front.jpg"
    assert sources[3].status == "rejected"


@pytest.mark.asyncio
async def test_empty_company_search_and_person_without_documents_are_private_lazy_results(db_session, monkeypatch):
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.infrastructure.database.traveller_reuse_models import (
        TravellerMatchCaseModel as MatchCase,
    )
    from app.presentation.api.v1.routes import company_people
    from tests.integration.test_company_people import people_fixture
    from tests.integration.test_company_people_http import application

    ctx, person, user = await people_fixture(db_session)
    incomplete = Person(agency_id=person.agency_id, company_id=person.company_id, status="review_required")
    db_session.add(incomplete)
    await db_session.flush()
    db_session.add(MatchCase(agency_id=person.agency_id, company_id=person.company_id,
        group_id=ctx.group.id, traveller_id=incomplete.id, source_kind="passport_submission",
        source_row_key=str(ctx.source.id), status="resolved", reason_code="historical_source_only"))
    await db_session.commit()
    app = application(async_sessionmaker(db_session.bind, expire_on_commit=False), user, ctx.crypto)
    monkeypatch.setattr(company_people, "MinioStorageRepository", lambda: pytest.fail("Eager image I/O"))
    prefix = f"/api/v1/companies/{person.company_id}/people"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        empty = await http.get(prefix, params={"search": "No matching synthetic traveller"})
        assert empty.status_code == 200 and empty.headers["Cache-Control"] == "private, no-store"
        assert empty.json()["items"] == [] and not empty.json()["has_more"]
        assert empty.json()["next_cursor"] is None
        documents = await http.get(f"{prefix}/{incomplete.id}/documents")
        assert documents.status_code == 200 and documents.headers["Cache-Control"] == "private, no-store"
        assert documents.json() == {"items": [], "has_more": False, "next_cursor": None}
        record = await http.get(f"{prefix}/{incomplete.id}/record")
        assert record.status_code == 200 and record.json()["current_document"] is None
