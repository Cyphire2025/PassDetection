"""Synthetic people remain separate from phone-level delivery consolidation."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import event, func, insert, select

from app.application.travellers.reconciliation import enqueue_reconciliation, reconcile_page
from app.core.config.traveller_reuse import TravellerReuseSettings
from app.infrastructure.database.gc_mobile_models import ClientOrganizationModel
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    PassportSubmissionModel,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerGroupReuseConfigModel,
    TravellerIdentifierModel,
    TravellerMatchCaseModel,
    TravellerParticipationModel,
    TravellerPassportModel,
    TravellerProfileModel,
)
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto


def _crypto():
    return TravellerReuseCrypto(TravellerReuseSettings(lookup_key="test-lookup-" * 4,
        encryption_key=Fernet.generate_key().decode(), key_version="synthetic-v1"))


async def _seed_scope(session):
    agency = AgencyModel(name="Synthetic", email=f"{uuid.uuid4()}@example.invalid")
    session.add(agency)
    await session.flush()
    company = ClientOrganizationModel(agency_id=agency.id, name="Company", normalized_name="company")
    session.add(company)
    await session.flush()
    group = ClientGroupModel(agency_id=agency.id, company_id=company.id, company_revision=1,
        token=uuid.uuid4().hex, name="Synthetic trip", travel_date=date(2030, 1, 1))
    session.add(group)
    await session.flush()
    return agency, company, group


async def _seed_sources(session, group, count, now):
    ids = [uuid.uuid4() for _ in range(count)]
    await session.execute(insert(PassportSubmissionModel), [dict(id=identity,
        agency_id=group.agency_id, group_id=group.id, client_name=f"Person {index}",
        client_phone="+919999999999", image_s3_key="synthetic-only", status="staff_approved",
        confirmed_fields={"passport_number": f"00{index:07d}", "issuing_country": "IND",
                          "document_type": "PASSPORT"},
        staff_metadata={"employee": f"00{index:07d}"}, created_at=now - timedelta(minutes=1))
        for index, identity in enumerate(ids)])
    return ids


async def _seed_people(session, group, count, crypto):
    people = [TravellerProfileModel(id=uuid.uuid4(), agency_id=group.agency_id,
        company_id=group.company_id, status="active") for _ in range(count)]
    session.add_all(people)
    await session.flush()
    session.add_all([TravellerPassportModel(agency_id=group.agency_id, company_id=group.company_id,
        traveller_id=person.id, issuing_country="IND", document_type="PASSPORT",
        number_fingerprint=crypto.passport_fingerprint(group.agency_id, group.company_id,
            f"00{index:07d}", "IND", "PASSPORT"), fingerprint_key_version=crypto.key_version,
        number_ciphertext=crypto.encrypt(f"00{index:07d}"), status="accepted")
        for index, person in enumerate(people)])
    await session.flush()
    return people


@pytest.mark.asyncio
async def test_700_people_with_shared_phone_yield_400_provisional_and_300_unmatched(db_session):
    _, _, group = await _seed_scope(db_session)
    now, crypto = datetime.now(UTC), _crypto()
    await _seed_sources(db_session, group, 700, now)
    await _seed_people(db_session, group, 400, crypto)
    job = await enqueue_reconciliation(db_session, agency_id=group.agency_id,
        company_id=group.company_id, group_id=group.id, idempotency_key="700-person-import", now=now)
    query_counts = []
    for _ in range(7):
        statements = []
        def capture(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)
        engine = db_session.bind.sync_engine
        event.listen(engine, "before_cursor_execute", capture)
        try:
            result = await reconcile_page(db_session, job_id=job.id, crypto=crypto)
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        query_counts.append(len(statements))
        assert result.processed == 100
    assert result.status == "succeeded" and result.total_processed == 700
    counts = dict((await db_session.execute(select(TravellerMatchCaseModel.status,
        func.count()).group_by(TravellerMatchCaseModel.status))).all())
    assert counts == {"provisional": 400, "unmatched": 300}
    assert max(query_counts) <= 8
    assert await db_session.scalar(select(func.count()).select_from(TravellerParticipationModel)) == 0
    assert await db_session.scalar(select(func.count()).select_from(TravellerProfileModel).where(
        TravellerProfileModel.reuse_permission_status == "granted")) == 0
    assert (await reconcile_page(db_session, job_id=job.id, crypto=crypto)).processed == 0
    second = await enqueue_reconciliation(db_session, agency_id=group.agency_id,
        company_id=group.company_id, group_id=group.id, idempotency_key="700-person-import", now=now)
    assert second.id == job.id


@pytest.mark.asyncio
async def test_unknown_issuer_ai_fields_and_contradictory_codes_never_merge(db_session):
    _, _, group = await _seed_scope(db_session)
    now, crypto = datetime.now(UTC), _crypto()
    ids = await _seed_sources(db_session, group, 3, now)
    people = await _seed_people(db_session, group, 3, crypto)
    first = await db_session.get(PassportSubmissionModel, ids[0])
    first.confirmed_fields = {"passport_number": "000000000", "nationality": "IND", "document_type": "PASSPORT"}
    second = await db_session.get(PassportSubmissionModel, ids[1])
    second.status = "ai_approved"
    db_session.add(TravellerGroupReuseConfigModel(agency_id=group.agency_id, company_id=group.company_id,
        group_id=group.id, individual_identifier_type="employee"))
    db_session.add(TravellerIdentifierModel(agency_id=group.agency_id, company_id=group.company_id,
        traveller_id=people[0].id, identifier_type="employee", value_ciphertext=crypto.encrypt("000000002"),
        value_fingerprint=crypto.scoped_digest("identifier", group.agency_id, group.company_id, "employee", "000000002"),
        fingerprint_key_version=crypto.key_version, is_individual=True))
    await db_session.flush()
    job = await enqueue_reconciliation(db_session, agency_id=group.agency_id, company_id=group.company_id,
        group_id=group.id, idempotency_key="conflicts", now=now)
    await reconcile_page(db_session, job_id=job.id, crypto=crypto)
    statuses = dict((await db_session.execute(select(TravellerMatchCaseModel.source_row_key,
        TravellerMatchCaseModel.status))).all())
    assert statuses == {str(ids[0]): "unmatched", str(ids[1]): "unmatched", str(ids[2]): "conflicting"}


@pytest.mark.asyncio
async def test_page_rollback_restarts_without_lost_records_or_duplicate_cases(db_session):
    _, _, group = await _seed_scope(db_session)
    now, crypto = datetime.now(UTC), _crypto()
    await _seed_sources(db_session, group, 3, now)
    await _seed_people(db_session, group, 3, crypto)
    job = await enqueue_reconciliation(db_session, agency_id=group.agency_id, company_id=group.company_id,
        group_id=group.id, idempotency_key="retry", now=now)
    job_id = job.id
    with pytest.raises(RuntimeError, match="synthetic crash"):
        async with db_session.begin_nested():
            await reconcile_page(db_session, job_id=job_id, crypto=crypto, page_size=2)
            raise RuntimeError("synthetic crash")
    result = await reconcile_page(db_session, job_id=job_id, crypto=crypto, page_size=2)
    assert result.processed == 2 and result.total_processed == 2
    result = await reconcile_page(db_session, job_id=job_id, crypto=crypto, page_size=2)
    assert result.status == "succeeded" and result.total_processed == 3
    assert await db_session.scalar(select(func.count()).select_from(TravellerMatchCaseModel)) == 3


@pytest.mark.asyncio
async def test_reassignment_cancels_pending_scan_without_rewriting_source_company(db_session):
    agency, _, group = await _seed_scope(db_session)
    now, crypto = datetime.now(UTC), _crypto()
    await _seed_sources(db_session, group, 1, now)
    job = await enqueue_reconciliation(db_session, agency_id=group.agency_id, company_id=group.company_id,
        group_id=group.id, idempotency_key="reassign", now=now)
    company = ClientOrganizationModel(agency_id=agency.id, name="Target", normalized_name="target")
    db_session.add(company)
    await db_session.flush()
    group.company_id, group.company_revision = company.id, 2
    await db_session.flush()
    result = await reconcile_page(db_session, job_id=job.id, crypto=crypto)
    assert result.status == "cancelled" and result.processed == 0
    assert job.company_id != group.company_id
