"""Trip snapshots retain exact ownership without reactivating future reuse."""

import uuid
from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.travellers.enrollment import enroll_submission
from app.application.travellers.export_authority import can_export_snapshot_assets
from app.application.travellers.retention import deletable_storage_keys, revoke_retained_profile
from app.application.travellers.snapshot_access import (
    can_read_snapshot_asset,
    sync_accepted_participations,
)
from app.application.use_cases.passports.prepare_image_export import (
    ImagePreparationError,
    PreparedImageExport,
)
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentAssetModel,
    TravellerDocumentRevisionModel,
    TravellerParticipationModel,
    TravellerProfileModel,
)
from app.infrastructure.travellers.runtime import stage_withdrawn_asset_deletions
from tests.unit.application.test_traveller_enrollment import _fixture


async def snapshot(session):
    ctx = await _fixture(session)
    enrolled = await enroll_submission(session, ctx.request, ctx.crypto)
    asset = await session.scalar(select(TravellerDocumentAssetModel).where(TravellerDocumentAssetModel.document_side == "front"))
    asset.availability, asset.byte_size, asset.content_type = "available", 1234, "image/jpeg"
    group = ClientGroupModel(agency_id=ctx.request.agency_id, company_id=ctx.request.company_id,
        company_revision=1, token=uuid.uuid4().hex, name="Current trip")
    session.add(group)
    await session.flush()
    source = PassportSubmissionModel(agency_id=group.agency_id, group_id=group.id, client_name="Snapshot",
        image_s3_key=asset.object_key, status="client_submitted", extraction_revision=3)
    session.add(source)
    await session.flush()
    participation = TravellerParticipationModel(agency_id=group.agency_id, company_id=group.company_id,
        group_id=group.id, traveller_id=enrolled.traveller_id, source_submission_id=source.id,
        source_kind="returning_reuse", passport_id=enrolled.passport_id, document_revision_id=enrolled.document_revision_id,
        profile_revision=1, contact_revision=1, status="submitted", question_version="synthetic", idempotency_key=uuid.uuid4().hex)
    session.add(participation)
    await session.flush()
    return ctx, enrolled, asset, group, source, participation


async def readable(session, asset, group, source):
    return await can_read_snapshot_asset(session, submission_id=source.id, group_id=group.id,
        agency_id=group.agency_id, storage_key=asset.object_key)


@pytest.mark.asyncio
async def test_withdrawal_preserves_current_trip_but_hard_delete_immediately_denies(db_session):
    ctx, enrolled, asset, group, source, _ = await snapshot(db_session)
    assert await readable(db_session, asset, group, source)
    assert await revoke_retained_profile(db_session, agency_id=group.agency_id, company_id=group.company_id,
        traveller_id=enrolled.traveller_id, expected_revision=1)
    assert await readable(db_session, asset, group, source)
    assert await deletable_storage_keys(db_session, [asset.object_key], agency_id=group.agency_id) == []
    person = await db_session.get(TravellerProfileModel, enrolled.traveller_id)
    person.status, person.deleted_at = "deleted", datetime.now(UTC)
    await db_session.flush()
    assert not await readable(db_session, asset, group, source)
    assert await deletable_storage_keys(db_session, [asset.object_key], agency_id=group.agency_id) == [asset.object_key]


@pytest.mark.asyncio
async def test_snapshot_cannot_read_other_source_group_or_purged_object(db_session):
    ctx, _, asset, group, source, _ = await snapshot(db_session)
    assert not await readable(db_session, asset, ctx.group, ctx.source)
    assert not await can_read_snapshot_asset(db_session, submission_id=source.id, group_id=group.id,
        agency_id=uuid.uuid4(), storage_key=asset.object_key)
    source.image_s3_key = "fresh/replacement.jpg"
    await db_session.flush()
    assert not await readable(db_session, asset, group, source)
    source.image_s3_key, asset.availability = asset.object_key, "purged"
    asset.purged_at = datetime.now(UTC)
    await db_session.flush()
    assert not await readable(db_session, asset, group, source)


@pytest.mark.asyncio
async def test_staff_acceptance_updates_trip_once_without_promoting_retained_evidence(db_session):
    _, enrolled, _, group, source, participation = await snapshot(db_session)
    await sync_accepted_participations(db_session, agency_id=group.agency_id, group_id=group.id, submission_ids=[source.id])
    assert participation.status == "submitted"
    source.status, source.extraction_revision = "staff_approved", 4
    await db_session.flush()
    await sync_accepted_participations(db_session, agency_id=group.agency_id, group_id=group.id, submission_ids=[source.id])
    assert participation.status == "accepted" and participation.revision == 2
    assert participation.confirmations["accepted_source_extraction_revision"] == 4
    await sync_accepted_participations(db_session, agency_id=group.agency_id, group_id=group.id, submission_ids=[source.id])
    assert participation.revision == 2 and participation.document_revision_id == enrolled.document_revision_id
    retained = await db_session.get(TravellerDocumentRevisionModel, enrolled.document_revision_id)
    assert retained.revision_number == 1


@pytest.mark.asyncio
async def test_withdrawal_worker_keeps_only_lawful_trip_assets(db_session):
    _, enrolled, asset, group, _, _ = await snapshot(db_session)
    asset_id = asset.id
    await revoke_retained_profile(db_session, agency_id=group.agency_id, company_id=group.company_id,
        traveller_id=enrolled.traveller_id, expected_revision=1)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    assert await stage_withdrawn_asset_deletions(session_factory=factory) == 1
    db_session.expire_all()
    assert (await db_session.get(TravellerDocumentAssetModel, asset_id)).availability == "available"


@pytest.mark.asyncio
async def test_export_rechecks_retained_asset_purge_before_publication(db_session):
    _, _, asset, group, source, _ = await snapshot(db_session)
    assert await can_export_snapshot_assets(db_session, agency_id=group.agency_id, group_id=group.id, sources=[source])
    asset.availability, asset.purged_at = "purged", datetime.now(UTC)
    await db_session.flush()
    assert not await can_export_snapshot_assets(db_session, agency_id=group.agency_id, group_id=group.id, sources=[source])
    output = BytesIO(b"synthetic archive")
    check = AsyncMock(side_effect=[True, False])
    prepared = PreparedImageExport([], {}, {}, "synthetic", check)
    exporter = SimpleNamespace(export_group=AsyncMock(return_value=(output, 1, 17)))
    with pytest.raises(ImagePreparationError, match="became unavailable"):
        await prepared.render(storage=SimpleNamespace(), exporter=exporter)
    assert output.closed and check.await_count == 2
