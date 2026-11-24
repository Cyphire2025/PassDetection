"""Durable photo operation job queries."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.my_photos.states import MEDIA_DELIVERY_READY_STATES
from app.infrastructure.database.my_photos_models import (
    MyPhotoAssetVariantModel,
    MyPhotoGalleryModel,
    MyPhotoJobModel,
    MyPhotoMediaAssetModel,
)
from app.infrastructure.my_photos.operational_job_contracts import _OperationalClaim
from app.infrastructure.my_photos.operational_job_policy import _utc


async def _locked_current_job_scope(
    session: AsyncSession, claim: _OperationalClaim
) -> tuple[MyPhotoJobModel, MyPhotoGalleryModel] | None:
    gallery = (
        await session.execute(
            select(MyPhotoGalleryModel)
            .where(
                MyPhotoGalleryModel.id == claim.gallery_id,
                MyPhotoGalleryModel.agency_id == claim.agency_id,
                MyPhotoGalleryModel.group_id == claim.group_id,
                MyPhotoGalleryModel.feature_enabled.is_(True),
                MyPhotoGalleryModel.status.notin_(("failed", "removed")),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if gallery is None:
        return None
    job = (
        await session.execute(
            select(MyPhotoJobModel)
            .where(
                MyPhotoJobModel.id == claim.job_id,
                MyPhotoJobModel.gallery_id == claim.gallery_id,
                MyPhotoJobModel.agency_id == claim.agency_id,
                MyPhotoJobModel.group_id == claim.group_id,
                MyPhotoJobModel.status == "running",
                MyPhotoJobModel.lease_owner == claim.lease_owner,
                MyPhotoJobModel.cancellation_requested_at.is_(None),
                MyPhotoJobModel.lease_expires_at > datetime.now(tz=UTC),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if (
        job is None
        or job.lease_expires_at is None
        or _utc(job.lease_expires_at) <= datetime.now(tz=UTC)
    ):
        return None
    return (job, gallery)


async def _locked_job_and_asset(
    session: AsyncSession, claim: _OperationalClaim
) -> tuple[MyPhotoJobModel, MyPhotoMediaAssetModel] | None:
    rows = await _locked_current_job_scope(session, claim)
    if rows is None or claim.media_asset_id is None:
        return None
    job, _gallery = rows
    asset = (
        await session.execute(
            select(MyPhotoMediaAssetModel)
            .where(
                MyPhotoMediaAssetModel.id == claim.media_asset_id,
                MyPhotoMediaAssetModel.gallery_id == claim.gallery_id,
                MyPhotoMediaAssetModel.agency_id == claim.agency_id,
                MyPhotoMediaAssetModel.group_id == claim.group_id,
                MyPhotoMediaAssetModel.processing_state.notin_(("failed", "removed")),
                MyPhotoMediaAssetModel.availability_state.notin_(("failed", "removed")),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if (
        asset is None
        or job.lease_expires_at is None
        or _utc(job.lease_expires_at) <= datetime.now(tz=UTC)
    ):
        return None
    return (job, asset)


async def _locked_claim_job(
    session: AsyncSession, claim: _OperationalClaim
) -> MyPhotoJobModel | None:
    """Use the same current authority for failure effects and successful output."""
    rows = (
        await _locked_job_and_asset(session, claim)
        if claim.media_asset_id is not None
        else await _locked_current_job_scope(session, claim)
    )
    return None if rows is None else rows[0]


async def _latest_ready_analysis_variants(
    session: AsyncSession,
    *,
    assets: list[MyPhotoMediaAssetModel],
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
) -> dict[uuid.UUID, MyPhotoAssetVariantModel]:
    """Load one current, provider-ready analysis derivative per bounded batch."""
    asset_ids = tuple((asset.id for asset in assets))
    if not asset_ids:
        return {}
    now = datetime.now(tz=UTC)
    latest = (
        select(
            MyPhotoAssetVariantModel.media_asset_id.label("asset_id"),
            func.max(MyPhotoAssetVariantModel.delivery_version).label("delivery_version"),
        )
        .where(
            MyPhotoAssetVariantModel.media_asset_id.in_(asset_ids),
            MyPhotoAssetVariantModel.agency_id == agency_id,
            MyPhotoAssetVariantModel.group_id == group_id,
            MyPhotoAssetVariantModel.variant_kind == "analysis",
            MyPhotoAssetVariantModel.availability_state.in_(tuple(MEDIA_DELIVERY_READY_STATES)),
            MyPhotoAssetVariantModel.storage_reference.is_not(None),
            or_(
                MyPhotoAssetVariantModel.expires_at.is_(None),
                MyPhotoAssetVariantModel.expires_at > now,
            ),
        )
        .group_by(MyPhotoAssetVariantModel.media_asset_id)
        .subquery()
    )
    rows = list(
        (
            await session.execute(
                select(MyPhotoAssetVariantModel).join(
                    latest,
                    and_(
                        latest.c.asset_id == MyPhotoAssetVariantModel.media_asset_id,
                        latest.c.delivery_version == MyPhotoAssetVariantModel.delivery_version,
                    ),
                )
            )
        ).scalars()
    )
    return {row.media_asset_id: row for row in rows}
