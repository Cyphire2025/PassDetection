"""Approved legacy photos become reusable trips without invented public consent."""

import json
from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.travellers.accepted_source import retained_source_is_current
from app.application.travellers.broadcast_history_schedule import (
    finish_broadcast_history_refresh,
    prepare_broadcast_history_refresh,
    require_current_broadcast_history_scope,
)
from app.application.travellers.history_schedule import schedule_group_history
from app.application.travellers.legacy_staff_acceptance import STAFF_ACCEPTANCE_RULE
from app.application.travellers.reconciliation import reconcile_page
from app.infrastructure.database.models import (
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportSubmissionModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerClaimModel,
    TravellerDocumentAssetModel,
    TravellerDocumentRevisionModel,
    TravellerHistoryGrantModel,
    TravellerMatchCaseModel,
    TravellerParticipationModel,
    TravellerPassportModel,
    TravellerProfileModel,
    TravellerReconciliationJobModel,
    TravellerReusePolicyModel,
)
from app.infrastructure.storage.minio_repository import ObjectIntegrityMetadata
from app.infrastructure.travellers import asset_copy
from tests.unit.application.test_company_history_registration import register
from tests.unit.application.test_incremental_company_history import targets
from tests.unit.application.test_traveller_enrollment import _fixture
from tests.unit.application.test_traveller_legacy_staff_approval import approve_staff_legacy


