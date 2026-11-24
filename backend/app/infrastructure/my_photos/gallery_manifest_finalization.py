"""Gallery manifest finalization owner."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select

from app.application.my_photos.errors import MyPhotosConflict
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.infrastructure.database.my_photos_models import (
    MyPhotoGalleryManifestBatchModel,
    MyPhotoJobModel,
)
from app.infrastructure.my_photos.gallery_manifest_context import GalleryManifestContext
from app.infrastructure.my_photos.gallery_manifest_contracts import (
    GalleryManifestRequest,
    GalleryManifestResult,
)
from app.infrastructure.my_photos.gallery_manifest_fingerprints import _content_fingerprint
from app.infrastructure.my_photos.gallery_manifest_policy import (
    _dispatch_result,
    _require_manifest_header,
    _require_operator,
    _result_with_job,
)
from app.infrastructure.my_photos.gallery_manifest_providers import (
    _provider_configuration_fingerprint,
)
from app.infrastructure.my_photos.gallery_manifest_queries import (
    _job_for_manifest,
    _load_scope,
    _locked_gallery,
    _locked_manifest,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository


async def finalize_manifest(
    ctx: GalleryManifestContext,
    *,
    actor: User,
    mfa_verified_at: datetime,
    request: GalleryManifestRequest,
    dispatch: Callable[[uuid.UUID], None],
    batch_replay: bool = False,
) -> GalleryManifestResult:
    if ctx.session.in_transaction():
        raise RuntimeError("Manifest finalization requires a fresh database session")
    _require_operator(actor, request.agency_id, mfa_verified_at)
    header_fingerprint = request.header_fingerprint(
        provider_configuration_fingerprint=_provider_configuration_fingerprint(ctx)
    )
    should_dispatch = False
    async with ctx.session.begin():
        await _load_scope(ctx, request, lock=True)
        gallery = await _locked_gallery(ctx, request)
        if gallery is None:
            raise EntityNotFoundError("My Photos gallery", request.group_id)
        manifest = await _locked_manifest(ctx, gallery.id, request.manifest_identity)
        if manifest is None:
            raise EntityNotFoundError("My Photos manifest", request.manifest_identity)
        _require_manifest_header(manifest, request, header_fingerprint)
        if manifest.cancellation_requested_at is not None:
            raise MyPhotosConflict(
                "MY_PHOTOS_MANIFEST_CANCELLATION_PENDING",
                "This gallery manifest is being cancelled.",
            )
        existing_job = await _job_for_manifest(ctx, gallery.id, manifest.manifest_identity)
        if existing_job is not None:
            if (
                existing_job.target_revision != manifest.target_revision
                or existing_job.request_fingerprint != manifest.content_fingerprint
            ):
                raise MyPhotosConflict(
                    "MY_PHOTOS_MANIFEST_JOB_CONFLICT", "The gallery manifest index job is invalid."
                )
            result = _result_with_job(
                manifest, existing_job, batch_replay=batch_replay, manifest_replay=True
            )
            should_dispatch = existing_job.status in {"queued", "retrying"}
        else:
            if manifest.status != "receiving":
                raise MyPhotosConflict(
                    "MY_PHOTOS_MANIFEST_FINALIZED",
                    "The gallery manifest cannot be finalized again.",
                )
            batches = list(
                (
                    await ctx.session.execute(
                        select(MyPhotoGalleryManifestBatchModel)
                        .where(
                            MyPhotoGalleryManifestBatchModel.manifest_id == manifest.id,
                            MyPhotoGalleryManifestBatchModel.agency_id == request.agency_id,
                            MyPhotoGalleryManifestBatchModel.group_id == request.group_id,
                        )
                        .order_by(MyPhotoGalleryManifestBatchModel.batch_index)
                        .with_for_update()
                    )
                ).scalars()
            )
            if (
                len(batches) != manifest.batch_count
                or [batch.batch_index for batch in batches] != list(range(manifest.batch_count))
                or sum((batch.asset_count for batch in batches)) != manifest.total_asset_count
                or (manifest.received_asset_count != manifest.total_asset_count)
            ):
                raise MyPhotosConflict(
                    "MY_PHOTOS_MANIFEST_INCOMPLETE",
                    "Every manifest batch must be registered before finalization.",
                )
            content_fingerprint = _content_fingerprint(
                manifest.header_fingerprint, [batch.batch_fingerprint for batch in batches]
            )
            active_job = (
                await ctx.session.execute(
                    select(MyPhotoJobModel.id)
                    .where(
                        MyPhotoJobModel.gallery_id == gallery.id,
                        MyPhotoJobModel.job_type == "index_gallery",
                        MyPhotoJobModel.status.in_(("queued", "running", "retrying")),
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if active_job is not None:
                raise MyPhotosConflict(
                    "MY_PHOTOS_GALLERY_INDEX_BUSY", "Another gallery revision is still indexing."
                )
            index_job = MyPhotoJobModel(
                id=uuid.uuid4(),
                gallery_id=gallery.id,
                agency_id=request.agency_id,
                group_id=request.group_id,
                job_type="index_gallery",
                status="queued",
                idempotency_key=manifest.manifest_identity,
                request_fingerprint=content_fingerprint,
                target_revision=manifest.target_revision,
                max_attempts=ctx.settings.my_photos.job_max_attempts,
                total_count=manifest.total_asset_count,
                correlation_id=uuid.uuid4().hex,
            )
            ctx.session.add(index_job)
            manifest.content_fingerprint = content_fingerprint
            manifest.status = "indexing"
            manifest.finalized_at = datetime.now(tz=UTC)
            if gallery.published_revision == 0:
                gallery.status = "indexing"
            await ctx.session.flush()
            await AuditLogRepository(ctx.session).record(
                action="my_photos_gallery_manifest_finalized",
                entity_type="my_photos_gallery",
                agency_id=request.agency_id,
                user_id=actor.id,
                actor_email=actor.email,
                entity_id=str(gallery.id),
                metadata={
                    "group_id": str(request.group_id),
                    "target_revision": manifest.target_revision,
                    "asset_count": manifest.total_asset_count,
                    "batch_count": manifest.batch_count,
                    "retention_policy_version": manifest.retention_policy_version,
                },
            )
            result = _result_with_job(
                manifest, index_job, batch_replay=batch_replay, manifest_replay=False
            )
            should_dispatch = True
    if not should_dispatch or result.index_job_id is None:
        return result
    return _dispatch_result(result, dispatch=dispatch)
