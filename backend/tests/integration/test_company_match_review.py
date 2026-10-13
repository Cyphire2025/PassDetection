"""Staff matching is bounded, tenant scoped and never substitutes public proof."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.application.companies.assignment import assign_group_company
from app.application.companies.traveller_metrics import group_traveller_counts
from app.application.travellers.match_resolution import resolve_match
from app.application.travellers.reconciliation import enqueue_reconciliation, reconcile_page
from app.domain.exceptions.exceptions import ConflictError, EntityNotFoundError
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.database.traveller_reuse_models import (
    TravellerGroupReuseConfigModel,
    TravellerMatchCaseModel,
    TravellerParticipationModel,
    TravellerProfileModel,
)
from app.presentation.api.v1.routes.company_match_review import matching_preview
from tests.integration.test_company_directory import company, legacy_group, seed_user
from tests.unit.application.test_traveller_reconciliation import _crypto, _seed_sources


async def context(session):
    user = await seed_user(session)
    client, group = await company(session, user), await legacy_group(session, user)
    model = await assign_group_company(session, user=user, agency_id=user.agency_id,
        group_id=group.id, company_id=client.id, expected_revision=0)
    person = TravellerProfileModel(agency_id=user.agency_id, company_id=client.id, status="active")
    session.add(person)
    await session.flush()
    return user, client, model, person


def match(client, group, person=None):
    return TravellerMatchCaseModel(agency_id=client.agency_id, company_id=client.id,
        group_id=group.id, source_kind="whatsapp_rejected", source_row_key=str(uuid.uuid4()),
        status="provisional" if person else "unmatched", reason_code="individual_code" if person else "no_match",
        traveller_id=person.id if person else None, evidence={})


@pytest.mark.asyncio
async def test_preview_keysets_scope_and_independent_status_counts(db_session, test_settings):
    user, client, group, person = await context(db_session)
    db_session.add_all([match(client, group, person) for _ in range(27)] + [match(client, group)])
    await db_session.flush()
    first = await matching_preview(client.id, group.id, cursor=None, page_size=25, status="all",
        user=user, session=db_session, settings=test_settings)
    second = await matching_preview(client.id, group.id, cursor=first.next_cursor, page_size=25, status="all",
        user=user, session=db_session, settings=test_settings)
    assert len(first.items) == 25 and len(second.items) == 3 and not second.next_cursor
    assert len({row.id for row in first.items + second.items}) == 28
    assert first.counts == {"provisional": 27, "unmatched": 1}
    assert first.expected_group_revision == 1 and first.processed_count == 0
    for cursor, status in ((first.next_cursor, "unmatched"), (first.next_cursor + "broken", "all")):
        with pytest.raises(HTTPException) as error:
            await matching_preview(client.id, group.id, cursor=cursor, page_size=25, status=status,
                user=user, session=db_session, settings=test_settings)
        assert error.value.status_code == 422
    other = await seed_user(db_session)
    with pytest.raises(EntityNotFoundError):
        await matching_preview(client.id, group.id, cursor=None, page_size=25, status="all",
            user=other, session=db_session, settings=test_settings)


@pytest.mark.asyncio
async def test_review_creates_only_pending_membership_and_rejects_stale_or_foreign_person(db_session):
    user, client, group, person = await context(db_session)
    crypto = _crypto()
    now = datetime.now(UTC)
    await _seed_sources(db_session, group, 1, now)
    job = await enqueue_reconciliation(db_session, agency_id=user.agency_id, company_id=client.id,
        group_id=group.id, idempotency_key="review", now=now)
    await reconcile_page(db_session, job_id=job.id, crypto=crypto)
    case = await db_session.scalar(select(TravellerMatchCaseModel).where(TravellerMatchCaseModel.group_id == group.id))
    args = dict(agency_id=client.agency_id, company_id=client.id, group_id=group.id, case_id=case.id,
        traveller_id=person.id, expected_revision=case.revision, expected_group_revision=1,
        actor_id=user.id, reason="Original roster evidence checked with the company.", crypto=crypto)
    with pytest.raises(ConflictError):
        await resolve_match(db_session, **{**args, "expected_group_revision": 2})
    _, _, _, foreign_person = await context(db_session)
    with pytest.raises(EntityNotFoundError):
        await resolve_match(db_session, **{**args, "traveller_id": foreign_person.id})
    participation = await resolve_match(db_session, **args)
    assert participation.status == "pending" and participation.document_revision_id is None
    assert participation.confirmations == {} and participation.source_submission_id is None
    assert person.reuse_permission_status != "granted"
    assert case.status == "resolved" and case.revision == 2
    with pytest.raises(ConflictError):
        await resolve_match(db_session, **args)
    assert await db_session.scalar(select(func.count()).select_from(TravellerParticipationModel)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["fields", "revision", "identifier", "removed", "replacement"])
async def test_match_resolution_rejects_stale_source_or_rules_and_refreshes_unresolved_preview(db_session, mutation):
    user, client, group, person = await context(db_session)
    crypto, now = _crypto(), datetime.now(UTC)
    ids = await _seed_sources(db_session, group, 1, now)
    config = TravellerGroupReuseConfigModel(agency_id=user.agency_id, company_id=client.id,
        group_id=group.id, individual_identifier_type="employee")
    db_session.add(config)
    await db_session.flush()
    job = await enqueue_reconciliation(db_session, agency_id=user.agency_id, company_id=client.id,
        group_id=group.id, idempotency_key="before", now=now)
    await reconcile_page(db_session, job_id=job.id, crypto=crypto)
    case = await db_session.scalar(select(TravellerMatchCaseModel).where(TravellerMatchCaseModel.group_id == group.id))
    source = await db_session.get(PassportSubmissionModel, ids[0])
    if mutation == "fields":
        source.confirmed_fields = {**source.confirmed_fields, "passport_number": "DIFFERENT"}
    elif mutation == "revision":
        source.extraction_revision += 1
    elif mutation == "identifier":
        config.individual_identifier_type = "booking_reference"
    elif mutation == "removed":
        await db_session.delete(source)
    else:
        case.reason_code = "authorized_replacement_candidate"
    await db_session.flush()
    args = dict(agency_id=client.agency_id, company_id=client.id, group_id=group.id, case_id=case.id,
        traveller_id=person.id, expected_revision=case.revision, expected_group_revision=1,
        actor_id=user.id, reason="Original roster evidence checked with the company.", crypto=crypto)
    with pytest.raises(ConflictError):
        await resolve_match(db_session, **args)
    assert await db_session.scalar(select(func.count()).select_from(TravellerParticipationModel)) == 0
    if mutation not in {"removed", "replacement"}:
        job = await enqueue_reconciliation(db_session, agency_id=user.agency_id, company_id=client.id,
            group_id=group.id, idempotency_key="after", now=now)
        await reconcile_page(db_session, job_id=job.id, crypto=crypto)
        assert case.revision == 2
        participation = await resolve_match(db_session, **{**args, "expected_revision": 2})
        assert participation.status == "pending"


@pytest.mark.asyncio
async def test_metrics_separate_recognition_acceptance_and_reuse_of_reviewed_roster(db_session):
    user, client, group, person = await context(db_session)
    group.travel_date = date(2030, 5, 1)
    prior = ClientGroupModel(agency_id=user.agency_id, company_id=client.id, company_revision=1,
        token=uuid.uuid4().hex, name="Earlier trip", travel_date=date(2029, 1, 1), status="closed")
    db_session.add(prior)
    await db_session.flush()
    current = TravellerParticipationModel(agency_id=user.agency_id, company_id=client.id, group_id=group.id,
        traveller_id=person.id, source_kind="reviewed_roster", status="submitted", profile_revision=1,
        contact_revision=1, question_version="test", confirmations={"information_confirmed": True, "completion_key": "synthetic"},
        idempotency_key="current", trip_started_at=datetime(2030, 5, 1, tzinfo=UTC))
    db_session.add_all([current, TravellerParticipationModel(agency_id=user.agency_id, company_id=client.id,
        group_id=prior.id, traveller_id=person.id, source_kind="accepted_submission", status="accepted",
        profile_revision=1, contact_revision=1, question_version="test", idempotency_key="prior",
        trip_started_at=datetime(2029, 1, 1, tzinfo=UTC), created_at=datetime.now(UTC) + timedelta(days=1))])
    await db_session.flush()
    counts = await group_traveller_counts(db_session, user=user, agency_id=user.agency_id,
        company_id=client.id, group_ids=[group.id])
    assert counts[group.id].returning_travellers == 1  # actual trip date, never import timestamp
    assert counts[group.id].trip_participations == counts[group.id].reuse_completed == 0
    current.status = "accepted"
    await db_session.flush()
    counts = await group_traveller_counts(db_session, user=user, agency_id=user.agency_id,
        company_id=client.id, group_ids=[group.id])
    assert counts[group.id].returning_travellers == counts[group.id].trip_participations == counts[group.id].reuse_completed == 1
