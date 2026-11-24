"""Gallery manifest cancellation owner."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update

from app.application.my_photos.errors import MyPhotosConflict
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.infrastructure.database.my_photos_models import (
    MyPhotoAssetVariantModel,
    MyPhotoFaceOccurrenceModel,
    MyPhotoGalleryManifestModel,
    MyPhotoGalleryModel,
    MyPhotoJobModel,
    MyPhotoMediaAssetModel,
)
from app.infrastructure.my_photos.gallery_manifest_cleanup import (
    _cancelled_media_batch,
    _cleanup_cancelled_manifest,
    _delete_cancelled_media,
    _delete_cancelled_provider_faces,
    _has_cancelled_media,
)
from app.infrastructure.my_photos.gallery_manifest_context import GalleryManifestContext
from app.infrastructure.my_photos.gallery_manifest_contracts import (
    GalleryManifestLocator,
    GalleryManifestStatus,
)
from app.infrastructure.my_photos.gallery_manifest_policy import _require_operator
from app.infrastructure.my_photos.gallery_manifest_queries import (
    _job_for_manifest,
    _load_scope,
    _locked_gallery,
    _locked_manifest,
)
from app.infrastructure.my_photos.gallery_manifest_status import manifest_status
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository


async def cancel_manifest(
    ctx: GalleryManifestContext,
    *,
    actor: User,
    mfa_verified_at: datetime,
    locator: GalleryManifestLocator,
) -> GalleryManifestStatus:
    """Request cancellation, then clean only this unpublished target revision.

    A running worker is first stopped through the durable job cancellation
    fence. Repeating the command resumes bounded provider-face cleanup and
    finally removes the local staging rows.
    """
    if ctx.session.in_transaction():
        raise RuntimeError("Manifest cancellation requires a fresh database session")
    _require_operator(actor, locator.agency_id, mfa_verified_at)
    provider_faces: tuple[tuple[uuid.UUID, str], ...] = ()
    provider_media_references: tuple[str, ...] = ()
    media_asset_ids: tuple[uuid.UUID, ...] = ()
    media_variant_ids: tuple[uuid.UUID, ...] = ()
    collection_reference: str | None = None
    async with ctx.session.begin():
        await _load_scope(ctx, locator, lock=True)
        gallery = await _locked_gallery(ctx, locator)
        if gallery is None:
            raise EntityNotFoundError("My Photos gallery", locator.group_id)
        manifest = await _locked_manifest(ctx, gallery.id, locator.manifest_identity)
        if manifest is None:
            raise EntityNotFoundError("My Photos manifest", locator.manifest_identity)
        if manifest.status == "cancelled":
            pass
        elif (
            gallery.published_revision >= manifest.target_revision or manifest.status == "finalized"
        ):
            raise MyPhotosConflict(
                "MY_PHOTOS_MANIFEST_ALREADY_PUBLISHED",
                "A published gallery revision cannot be cancelled.",
            )
        else:
            job = await _job_for_manifest(ctx, gallery.id, manifest.manifest_identity, lock=True)
            now = datetime.now(tz=UTC)
            manifest.cancellation_requested_at = manifest.cancellation_requested_at or now
            if job is not None and job.status == "succeeded":
                raise MyPhotosConflict(
                    "MY_PHOTOS_MANIFEST_ALREADY_INDEXED",
                    "A completed gallery index cannot be cancelled.",
                )
            if job is not None and job.status in {"queued", "running", "retrying"}:
                first_request = job.cancellation_requested_at is None
                job.cancellation_requested_at = job.cancellation_requested_at or now
                if job.status in {"queued", "retrying"}:
                    job.status = "cancelled"
                    job.completed_at = now
                    job.lease_owner = None
                    job.lease_expires_at = None
                if first_request:
                    await _audit_cancellation_requested(
                        ctx, actor=actor, gallery=gallery, manifest=manifest, job=job
                    )
            elif job is not None and job.status == "failed":
                job.cancellation_requested_at = job.cancellation_requested_at or now
            if job is None or job.status in {"failed", "cancelled"}:
                face_rows = list(
                    (
                        await ctx.session.execute(
                            select(MyPhotoFaceOccurrenceModel)
                            .join(
                                MyPhotoMediaAssetModel,
                                MyPhotoMediaAssetModel.id
                                == MyPhotoFaceOccurrenceModel.media_asset_id,
                            )
                            .where(
                                MyPhotoMediaAssetModel.gallery_id == gallery.id,
                                MyPhotoMediaAssetModel.agency_id == locator.agency_id,
                                MyPhotoMediaAssetModel.group_id == locator.group_id,
                                MyPhotoMediaAssetModel.published_revision
                                == manifest.target_revision,
                                MyPhotoFaceOccurrenceModel.active.is_(True),
                            )
                            .order_by(MyPhotoFaceOccurrenceModel.id)
                            .limit(ctx.settings.my_photos.provider_deletion_batch_size)
                            .with_for_update()
                        )
                    ).scalars()
                )
                if face_rows:
                    provider_faces = tuple(
                        ((face.id, face.provider_face_reference) for face in face_rows)
                    )
                    collection_reference = manifest.provider_collection_reference
                else:
                    (
                        provider_media_references,
                        media_asset_ids,
                        media_variant_ids,
                    ) = await _cancelled_media_batch(ctx, gallery=gallery, manifest=manifest)
                    if not provider_media_references:
                        await _cleanup_cancelled_manifest(
                            ctx, actor=actor, gallery=gallery, manifest=manifest
                        )
    if provider_faces:
        assert collection_reference is not None
        await _delete_cancelled_provider_faces(
            ctx,
            locator=locator,
            collection_reference=collection_reference,
            provider_faces=provider_faces,
        )
        async with ctx.session.begin():
            gallery = await _locked_gallery(ctx, locator)
            if gallery is None:
                raise EntityNotFoundError("My Photos gallery", locator.group_id)
            manifest = await _locked_manifest(ctx, gallery.id, locator.manifest_identity)
            if manifest is None:
                raise EntityNotFoundError("My Photos manifest", locator.manifest_identity)
            job = await _job_for_manifest(ctx, gallery.id, manifest.manifest_identity, lock=True)
            if job is not None and job.status not in {"failed", "cancelled"}:
                raise MyPhotosConflict(
                    "MY_PHOTOS_MANIFEST_CANCELLATION_PENDING",
                    "The gallery index worker has not stopped yet.",
                )
            face_ids = tuple((face_id for face_id, _reference in provider_faces))
            await ctx.session.execute(
                update(MyPhotoFaceOccurrenceModel)
                .where(
                    MyPhotoFaceOccurrenceModel.id.in_(face_ids),
                    MyPhotoFaceOccurrenceModel.agency_id == locator.agency_id,
                    MyPhotoFaceOccurrenceModel.group_id == locator.group_id,
                )
                .values(active=False, deleted_at=datetime.now(tz=UTC))
            )
            remaining = (
                await ctx.session.execute(
                    select(MyPhotoFaceOccurrenceModel.id)
                    .join(
                        MyPhotoMediaAssetModel,
                        MyPhotoMediaAssetModel.id == MyPhotoFaceOccurrenceModel.media_asset_id,
                    )
                    .where(
                        MyPhotoMediaAssetModel.gallery_id == gallery.id,
                        MyPhotoMediaAssetModel.published_revision == manifest.target_revision,
                        MyPhotoFaceOccurrenceModel.active.is_(True),
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if remaining is None:
                pass
    elif provider_media_references:
        await _delete_cancelled_media(ctx, locator=locator, references=provider_media_references)
        async with ctx.session.begin():
            gallery = await _locked_gallery(ctx, locator)
            if gallery is None:
                raise EntityNotFoundError("My Photos gallery", locator.group_id)
            manifest = await _locked_manifest(ctx, gallery.id, locator.manifest_identity)
            if manifest is None:
                raise EntityNotFoundError("My Photos manifest", locator.manifest_identity)
            job = await _job_for_manifest(ctx, gallery.id, manifest.manifest_identity, lock=True)
            if job is not None and job.status not in {"failed", "cancelled"}:
                raise MyPhotosConflict(
                    "MY_PHOTOS_MANIFEST_CANCELLATION_PENDING",
                    "The gallery index worker has not stopped yet.",
                )
            if media_asset_ids:
                await ctx.session.execute(
                    update(MyPhotoMediaAssetModel)
                    .where(MyPhotoMediaAssetModel.id.in_(media_asset_ids))
                    .values(processing_state="removed", availability_state="removed")
                )
            if media_variant_ids:
                await ctx.session.execute(
                    update(MyPhotoAssetVariantModel)
                    .where(MyPhotoAssetVariantModel.id.in_(media_variant_ids))
                    .values(availability_state="removed")
                )
            remaining_media = await _has_cancelled_media(ctx, gallery=gallery, manifest=manifest)
            if not remaining_media:
                await _cleanup_cancelled_manifest(
                    ctx, actor=actor, gallery=gallery, manifest=manifest
                )
    return await manifest_status(ctx, actor=actor, mfa_verified_at=mfa_verified_at, locator=locator)


async def _audit_cancellation_requested(
    ctx: GalleryManifestContext,
    *,
    actor: User,
    gallery: MyPhotoGalleryModel,
    manifest: MyPhotoGalleryManifestModel,
    job: MyPhotoJobModel,
) -> None:
    await AuditLogRepository(ctx.session).record(
        action="my_photos_gallery_manifest_cancellation_requested",
        entity_type="my_photos_gallery",
        agency_id=manifest.agency_id,
        user_id=actor.id,
        actor_email=actor.email,
        entity_id=str(gallery.id),
        metadata={
            "group_id": str(manifest.group_id),
            "manifest_identity": manifest.manifest_identity,
            "target_revision": manifest.target_revision,
            "index_job_id": str(job.id),
        },
    )
