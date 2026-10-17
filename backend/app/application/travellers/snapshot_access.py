"""Current-trip ownership is separate from permission for future reuse.

Every retained-image read uses the submission's exact frozen participation.
The bounded lookup also guards cached thumbnails and derived staff previews.
Withdrawal stops future reuse; lawful existing trip references keep their copy
until their operational submission is removed. Purge or hard deletion denies
all retained reads immediately, without waiting for object deletion.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import Exists

from app.application.travellers.asset_policy import is_reviewable_asset
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentAssetModel,
    TravellerParticipationModel,
    TravellerProfileModel,
)


def has_retained_document(submission: object) -> bool:
    """Skip new joins entirely for ordinary fresh-upload approval paths."""
    return any(str(getattr(submission, field, "") or "").startswith("travellers/") for field in (
        "image_s3_key", "passport_back_s3_key", "passport_cover_s3_key",
        "passport_back_cover_s3_key", "passport_photo_s3_key"))


def live_trip_asset_reference(*, submission_id: uuid.UUID | None = None, group_id: uuid.UUID | None = None) -> Exists:
    """Correlated indexed existence check; never loads a person's trip history."""
    asset = TravellerDocumentAssetModel
    participation = TravellerParticipationModel
    source = PassportSubmissionModel
    query = select(participation.id).join(source,
        (source.id == participation.source_submission_id)
        & (source.group_id == participation.group_id)
        & (source.agency_id == participation.agency_id),
    ).join(ClientGroupModel, (ClientGroupModel.id == source.group_id)
        & (ClientGroupModel.agency_id == source.agency_id)).where(
        participation.agency_id == asset.agency_id,
        participation.company_id == asset.company_id,
        participation.traveller_id == asset.traveller_id,
        participation.passport_id == asset.passport_id,
        participation.document_revision_id == asset.document_revision_id,
        participation.status.in_(("submitted", "accepted")),
        ClientGroupModel.deleted_at.is_(None), ClientGroupModel.status != "deleted",
        or_(source.image_s3_key == asset.object_key, source.passport_back_s3_key == asset.object_key,
            source.passport_cover_s3_key == asset.object_key, source.passport_back_cover_s3_key == asset.object_key,
            source.passport_photo_s3_key == asset.object_key),
    ).correlate(asset)
    if submission_id is not None:
        query = query.where(source.id == submission_id)
    if group_id is not None:
        query = query.where(source.group_id == group_id)
    return exists(query)


async def can_read_snapshot_asset(
    session: AsyncSession, *, submission_id: uuid.UUID, group_id: uuid.UUID,
    agency_id: uuid.UUID, storage_key: str,
) -> bool:
    """Called after normal viewer authorization; one extra query for reuse keys."""
    if not storage_key.startswith("travellers/"):
        return True
    asset = TravellerDocumentAssetModel
    row = (await session.execute(select(asset, TravellerProfileModel)
        .join(TravellerProfileModel, (TravellerProfileModel.id == asset.traveller_id)
            & (TravellerProfileModel.company_id == asset.company_id)
            & (TravellerProfileModel.agency_id == asset.agency_id))
        .where(asset.agency_id == agency_id, asset.object_key == storage_key,
            live_trip_asset_reference(submission_id=submission_id, group_id=group_id))
        .limit(1))).first()
    if row is None:
        return False
    retained, person = row
    return bool(person.deleted_at is None and person.status != "deleted"
                and is_reviewable_asset(retained, datetime.now(UTC)))


async def sync_accepted_participations(
    session: AsyncSession, *, agency_id: uuid.UUID, group_id: uuid.UUID,
    submission_ids: Sequence[uuid.UUID],
) -> None:
    """Reflect explicit staff acceptance in batches of 100, without promotion.

Reviewed current-trip fields may differ from retained evidence. Record their
source revision separately; only explicit enrollment can create or promote a
new immutable retained revision. Memory O(min(n,100)); O(ceil(n/100)) queries.
The caller holds the group and selected submission locks before this hook.
"""
    for offset in range(0, len(submission_ids), 100):
        rows = (await session.execute(select(TravellerParticipationModel,
            PassportSubmissionModel.extraction_revision).join(PassportSubmissionModel,
                (PassportSubmissionModel.id == TravellerParticipationModel.source_submission_id)
                & (PassportSubmissionModel.group_id == TravellerParticipationModel.group_id)
                & (PassportSubmissionModel.agency_id == TravellerParticipationModel.agency_id))
            .where(TravellerParticipationModel.agency_id == agency_id,
                TravellerParticipationModel.group_id == group_id,
                TravellerParticipationModel.source_submission_id.in_(submission_ids[offset:offset + 100]),
                TravellerParticipationModel.status == "submitted",
                PassportSubmissionModel.status.in_(("staff_approved", "confirmed")))
            .with_for_update(of=TravellerParticipationModel))).all()
        for participation, source_revision in rows:
            participation.status = "accepted"
            participation.accepted_at = datetime.now(UTC)
            participation.revision += 1
            participation.confirmations = {**participation.confirmations,
                "accepted_source_extraction_revision": source_revision}


async def sync_approved_snapshot_participations(
    session: AsyncSession, *, agency_id: uuid.UUID, group_id: uuid.UUID,
    sources: Sequence[PassportSubmissionModel], approved_ids: Sequence[uuid.UUID],
) -> None:
    """Bulk approval skips all new queries when no selected row reuses history."""
    approved = set(approved_ids)
    retained_ids = [source.id for source in sources if source.id in approved and has_retained_document(source)]
    if retained_ids:
        await sync_accepted_participations(session, agency_id=agency_id, group_id=group_id,
            submission_ids=retained_ids)
