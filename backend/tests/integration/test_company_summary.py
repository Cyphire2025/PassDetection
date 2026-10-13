"""Record totals, identity completeness and retained-history scope are distinct."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import event

from app.application.companies.traveller_metrics import group_traveller_counts
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES, GroupStatus
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastRejectedContactModel,
    WhatsAppBroadcastSourceContactModel,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerMatchCaseModel,
    TravellerParticipationModel,
    TravellerProfileModel,
    TravellerReconciliationJobModel,
)
from app.presentation.api.v1.routes.companies import company_summary
from tests.integration.test_company_directory import company, legacy_group, seed_user


async def assigned_group(session, user, item, status=GroupStatus.ACTIVE):
    group = await legacy_group(session, user, status)
    row = await session.get(ClientGroupModel, group.id)
    row.company_id, row.company_revision = item.id, 1
    await session.flush()
    return row


async def person(session, group, *, deleted=False, permission="granted"):
    value = TravellerProfileModel(agency_id=group.agency_id, company_id=group.company_id,
        status="deleted" if deleted else "active", reuse_permission_status=permission,
        deleted_at=datetime.now(UTC) if deleted else None)
    session.add(value)
    await session.flush()
    return value


async def membership(session, group, profile, *, status="accepted", source=None):
    value = TravellerParticipationModel(agency_id=group.agency_id, company_id=group.company_id,
        group_id=group.id, traveller_id=profile.id, source_kind="accepted_submission" if source else "reviewed_roster",
        source_submission_id=source.id if source else None, source_row_key=str(source.id) if source else None,
        profile_revision=1, contact_revision=1, question_version="test", status=status,
        idempotency_key=f"summary:{profile.id}")
    session.add(value)
    await session.flush()
    return value


async def submission(session, group, status="staff_approved"):
    value = PassportSubmissionModel(agency_id=group.agency_id, group_id=group.id,
        client_name="Synthetic person", image_s3_key="synthetic.png", status=status)
    session.add(value)
    await session.flush()
    return value


async def roster(session, group):
    broadcast = WhatsAppBroadcastGroupModel(agency_id=group.agency_id, name="Synthetic roster")
    session.add(broadcast)
    await session.flush()
    session.add(ClientGroupWhatsAppBroadcastLinkModel(agency_id=group.agency_id,
        client_group_id=group.id, broadcast_group_id=broadcast.id))
    recipient = WhatsAppBroadcastRecipientModel(agency_id=group.agency_id,
        broadcast_group_id=broadcast.id, phone_number="+919999999999", normalized_phone_number="+919999999999")
    session.add(recipient)
    await session.flush()
    return broadcast, recipient


@pytest.mark.asyncio
async def test_collected_population_all_visible_statuses_groups_and_tenants(db_session):
    user, other = await seed_user(db_session), await seed_user(db_session)
    item, unrelated, foreign = await company(db_session, user), await company(db_session, user, "Unrelated"), await company(db_session, other)
    active = await assigned_group(db_session, user, item)
    for status in OFFICE_VISIBLE_PASSPORT_STATUS_VALUES:
        await submission(db_session, active, status)
    for status in ("uploaded", "processing", "ready_for_client_review", "failed"):
        await submission(db_session, active, status)
    for status in (GroupStatus.CLOSED, GroupStatus.ARCHIVED):
        await submission(db_session, await assigned_group(db_session, user, item, status))
    for owner, client, state in ((user, item, GroupStatus.DELETED),
        (user, unrelated, GroupStatus.ACTIVE), (other, foreign, GroupStatus.ACTIVE)):
        ignored = await assigned_group(db_session, owner, client, state)
        await submission(db_session, ignored)
        await roster(db_session, ignored)
    result = await company_summary(item.id, user=user, session=db_session, agency_id=None)
    assert result.collected_records == result.unresolved_historical_records == 8
    assert result.unique_travellers == result.trip_participations == 0
    assert result.total_groups == 3 and result.identity_totals_partial


@pytest.mark.asyncio
async def test_distinct_people_accepted_trips_delete_and_reuse_withdrawal(db_session):
    user = await seed_user(db_session)
    item = await company(db_session, user)
    first, second = await assigned_group(db_session, user, item), await assigned_group(db_session, user, item, GroupStatus.ARCHIVED)
    kept, deleted = await person(db_session, first, permission="withdrawn"), await person(db_session, first, deleted=True)
    for group in (first, second):
        await membership(db_session, group, kept, source=await submission(db_session, group))
    await membership(db_session, first, deleted, source=await submission(db_session, first))
    result = await company_summary(item.id, user=user, session=db_session, agency_id=None)
    assert (result.collected_records, result.unique_travellers, result.trip_participations) == (3, 1, 2)
    assert result.unresolved_historical_records == 1 and result.identity_totals_partial
    counts = await group_traveller_counts(db_session, user=user, agency_id=item.agency_id,
        company_id=item.id, group_ids=[first.id, second.id])
    assert counts[first.id].trip_participations == counts[second.id].trip_participations == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "submitted"])
async def test_pending_membership_without_submission_keeps_totals_partial(db_session, status):
    user = await seed_user(db_session)
    item = await company(db_session, user)
    group = await assigned_group(db_session, user, item)
    await membership(db_session, group, await person(db_session, group), status=status)
    result = await company_summary(item.id, user=user, session=db_session, agency_id=None)
    assert result.collected_records == result.unresolved_historical_records == 0
    assert result.unique_travellers == result.trip_participations == 0
    assert result.identity_totals_partial


@pytest.mark.asyncio
async def test_700_shared_phone_sources_count_before_and_after_completed_matching(db_session):
    user = await seed_user(db_session)
    item = await company(db_session, user)
    group = await assigned_group(db_session, user, item)
    broadcast, recipient = await roster(db_session, group)
    for start in range(1, 700, 350):
        db_session.add_all([WhatsAppBroadcastRejectedContactModel(agency_id=group.agency_id,
            broadcast_group_id=broadcast.id, source_file_name="synthetic.xlsx", sheet_name="People",
            row_number=index + 1, raw_name=f"Person {index}", raw_phone_number="+919999999999",
            reason_code="duplicate_phone", reason="Shared phone", fingerprint=f"{index:064x}")
            for index in range(start, min(start + 350, 700))])
        await db_session.flush()
    queries = []
    connection = db_session.bind.sync_engine
    def count_sql(_connection, _cursor, statement, _parameters, _context, _many):
        queries.append(statement)
    event.listen(connection, "before_cursor_execute", count_sql)
    try:
        result = await company_summary(item.id, user=user, session=db_session, agency_id=None)
    finally:
        event.remove(connection, "before_cursor_execute", count_sql)
    assert result.collected_records == result.unique_travellers == result.trip_participations == 0
    assert result.unresolved_historical_records == 700 and result.identity_totals_partial
    assert len(queries) == 5  # Authorization plus four constant-sized aggregates.
    profile = await person(db_session, group)
    pending = await membership(db_session, group, profile, status="pending")
    db_session.add_all([
        TravellerMatchCaseModel(agency_id=group.agency_id, company_id=item.id, group_id=group.id,
            source_kind="whatsapp_recipient", source_row_key=str(recipient.id), traveller_id=profile.id,
            status="resolved", reason_code="staff_reviewed"),
        TravellerReconciliationJobModel(agency_id=group.agency_id, company_id=item.id, group_id=group.id,
            expected_group_revision=1, idempotency_key="complete", status="succeeded", processed_count=700,
            available_at=datetime.now(UTC)),
    ])
    await db_session.flush()
    result = await company_summary(item.id, user=user, session=db_session, agency_id=None)
    assert result.unresolved_historical_records == 700 and result.identity_totals_partial
    pending.status = "accepted"
    await db_session.flush()
    result = await company_summary(item.id, user=user, session=db_session, agency_id=None)
    assert result.unresolved_historical_records == 699 and result.identity_totals_partial
    assert result.unique_travellers == result.trip_participations == 1


@pytest.mark.asyncio
async def test_source_managed_broadcast_does_not_duplicate_collected_record(db_session):
    user = await seed_user(db_session)
    item = await company(db_session, user)
    group = await assigned_group(db_session, user, item)
    source = await submission(db_session, group)
    broadcast, recipient = await roster(db_session, group)
    recipient.is_source_managed = True
    db_session.add(WhatsAppBroadcastSourceContactModel(agency_id=group.agency_id, broadcast_group_id=broadcast.id,
        source_group_id=group.id, source_submission_id=source.id, recipient_id=recipient.id, name="Synthetic person"))
    await membership(db_session, group, await person(db_session, group), source=source)
    await db_session.flush()
    result = await company_summary(item.id, user=user, session=db_session, agency_id=None)
    assert result.collected_records == result.unique_travellers == result.trip_participations == 1
    assert result.unresolved_historical_records == 0 and not result.identity_totals_partial


@pytest.mark.asyncio
async def test_unresolved_cases_keep_completed_job_partial_without_inventing_people(db_session):
    user = await seed_user(db_session)
    item = await company(db_session, user)
    group = await assigned_group(db_session, user, item)
    source = await submission(db_session, group)
    await membership(db_session, group, await person(db_session, group), source=source)
    db_session.add(TravellerMatchCaseModel(agency_id=group.agency_id, company_id=item.id, group_id=group.id,
        source_kind="passport_submission", source_row_key=str(source.id), status="conflicting", reason_code="identity_conflict"))
    await db_session.flush()
    result = await company_summary(item.id, user=user, session=db_session, agency_id=None)
    assert result.collected_records == result.unique_travellers == result.trip_participations == 1
    assert result.unresolved_historical_records == 0 and result.identity_totals_partial
