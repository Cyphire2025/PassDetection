"""Late history retries early roster results without depending on another edit."""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select

from app.application.travellers.historical_registration import register_historical_source
from app.application.travellers.history_schedule import schedule_group_history
from app.application.travellers.reconciliation import reconcile_page
from app.infrastructure.database.models import (
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportSubmissionModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentAssetModel,
    TravellerMatchCaseModel,
    TravellerParticipationModel,
    TravellerProfileModel,
    TravellerReusePolicyModel,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerReconciliationJobModel as Job,
)
from tests.unit.application.test_incremental_company_history import targets
from tests.unit.application.test_traveller_enrollment import _fixture, _source
from tests.unit.application.test_traveller_legacy_approval import approve_legacy


@pytest.mark.asyncio
@pytest.mark.parametrize("private_first", [False, True])
@pytest.mark.parametrize("legacy_ai_approval", [False, True])
async def test_group_history_retries_completed_roster_and_assigns_without_public_confirmation(
    db_session, private_first, legacy_ai_approval,
):
    db_session.autoflush = False  # Match production session behavior.
    ctx = await _fixture(db_session)
    ctx.source.confirmed_fields = {**ctx.source.confirmed_fields, "nationality": "IND"}
    if legacy_ai_approval:
        approve_legacy(ctx.source)
    policy = await db_session.get(TravellerReusePolicyModel, ctx.group.company_id)
    policy.configured_by_user_id = ctx.request.actor_id
    target = (await targets(db_session, ctx, 1))[0]
    target.travel_date = date(2027, 1, 1)
    link = await db_session.scalar(select(ClientGroupWhatsAppBroadcastLinkModel).where(
        ClientGroupWhatsAppBroadcastLinkModel.client_group_id == target.id))
    recipient = WhatsAppBroadcastRecipientModel(agency_id=target.agency_id,
        broadcast_group_id=link.broadcast_group_id, name=ctx.source.client_name,
        phone_number=ctx.source.client_phone, normalized_phone_number="919999999999",
        imported_fields={"passport_number": "001234567", "date_of_birth": "1990-01-01 00:00:00"})
    db_session.add(recipient)
    await db_session.flush()
    if private_first:
        await register_historical_source(db_session, group=ctx.group, source_id=ctx.source.id,
            policy=None, crypto=ctx.crypto, now=datetime.now(UTC))

    # The target is linked and checked before the historical group is indexed.
    await schedule_group_history(db_session, group=target, trigger="first-link")
    early = await db_session.scalar(select(Job).where(Job.group_id == target.id))
    assert (await reconcile_page(db_session, job_id=early.id, crypto=ctx.crypto)).status == "succeeded"
    await db_session.flush()
    case = await db_session.scalar(select(TravellerMatchCaseModel).where(
        TravellerMatchCaseModel.group_id == target.id))
    assert (case.status, case.reason_code) == (
        ("provisional", "unavailable") if private_first else ("unmatched", "no_exact_name_candidate"))
    assert await db_session.scalar(select(func.count()).select_from(TravellerProfileModel)) == int(private_first)

    # A later bulk/group history page must revisit the early result by itself.
    await schedule_group_history(db_session, group=ctx.group, trigger="assign-history")
    history = await db_session.scalar(select(Job).where(Job.group_id == ctx.group.id))
    assert (await reconcile_page(db_session, job_id=history.id, crypto=ctx.crypto)).status == "succeeded"
    await db_session.flush()
    fanout = await db_session.scalar(select(Job).where(Job.idempotency_key.startswith("company-fanout:")))
    assert fanout is not None and fanout.status == "queued"
    assert (await reconcile_page(db_session, job_id=fanout.id, crypto=ctx.crypto)).status == "succeeded"
    await db_session.flush()
    roster = await db_session.scalar(select(Job).where(Job.idempotency_key.startswith("company-roster:")))

    # Retained document copies remain a publication prerequisite.
    assert (await reconcile_page(db_session, job_id=roster.id, crypto=ctx.crypto)).status == "queued"
    for asset in await db_session.scalars(select(TravellerDocumentAssetModel)):
        asset.availability, asset.byte_size, asset.content_type = "available", 32, "image/jpeg"
    await db_session.flush()
    assert (await reconcile_page(db_session, job_id=roster.id, crypto=ctx.crypto)).status == "succeeded"
    await db_session.flush()
    member = await db_session.scalar(select(TravellerParticipationModel).where(
        TravellerParticipationModel.group_id == target.id))
    assert member.status == "accepted" and member.confirmations["information_confirmed"] is False
    generated = await db_session.get(PassportSubmissionModel, member.source_submission_id)
    assert generated.status == "confirmed" and generated.client_reviewed_at is None
    assert case.status == "resolved"
    assert await db_session.scalar(select(func.count()).select_from(TravellerProfileModel)) == 1
    assert fanout.status == "succeeded"  # Roster-only work cannot recursively fan out.
    assert await db_session.scalar(select(func.count()).select_from(Job)) == 4
    assert (await reconcile_page(db_session, job_id=roster.id, crypto=ctx.crypto)).processed == 0
    assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel).where(
        PassportSubmissionModel.group_id == target.id)) == 1


@pytest.mark.asyncio
async def test_every_productive_history_page_requeues_the_same_bounded_fanout(db_session):
    ctx = await _fixture(db_session)
    policy = await db_session.get(TravellerReusePolicyModel, ctx.group.company_id)
    policy.configured_by_user_id = ctx.request.actor_id
    await targets(db_session, ctx, 1)
    for index in range(25):
        source = _source(ctx.group, number=f"B{index:08}")
        source.client_name = f"Synthetic Person {index}"
        db_session.add(source)
    await db_session.flush()
    await schedule_group_history(db_session, group=ctx.group, trigger="large-group")
    history = await db_session.scalar(select(Job))
    first = await reconcile_page(db_session, job_id=history.id, crypto=ctx.crypto)
    assert first.processed == 25 and first.status == "queued"
    fanout = await db_session.scalar(select(Job).where(Job.idempotency_key.startswith("company-fanout:")))
    assert (await reconcile_page(db_session, job_id=fanout.id, crypto=ctx.crypto)).status == "succeeded"
    final = await reconcile_page(db_session, job_id=history.id, crypto=ctx.crypto)
    assert final.processed == 1 and final.status == "succeeded"
    assert fanout.status == "queued"
    assert await db_session.scalar(select(func.count()).select_from(Job).where(
        Job.idempotency_key.startswith("company-fanout:"))) == 1
