"""Gallery manifest results owner."""

from __future__ import annotations

from app.application.my_photos.errors import MyPhotosConflict
from app.infrastructure.database.my_photos_models import MyPhotoGalleryManifestModel
from app.infrastructure.my_photos.gallery_manifest_context import GalleryManifestContext
from app.infrastructure.my_photos.gallery_manifest_contracts import (
    GalleryManifestRequest,
    GalleryManifestResult,
)
from app.infrastructure.my_photos.gallery_manifest_policy import (
    _require_manifest_header,
    _result_with_job,
)
from app.infrastructure.my_photos.gallery_manifest_queries import (
    _job_for_manifest,
    _locked_batch,
    _locked_gallery,
    _locked_manifest,
)


async def _existing_batch_result(
    ctx: GalleryManifestContext,
    request: GalleryManifestRequest,
    *,
    header_fingerprint: str,
    batch_fingerprint: str,
) -> GalleryManifestResult | None:
    gallery = await _locked_gallery(ctx, request)
    if gallery is None:
        return None
    manifest = await _locked_manifest(ctx, gallery.id, request.manifest_identity)
    if manifest is None:
        return None
    _require_manifest_header(manifest, request, header_fingerprint)
    if manifest.cancellation_requested_at is not None:
        raise MyPhotosConflict(
            "MY_PHOTOS_MANIFEST_CANCELLATION_PENDING", "This gallery manifest is being cancelled."
        )
    batch = await _locked_batch(ctx, manifest.id, request.batch_index)
    if batch is None:
        if manifest.status != "receiving":
            raise MyPhotosConflict(
                "MY_PHOTOS_MANIFEST_FINALIZED", "This gallery manifest no longer accepts batches."
            )
        return None
    if batch.batch_fingerprint != batch_fingerprint:
        raise MyPhotosConflict(
            "MY_PHOTOS_MANIFEST_BATCH_CONFLICT",
            "The manifest batch index was already used for different input.",
        )
    return await _result_for_manifest(
        ctx, manifest, batch_replay=True, manifest_replay=manifest.status != "receiving"
    )


async def _result_for_manifest(
    ctx: GalleryManifestContext,
    manifest: MyPhotoGalleryManifestModel,
    *,
    batch_replay: bool,
    manifest_replay: bool,
) -> GalleryManifestResult:
    job = await _job_for_manifest(ctx, manifest.gallery_id, manifest.manifest_identity)
    if job is not None:
        return _result_with_job(
            manifest, job, batch_replay=batch_replay, manifest_replay=manifest_replay
        )
    return GalleryManifestResult(
        manifest_id=manifest.id,
        gallery_id=manifest.gallery_id,
        index_job_id=None,
        target_revision=manifest.target_revision,
        received_asset_count=manifest.received_asset_count,
        total_asset_count=manifest.total_asset_count,
        batch_count=manifest.batch_count,
        state="receiving",
        batch_replay=batch_replay,
        manifest_replay=manifest_replay,
        content_fingerprint=manifest.content_fingerprint,
        dispatch_state="not_required",
    )
