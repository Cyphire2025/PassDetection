"""Gallery manifest status owner."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.infrastructure.database.my_photos_models import (
    MyPhotoGalleryManifestBatchModel,
    MyPhotoGalleryManifestModel,
)
from app.infrastructure.my_photos.gallery_manifest_context import GalleryManifestContext
from app.infrastructure.my_photos.gallery_manifest_contracts import (
    GalleryManifestLocator,
    GalleryManifestStatus,
)
from app.infrastructure.my_photos.gallery_manifest_policy import _as_utc, _require_operator
from app.infrastructure.my_photos.gallery_manifest_queries import (
    _job_for_manifest,
    _load_scope,
    _locked_gallery,
    _locked_manifest,
)


async def manifest_status(
    ctx: GalleryManifestContext,
    *,
    actor: User,
    mfa_verified_at: datetime,
    locator: GalleryManifestLocator,
) -> GalleryManifestStatus:
    if ctx.session.in_transaction():
        raise RuntimeError("Manifest status requires a fresh database session")
    _require_operator(actor, locator.agency_id, mfa_verified_at)
    try:
        await _load_scope(ctx, locator, lock=False)
        gallery = await _locked_gallery(ctx, locator, lock=False)
        if gallery is None:
            raise EntityNotFoundError("My Photos gallery", locator.group_id)
        manifest = await _locked_manifest(ctx, gallery.id, locator.manifest_identity, lock=False)
        if manifest is None:
            raise EntityNotFoundError("My Photos manifest", locator.manifest_identity)
        return await _status_snapshot(ctx, manifest)
    finally:
        await ctx.session.rollback()


async def _status_snapshot(
    ctx: GalleryManifestContext, manifest: MyPhotoGalleryManifestModel
) -> GalleryManifestStatus:
    batches = tuple(
        (
            await ctx.session.execute(
                select(MyPhotoGalleryManifestBatchModel.batch_index)
                .where(MyPhotoGalleryManifestBatchModel.manifest_id == manifest.id)
                .order_by(MyPhotoGalleryManifestBatchModel.batch_index)
            )
        ).scalars()
    )
    job = await _job_for_manifest(ctx, manifest.gallery_id, manifest.manifest_identity)
    cancellation_requested = bool(
        manifest.cancellation_requested_at is not None
        or (job is not None and job.cancellation_requested_at is not None)
    )
    if manifest.status == "cancelled":
        state = "cancelled"
    elif cancellation_requested:
        state = "cancellation_pending"
    else:
        state = job.status if job is not None else manifest.status
    received = set(batches)
    return GalleryManifestStatus(
        manifest_id=manifest.id,
        gallery_id=manifest.gallery_id,
        index_job_id=job.id if job is not None else None,
        target_revision=manifest.target_revision,
        received_asset_count=manifest.received_asset_count,
        total_asset_count=manifest.total_asset_count,
        batch_count=manifest.batch_count,
        received_batch_indices=batches,
        missing_batch_indices=tuple(
            (index for index in range(manifest.batch_count) if index not in received)
        ),
        state=state,
        cancellation_requested=cancellation_requested,
        content_fingerprint=manifest.content_fingerprint,
        updated_at=_as_utc(manifest.updated_at),
    )
