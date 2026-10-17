"""Batched live retained-object authorization for ZIP preparation/publication."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.travellers.asset_policy import is_reviewable_asset
from app.domain.entities.entities import PassportSubmission
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentAssetModel,
    TravellerParticipationModel,
    TravellerProfileModel,
)


async def can_export_snapshot_assets(
    session: AsyncSession, *, agency_id: uuid.UUID, group_id: uuid.UUID,
    sources: Sequence[PassportSubmission],
) -> bool:
    """O(ceil(n/200)) seeks, at most 1,000 asset rows per batch; no N+1.

The existing ZIP contract caps n at 5,000. Ordinary source keys perform no
queries. Call again before publishing rendered bytes, after storage work.
"""
    for offset in range(0, len(sources), 200):
        expected = {(source.id, key) for source in sources[offset:offset + 200]
            for key in (source.image_s3_key, source.passport_back_s3_key, source.passport_photo_s3_key,
                source.passport_cover_s3_key, source.passport_back_cover_s3_key)
            if key and key.startswith("travellers/")}
        if not expected:
            continue
        asset, participation, source = TravellerDocumentAssetModel, TravellerParticipationModel, PassportSubmissionModel
        query = select(asset, source.id).join(TravellerProfileModel,
            (TravellerProfileModel.id == asset.traveller_id)
            & (TravellerProfileModel.agency_id == asset.agency_id)
            & (TravellerProfileModel.company_id == asset.company_id)).join(participation,
            (participation.document_revision_id == asset.document_revision_id)
            & (participation.passport_id == asset.passport_id)
            & (participation.traveller_id == asset.traveller_id)
            & (participation.agency_id == asset.agency_id)
            & (participation.company_id == asset.company_id)).join(source,
            (source.id == participation.source_submission_id)
            & (source.agency_id == participation.agency_id) & (source.group_id == participation.group_id))
        query = query.join(ClientGroupModel, (ClientGroupModel.id == source.group_id)
            & (ClientGroupModel.agency_id == source.agency_id)).where(
            asset.agency_id == agency_id, source.group_id == group_id,
            source.id.in_({identifier for identifier, _ in expected}),
            asset.object_key.in_({key for _, key in expected}),
            asset.availability == "available", asset.purged_at.is_(None),
            TravellerProfileModel.status != "deleted", TravellerProfileModel.deleted_at.is_(None),
            participation.status.in_(("submitted", "accepted")),
            ClientGroupModel.status != "deleted", ClientGroupModel.deleted_at.is_(None),
            or_(source.image_s3_key == asset.object_key, source.passport_back_s3_key == asset.object_key,
                source.passport_photo_s3_key == asset.object_key, source.passport_cover_s3_key == asset.object_key,
                source.passport_back_cover_s3_key == asset.object_key),
        ).limit(1001).execution_options(populate_existing=True)
        rows = (await session.execute(query)).all()
        now = datetime.now(UTC)
        allowed = {(identifier, retained.object_key) for retained, identifier in rows
            if is_reviewable_asset(retained, now)}
        if not expected.issubset(allowed):
            return False
    return True
