"""Gallery manifest cleanup owner."""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import delete, select

from app.application.my_photos.errors import MyPhotosConflict, MyPhotosUnavailable
from app.application.my_photos.providers import FaceDeletionRequest, MediaDeletionRequest
from app.domain.entities.entities import User
from app.infrastructure.database.my_photos_models import (
    MyPhotoAssetVariantModel,
    MyPhotoFaceOccurrenceModel,
    MyPhotoGalleryManifestBatchModel,
    MyPhotoGalleryManifestModel,
    MyPhotoGalleryModel,
    MyPhotoMediaAssetModel,
)
from app.infrastructure.my_photos.gallery_manifest_context import GalleryManifestContext
from app.infrastructure.my_photos.gallery_manifest_contracts import GalleryManifestLocator
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository


async def _delete_cancelled_provider_faces(
    ctx: GalleryManifestContext,
    *,
    locator: GalleryManifestLocator,
    collection_reference: str,
    provider_faces: tuple[tuple[uuid.UUID, str], ...],
) -> None:
    if ctx.providers.provider_name != "aws" or not ctx.providers.face_search.ready:
        raise MyPhotosUnavailable(
            "MY_PHOTOS_PROVIDER_NOT_CONFIGURED",
            "Production My Photos providers are not configured.",
        )
    requested = tuple((reference for _face_id, reference in provider_faces))
    try:
        async with asyncio.timeout(ctx.settings.my_photos.face_search_provider_timeout_seconds):
            result = await ctx.providers.face_search.delete_faces(
                FaceDeletionRequest(
                    tenant_scope=str(locator.agency_id),
                    group_scope=str(locator.group_id),
                    collection_reference=collection_reference,
                    provider_face_references=requested,
                )
            )
    except MyPhotosUnavailable:
        raise
    except Exception as exc:
        raise MyPhotosUnavailable(
            "MY_PHOTOS_PROVIDER_UNAVAILABLE", "Photo index cleanup is temporarily unavailable."
        ) from exc
    outcomes = result.deleted_face_references + result.not_found_face_references
    if len(outcomes) != len(set(outcomes)) or set(outcomes) != set(requested):
        raise MyPhotosUnavailable(
            "MY_PHOTOS_PROVIDER_RESULT_INVALID", "Photo index cleanup returned an invalid result."
        )


async def _cancelled_media_batch(
    ctx: GalleryManifestContext,
    *,
    gallery: MyPhotoGalleryModel,
    manifest: MyPhotoGalleryManifestModel,
) -> tuple[tuple[str, ...], tuple[uuid.UUID, ...], tuple[uuid.UUID, ...]]:
    limit = ctx.settings.my_photos.provider_deletion_batch_size
    assets = list(
        (
            await ctx.session.execute(
                select(MyPhotoMediaAssetModel)
                .where(
                    MyPhotoMediaAssetModel.gallery_id == gallery.id,
                    MyPhotoMediaAssetModel.published_revision == manifest.target_revision,
                    MyPhotoMediaAssetModel.availability_state != "removed",
                )
                .order_by(MyPhotoMediaAssetModel.id)
                .limit(limit)
                .with_for_update()
            )
        ).scalars()
    )
    references: list[str] = []
    asset_ids: list[uuid.UUID] = []
    for asset in assets:
        exact = tuple(
            dict.fromkeys(
                (
                    reference
                    for reference in (asset.archive_reference, asset.storage_reference)
                    if reference is not None
                )
            )
        )
        if len(exact) != 1:
            raise MyPhotosConflict(
                "MY_PHOTOS_MANIFEST_MEDIA_REFERENCE_INVALID",
                "Cancelled media does not have one exact versioned reference.",
            )
        if len(references) == limit:
            break
        references.extend(exact)
        asset_ids.append(asset.id)
    remaining = limit - len(references)
    variant_ids: list[uuid.UUID] = []
    if remaining > 0:
        variants = list(
            (
                await ctx.session.execute(
                    select(MyPhotoAssetVariantModel)
                    .join(
                        MyPhotoMediaAssetModel,
                        MyPhotoMediaAssetModel.id == MyPhotoAssetVariantModel.media_asset_id,
                    )
                    .where(
                        MyPhotoMediaAssetModel.gallery_id == gallery.id,
                        MyPhotoMediaAssetModel.published_revision == manifest.target_revision,
                        MyPhotoAssetVariantModel.availability_state != "removed",
                    )
                    .order_by(MyPhotoAssetVariantModel.id)
                    .limit(remaining)
                    .with_for_update()
                )
            ).scalars()
        )
        for variant in variants:
            if variant.storage_reference is None:
                raise MyPhotosConflict(
                    "MY_PHOTOS_MANIFEST_MEDIA_REFERENCE_INVALID",
                    "Cancelled media is missing its exact versioned reference.",
                )
            references.append(variant.storage_reference)
            variant_ids.append(variant.id)
    if len(references) != len(set(references)):
        raise MyPhotosConflict(
            "MY_PHOTOS_MANIFEST_MEDIA_REFERENCE_INVALID",
            "Cancelled media contains duplicate versioned references.",
        )
    return (tuple(references), tuple(asset_ids), tuple(variant_ids))


