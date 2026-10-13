"""Two-pass chains checkpoint sources and restart after completion boundaries."""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.application.travellers.company_history_jobs import advance_company_history_chain, enqueue_company_history
from app.application.travellers.reconciliation import reconcile_page
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentAssetModel,
    TravellerMatchCaseModel,
    TravellerParticipationModel,
    TravellerReconciliationJobModel,
    TravellerReusePolicyModel,
)
from tests.unit.application.test_traveller_enrollment import _fixture


@pytest.mark.asyncio
async def test_chain_registers_all_groups_then_matches_and_resumes_pending_assets(db_session):
    ctx = await _fixture(db_session)
    policy = await db_session.get(TravellerReusePolicyModel, ctx.group.company_id)
    policy.configured_by_user_id = ctx.request.actor_id
    ctx.source.confirmed_fields = {**ctx.source.confirmed_fields, "nationality": "IND", "date_of_expiry": "2036-01-01"}
    target = ClientGroupModel(agency_id=ctx.group.agency_id, company_id=ctx.group.company_id, company_revision=1,
        token=uuid.uuid4().hex, name="Next journey", travel_date=date.today() + timedelta(days=30))
    broadcast = WhatsAppBroadcastGroupModel(agency_id=ctx.group.agency_id, name="Roster")
    db_session.add_all([target, broadcast])
    await db_session.flush()
    recipient = WhatsAppBroadcastRecipientModel(agency_id=ctx.group.agency_id, broadcast_group_id=broadcast.id,
        name=ctx.source.client_name, phone_number=ctx.source.client_phone, normalized_phone_number=ctx.source.client_phone,
        imported_fields={"passport_number": "001234567", "date_of_birth": "1990-01-01"})
    db_session.add_all([recipient, ClientGroupWhatsAppBroadcastLinkModel(agency_id=ctx.group.agency_id,
        client_group_id=target.id, broadcast_group_id=broadcast.id, matching_field_keys=["name"])])
    await db_session.flush()
    first = min((ctx.group, target), key=lambda group: group.id)
    await enqueue_company_history(db_session, group=first, policy=policy, trigger="restart-proof")
    waited = False
    for _ in range(15):
        await advance_company_history_chain(db_session)
        job = await db_session.scalar(select(TravellerReconciliationJobModel).where(
            TravellerReconciliationJobModel.status == "queued").order_by(TravellerReconciliationJobModel.id).limit(1))
        if job is None:
            break
        result = await reconcile_page(db_session, job_id=job.id, crypto=ctx.crypto)
        if job.idempotency_key.startswith("company-history:m:") and job.group_id == target.id and result.status == "queued":
            waited = True
            assert result.processed == 0
            assert await db_session.scalar(select(func.count()).select_from(TravellerParticipationModel).where(
                TravellerParticipationModel.group_id == target.id)) == 0
            for asset in (await db_session.scalars(select(TravellerDocumentAssetModel))).all():
                asset.availability, asset.content_type, asset.byte_size = "available", "image/jpeg", 10
            await db_session.flush()
    assert waited
    member = await db_session.scalar(select(TravellerParticipationModel).where(TravellerParticipationModel.group_id == target.id))
    assert member is not None and member.status == "accepted"
    assert member.confirmations["information_confirmed"] is False
    case = await db_session.scalar(select(TravellerMatchCaseModel).where(TravellerMatchCaseModel.source_row_key == str(recipient.id)))
    assert case.status == "resolved" and case.reason_code == "automatic_group_assignment"
    assert not await advance_company_history_chain(db_session)
    jobs = (await db_session.scalars(select(TravellerReconciliationJobModel))).all()
    assert len(jobs) == 4 and all(job.status == "succeeded" for job in jobs)


@pytest.mark.asyncio
async def test_changed_policy_cancels_old_chain_without_registering_sources(db_session):
    ctx = await _fixture(db_session)
    policy = await db_session.get(TravellerReusePolicyModel, ctx.group.company_id)
    policy.configured_by_user_id = ctx.request.actor_id
    job = await enqueue_company_history(db_session, group=ctx.group, policy=policy, trigger="old-policy")
    policy.revision += 1
    await db_session.flush()
    result = await reconcile_page(db_session, job_id=job.id, crypto=ctx.crypto, now=datetime.now(UTC))
    assert result.status == "cancelled"
    assert await db_session.scalar(select(func.count()).select_from(TravellerMatchCaseModel)) == 0
