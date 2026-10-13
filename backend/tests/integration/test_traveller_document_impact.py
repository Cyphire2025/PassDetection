"""Resumable impact, bounded visibility, commit-ordered reference checkpoints."""

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.travellers.change_feed import publish_change_page, read_changes
from app.application.travellers.impact import process_impact_page
from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import AuthorizationError, ConflictError
from app.infrastructure.database.models import ClientGroupModel, UserModel
from app.infrastructure.database.traveller_reuse_models import (
    TravellerChangeEventModel,
    TravellerDocumentReviewTaskModel,
    TravellerDocumentRevisionModel,
    TravellerParticipationModel,
)
from app.presentation.api.v1.routes.company_review_tasks import (
    ResolveReviewTaskRequest,
    resolve_review_task,
    review_tasks,
)
from tests.integration.traveller_reuse_fixtures import reuse_context, seed_person


async def impact_context(session, settings, count=1):
    service, company, group = await reuse_context(session, settings)
    person = await seed_person(service, group)
    user = User.create(email=f"{uuid.uuid4()}@example.com", hashed_password="synthetic", full_name="Review Admin",
        role=UserRole.AGENCY_ADMIN, agency_id=group.agency_id)
    session.add(UserModel(id=user.id, email=user.email, full_name=user.full_name, hashed_password="synthetic",
        role=user.role.value, agency_id=group.agency_id))
    groups = [group]
    for index in range(count - 1):
        groups.append(ClientGroupModel(agency_id=group.agency_id, company_id=company.id, company_revision=1,
            token=uuid.uuid4().hex, name=f"Future trip {index}", travel_date=group.travel_date,
            status="archived" if index % 4 == 0 else "active"))
    session.add_all(groups[1:])
    await session.flush()
    participants = [TravellerParticipationModel(agency_id=group.agency_id, company_id=company.id,
        group_id=item.id, traveller_id=person.profile.id, passport_id=person.passport.id,
        document_revision_id=person.document.id, source_kind="accepted_submission", status="accepted",
        profile_revision=1, contact_revision=1, question_version="frozen", idempotency_key=uuid.uuid4().hex,
        answers={"unchanged": "original"}) for item in groups]
    replacement = TravellerDocumentRevisionModel(agency_id=group.agency_id, company_id=company.id,
        traveller_id=person.profile.id, passport_id=person.passport.id, revision_number=2, status="accepted",
        fields_ciphertext=person.document.fields_ciphertext, accepted_at=datetime.now(UTC),
        idempotency_key=uuid.uuid4().hex, reliable_fields=person.document.reliable_fields)
    event = TravellerChangeEventModel(agency_id=group.agency_id, company_id=company.id,
        traveller_id=person.profile.id, event_type="document_promoted", aggregate_id=person.passport.id,
        aggregate_revision=2, idempotency_key=uuid.uuid4().hex, reason_code="staff_accepted_renewal")
    session.add_all([*participants, replacement, event])
    await session.commit()
    return service, company, user, participants, event, replacement


@pytest.mark.asyncio
async def test_205_trip_impact_is_resumable_and_does_not_rewrite_frozen_records(db_session, test_settings):
    _, company, _, participants, event, replacement = await impact_context(db_session, test_settings, count=205)
    old_revision = participants[0].document_revision_id
    processed = []
    while event.processed_at is None:
        processed.append(await process_impact_page(db_session, event.id, page_size=31))
        await db_session.commit()
    assert sum(processed) == 205 and max(processed) <= 31
    expected = await db_session.scalar(select(func.count()).select_from(ClientGroupModel).where(
        ClientGroupModel.company_id == company.id, ClientGroupModel.status == "active"))
    tasks = list((await db_session.scalars(select(TravellerDocumentReviewTaskModel))).all())
    assert len(tasks) == expected
    assert all(task.old_document_revision_id == old_revision and task.new_document_revision_id == replacement.id for task in tasks)
    assert all(person.document_revision_id == old_revision and person.answers == {"unchanged": "original"} for person in participants)
    assert await process_impact_page(db_session, event.id) == 0
    assert await db_session.scalar(select(func.count()).select_from(TravellerDocumentReviewTaskModel)) == expected


@pytest.mark.asyncio
async def test_page_rollback_retries_exactly_once(db_session, test_settings):
    _, _, _, _, event, _ = await impact_context(db_session, test_settings, count=5)
    event_id = event.id
    with pytest.raises(RuntimeError):
        async with db_session.begin_nested():
            await process_impact_page(db_session, event_id, page_size=2)
            raise RuntimeError("synthetic-interruption")
    assert await db_session.scalar(select(func.count()).select_from(TravellerDocumentReviewTaskModel)) == 0
    await process_impact_page(db_session, event_id, page_size=2)
    await db_session.commit()
    assert await db_session.scalar(select(func.count()).select_from(TravellerDocumentReviewTaskModel)) <= 2