async def _delete_cancelled_media(
    ctx: GalleryManifestContext, *, locator: GalleryManifestLocator, references: tuple[str, ...]
) -> None:
    if ctx.providers.provider_name != "aws" or not ctx.providers.media.ready:
        raise MyPhotosUnavailable(
            "MY_PHOTOS_PROVIDER_NOT_CONFIGURED",
            "Production My Photos providers are not configured.",
        )
    try:
        async with asyncio.timeout(ctx.settings.my_photos.media_provider_timeout_seconds):
            result = await ctx.providers.media.delete(
                MediaDeletionRequest(
                    tenant_scope=str(locator.agency_id),
                    group_scope=str(locator.group_id),
                    media_references=references,
                )
            )
    except MyPhotosUnavailable:
        raise
    except Exception as exc:
        raise MyPhotosUnavailable(
            "MY_PHOTOS_PROVIDER_UNAVAILABLE", "Photo storage cleanup is temporarily unavailable."
        ) from exc
    outcomes = result.deleted_references + result.not_found_references
    if len(outcomes) != len(set(outcomes)) or set(outcomes) != set(references):
        raise MyPhotosUnavailable(
            "MY_PHOTOS_PROVIDER_RESULT_INVALID", "Photo storage cleanup returned an invalid result."
        )


async def _has_cancelled_media(
    ctx: GalleryManifestContext,
    *,
    gallery: MyPhotoGalleryModel,
    manifest: MyPhotoGalleryManifestModel,
) -> bool:
    asset = (
        await ctx.session.execute(
            select(MyPhotoMediaAssetModel.id)
            .where(
                MyPhotoMediaAssetModel.gallery_id == gallery.id,
                MyPhotoMediaAssetModel.published_revision == manifest.target_revision,
                MyPhotoMediaAssetModel.availability_state != "removed",
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if asset is not None:
        return True
    variant = (
        await ctx.session.execute(
            select(MyPhotoAssetVariantModel.id)
            .join(
                MyPhotoMediaAssetModel,
                MyPhotoMediaAssetModel.id == MyPhotoAssetVariantModel.media_asset_id,
            )
            .where(
                MyPhotoMediaAssetModel.gallery_id == gallery.id,
                MyPhotoMediaAssetModel.published_revision == manifest.target_revision,
                MyPhotoAssetVariantModel.availability_state != "removed",
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return variant is not None


async def _cleanup_cancelled_manifest(
    ctx: GalleryManifestContext,
    *,
    actor: User,
    gallery: MyPhotoGalleryModel,
    manifest: MyPhotoGalleryManifestModel,
) -> None:
    active_face = (
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
    if active_face is not None:
        raise MyPhotosConflict(
            "MY_PHOTOS_MANIFEST_CLEANUP_PENDING",
            "The cancelled provider index still requires bounded cleanup.",
        )
    if await _has_cancelled_media(ctx, gallery=gallery, manifest=manifest):
        raise MyPhotosConflict(
            "MY_PHOTOS_MANIFEST_MEDIA_CLEANUP_PENDING",
            "The cancelled media versions still require bounded cleanup.",
        )
    asset_ids = tuple(
        (
            await ctx.session.execute(
                select(MyPhotoMediaAssetModel.id).where(
                    MyPhotoMediaAssetModel.gallery_id == gallery.id,
                    MyPhotoMediaAssetModel.agency_id == manifest.agency_id,
                    MyPhotoMediaAssetModel.group_id == manifest.group_id,
                    MyPhotoMediaAssetModel.published_revision == manifest.target_revision,
                )
            )
        ).scalars()
    )
    if asset_ids:
        await ctx.session.execute(
            delete(MyPhotoFaceOccurrenceModel).where(
                MyPhotoFaceOccurrenceModel.media_asset_id.in_(asset_ids)
            )
        )
        await ctx.session.execute(
            delete(MyPhotoAssetVariantModel).where(
                MyPhotoAssetVariantModel.media_asset_id.in_(asset_ids)
            )
        )
        await ctx.session.execute(
            delete(MyPhotoMediaAssetModel).where(MyPhotoMediaAssetModel.id.in_(asset_ids))
        )
    await ctx.session.execute(
        delete(MyPhotoGalleryManifestBatchModel).where(
            MyPhotoGalleryManifestBatchModel.manifest_id == manifest.id
        )
    )
    manifest.received_asset_count = 0
    manifest.status = "cancelled"
    if gallery.published_revision == 0:
        gallery.status = "not_uploaded"
    await AuditLogRepository(ctx.session).record(
        action="my_photos_gallery_manifest_cancelled",
        entity_type="my_photos_gallery",
        agency_id=manifest.agency_id,
        user_id=actor.id,
        actor_email=actor.email,
        entity_id=str(gallery.id),
        metadata={
            "group_id": str(manifest.group_id),
            "manifest_identity": manifest.manifest_identity,
            "target_revision": manifest.target_revision,
            "removed_asset_count": len(asset_ids),
        },
    )