@pytest.mark.asyncio
async def test_current_staff_approval_copies_then_assigns_once_without_public_confirmation(
    db_session,
    monkeypatch,
):
    db_session.autoflush = False
    ctx = await _fixture(db_session)
    approve_staff_legacy(ctx.source, ctx.request.actor_id)
    original_fields = deepcopy(ctx.source.confirmed_fields)
    original_verification = deepcopy(ctx.source.post_submission_verification)
    policy = await db_session.get(TravellerReusePolicyModel, ctx.group.company_id)
    policy.configured_by_user_id = ctx.request.actor_id
    target = (await targets(db_session, ctx, 1))[0]
    target.travel_date = date(2027, 1, 1)
    link = await db_session.scalar(
        select(ClientGroupWhatsAppBroadcastLinkModel).where(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == target.id
        )
    )
    recipient = WhatsAppBroadcastRecipientModel(
        agency_id=target.agency_id,
        broadcast_group_id=link.broadcast_group_id,
        name=ctx.source.client_name,
        phone_number=ctx.source.client_phone,
        normalized_phone_number="919999999999",
        imported_fields={
            "passport_number": original_fields["passport_number"],
            "date_of_birth": "1990-01-01 00:00:00",
        },
    )
    db_session.add(recipient)
    await db_session.flush()

    await schedule_group_history(db_session, group=ctx.group, trigger="legacy-staff-approval")
    history = await db_session.scalar(
        select(TravellerReconciliationJobModel).where(
            TravellerReconciliationJobModel.group_id == ctx.group.id
        )
    )
    assert (
        await reconcile_page(db_session, job_id=history.id, crypto=ctx.crypto)
    ).status == "succeeded"
    document = await db_session.scalar(select(TravellerDocumentRevisionModel))
    passport = await db_session.scalar(select(TravellerPassportModel))
    assert document.source_provenance["acceptance_rule"] == STAFF_ACCEPTANCE_RULE
    assert passport.issuing_country == "UNK" and passport.document_type == "P"
    assert json.loads(ctx.crypto.decrypt(document.fields_ciphertext))["issuing_country"] == "UNK"
    assert ctx.source.confirmed_fields == original_fields
    assert ctx.source.post_submission_verification == original_verification
    assert retained_source_is_current(document, ctx.source, ctx.crypto)

    fanout = await db_session.scalar(
        select(TravellerReconciliationJobModel).where(
            TravellerReconciliationJobModel.idempotency_key.startswith("company-fanout:")
        )
    )
    assert (
        await reconcile_page(db_session, job_id=fanout.id, crypto=ctx.crypto)
    ).status == "succeeded"
    roster = await db_session.scalar(
        select(TravellerReconciliationJobModel).where(
            TravellerReconciliationJobModel.idempotency_key.startswith("company-roster:")
        )
    )
    assert (
        await reconcile_page(db_session, job_id=roster.id, crypto=ctx.crypto)
    ).status == "queued"
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(PassportSubmissionModel)
            .where(PassportSubmissionModel.group_id == target.id)
        )
        == 0
    )

    monkeypatch.setattr(
        asset_copy,
        "retained_source_is_current",
        lambda revision, source: retained_source_is_current(revision, source, ctx.crypto),
    )
    target_id, roster_id, broadcast_id = target.id, roster.id, link.broadcast_group_id
    person_id, document_id = document.traveller_id, document.id
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    storage = SimpleNamespace(
        stat_file=AsyncMock(return_value=ObjectIntegrityMetadata(4096, "a" * 64, "image/jpeg")),
        copy_file=AsyncMock(return_value="copied"),
    )
    assert await asset_copy.copy_next_asset(session_factory=factory, storage=storage)
    assert await asset_copy.copy_next_asset(session_factory=factory, storage=storage)
    assert not await asset_copy.copy_next_asset(session_factory=factory, storage=storage)
    assert storage.copy_file.await_count == 2
    for call in storage.copy_file.await_args_list:
        original, retained = call.args
        assert original != retained and retained.startswith("travellers/")

    db_session.expire_all()
    await db_session.refresh(ctx.group)
    await db_session.refresh(ctx.source)
    assets = list(await db_session.scalars(select(TravellerDocumentAssetModel)))
    assert len(assets) == 2 and all(asset.availability == "available" for asset in assets)
    assert (
        await reconcile_page(db_session, job_id=roster_id, crypto=ctx.crypto)
    ).status == "succeeded"
    member = await db_session.scalar(
        select(TravellerParticipationModel).where(TravellerParticipationModel.group_id == target_id)
    )
    assert member.traveller_id == person_id and member.document_revision_id == document_id
    assert member.status == "accepted"
    assert member.confirmations["information_confirmed"] is False
    assert member.confirmations["assignment_mode"] == "automatic"
    generated = await db_session.get(PassportSubmissionModel, member.source_submission_id)
    assert generated.status == "confirmed" and generated.client_reviewed_at is None
    assert generated.image_s3_key in {asset.object_key for asset in assets}
    case = await db_session.scalar(
        select(TravellerMatchCaseModel).where(TravellerMatchCaseModel.group_id == target_id)
    )
    assert case.status == "resolved" and case.reason_code == "automatic_group_assignment"

    # A completed history replay and a second broadcast refresh are idempotent.
    assert await register(db_session, ctx) == person_id
    refresh = await prepare_broadcast_history_refresh(
        db_session, agency_id=ctx.group.agency_id, broadcast_id=broadcast_id
    )
    await require_current_broadcast_history_scope(db_session, refresh)
    await finish_broadcast_history_refresh(db_session, refresh)
    assert refresh.jobs[0].id == roster_id
    assert (
        await reconcile_page(db_session, job_id=roster_id, crypto=ctx.crypto)
    ).status == "succeeded"
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(PassportSubmissionModel)
            .where(PassportSubmissionModel.group_id == target_id)
        )
        == 1
    )
    for model in (TravellerProfileModel, TravellerDocumentRevisionModel):
        assert await db_session.scalar(select(func.count()).select_from(model)) == 1
    assert (
        await db_session.scalar(select(func.count()).select_from(TravellerDocumentAssetModel)) == 2
    )
    for model in (TravellerClaimModel, TravellerHistoryGrantModel):
        assert await db_session.scalar(select(func.count()).select_from(model)) == 0
    person = await db_session.get(TravellerProfileModel, person_id)
    assert person.reuse_permission_status == "unknown"
    assert "consent" not in person.reuse_permission_evidence