@pytest.mark.asyncio
async def test_impact_retry_lease_stops_after_five_failures(db_session, test_settings):
    from app.infrastructure.travellers.impact_runtime import _failed, _reserve

    _, _, _, _, event, _ = await impact_context(db_session, test_settings)
    event_id = event.id
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    for attempt in range(1, 6):
        assert await _reserve(factory) == event_id
        assert await _reserve(factory) is None  # Durable lease blocks immediate retry.
        await _failed(factory, event_id)
        await db_session.refresh(event)
        assert event.impact_attempt_count == attempt
        assert event.impact_error_code == ("impact_attempts_exhausted" if attempt == 5 else "impact_page_failed")
        event.impact_available_at = datetime.now(UTC) - timedelta(seconds=1)
        await db_session.commit()
    assert await _reserve(factory) is None
    assert event.processed_at is None


@pytest.mark.asyncio
async def test_review_resolution_requires_current_revision_and_scope(db_session, test_settings):
    _, company, user, participants, event, _ = await impact_context(db_session, test_settings)
    await process_impact_page(db_session, event.id)
    await db_session.commit()
    page = await review_tasks(company.id, agency_id=None, status="pending", cursor=None, page_size=25,
        user=user, session=db_session, settings=test_settings)
    assert len(page.items) == 1
    task = page.items[0]
    body = ResolveReviewTaskRequest(expected_revision=task.revision,
        expected_participation_revision=task.current_participation_revision, resolution="resolved",
        reason="Existing downstream bookings reviewed manually")
    with pytest.raises(AuthorizationError):
        await resolve_review_task(company.id, task.id, body, agency_id=None,
            user=replace(user, role=UserRole.AGENCY_STAFF), session=db_session)
    result = await resolve_review_task(company.id, task.id, body, agency_id=None, user=user, session=db_session)
    assert result.status == "resolved" and result.revision == 2
    assert participants[0].revision == 1
    with pytest.raises(ConflictError):
        await resolve_review_task(company.id, task.id, body, agency_id=None, user=user, session=db_session)


@pytest.mark.asyncio
async def test_change_feed_does_not_miss_a_late_committed_old_timestamp(db_session, test_settings):
    _, company, user, _, original, _ = await impact_context(db_session, test_settings)
    for index in range(204):
        db_session.add(TravellerChangeEventModel(agency_id=company.agency_id, company_id=company.id,
            traveller_id=original.traveller_id, event_type="changed", aggregate_id=uuid.uuid4(),
            aggregate_revision=index + 1, idempotency_key=uuid.uuid4().hex, reason_code="current_trip_submitted"))
    await db_session.commit()
    assert await publish_change_page(db_session) == 100
    await db_session.commit()
    assert await publish_change_page(db_session) == 100
    await db_session.commit()
    assert await publish_change_page(db_session) == 5
    await db_session.commit()
    checkpoint, sequences = None, []
    while True:
        page = await read_changes(db_session, user=user, company_id=company.id, agency_id=None,
            checkpoint=checkpoint, page_size=37, signing_secret="synthetic-checkpoint-secret")
        sequences.extend(item["sequence"] for item in page["items"])
        checkpoint = page["checkpoint"]
        if not page["has_more"]:
            break
    assert sequences == list(range(1, 206))
    late = TravellerChangeEventModel(agency_id=company.agency_id, company_id=company.id,
        traveller_id=original.traveller_id, event_type="removed", aggregate_id=uuid.uuid4(), aggregate_revision=1,
        idempotency_key=uuid.uuid4().hex, reason_code="explicit_removal", created_at=datetime.now(UTC) - timedelta(days=30))
    db_session.add(late)
    await db_session.commit()
    assert await publish_change_page(db_session) == 1
    await db_session.commit()
    page = await read_changes(db_session, user=user, company_id=company.id, agency_id=None,
        checkpoint=checkpoint, page_size=37, signing_secret="synthetic-checkpoint-secret")
    assert [item["sequence"] for item in page["items"]] == [206]
    assert page["items"][0]["kind"] == "removed"
    assert "passport_number" not in str(page) and "object_key" not in str(page)
    with pytest.raises(ValueError):
        await read_changes(db_session, user=replace(user, id=uuid.uuid4()), company_id=company.id, agency_id=None,
            checkpoint=checkpoint, page_size=37, signing_secret="synthetic-checkpoint-secret")
    with pytest.raises(ValueError):
        await read_changes(db_session, user=user, company_id=company.id, agency_id=None,
            checkpoint=checkpoint + "tampered", page_size=37, signing_secret="synthetic-checkpoint-secret")
