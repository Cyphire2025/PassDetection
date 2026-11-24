"""Gallery manifest persistence owner."""

from __future__ import annotations

import uuid
from typing import cast

from sqlalchemy import select

from app.application.my_photos.errors import MyPhotosConflict
from app.domain.entities.entities import User
from app.infrastructure.database.my_photos_models import (
    MyPhotoAssetVariantModel,
    MyPhotoGalleryManifestBatchModel,
    MyPhotoGalleryManifestModel,
    MyPhotoGalleryModel,
    MyPhotoMediaAssetModel,
)
from app.infrastructure.my_photos.gallery_manifest_context import GalleryManifestContext
from app.infrastructure.my_photos.gallery_manifest_contracts import (
    GalleryManifestRequest,
    _VerifiedAsset,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository


async def _persist_batch_assets(
    ctx: GalleryManifestContext,
    *,
    request: GalleryManifestRequest,
    gallery: MyPhotoGalleryModel,
    manifest: MyPhotoGalleryManifestModel,
    verified_assets: tuple[_VerifiedAsset, ...],
    batch_fingerprint: str,
    actor: User,
) -> None:
    requested_keys = tuple((item.asset.immutable_asset_key for item in verified_assets))
    requested_ranks = tuple((item.asset.sort_rank for item in verified_assets))
    identity_conflict = (
        await ctx.session.execute(
            select(MyPhotoMediaAssetModel.id)
            .where(
                MyPhotoMediaAssetModel.gallery_id == gallery.id,
                MyPhotoMediaAssetModel.immutable_asset_key.in_(requested_keys),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    rank_conflict = (
        await ctx.session.execute(
            select(MyPhotoMediaAssetModel.id)
            .where(
                MyPhotoMediaAssetModel.gallery_id == gallery.id,
                MyPhotoMediaAssetModel.published_revision == manifest.target_revision,
                MyPhotoMediaAssetModel.sort_rank.in_(requested_ranks),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if identity_conflict is not None or rank_conflict is not None:
        raise MyPhotosConflict(
            "MY_PHOTOS_ASSET_IDENTITY_CONFLICT",
            "A manifest asset identity or sort rank already exists.",
        )
    pending_variants: list[MyPhotoAssetVariantModel] = []
    for verified in verified_assets:
        item = verified.asset
        asset_id = uuid.uuid4()
        ctx.session.add(
            MyPhotoMediaAssetModel(
                id=asset_id,
                gallery_id=gallery.id,
                agency_id=request.agency_id,
                group_id=request.group_id,
                immutable_asset_key=item.immutable_asset_key,
                media_type="photo",
                archive_reference=verified.original_storage_reference,
                storage_reference=verified.original_storage_reference,
                original_filename=item.original_filename,
                mime_type=item.mime_type,
                width=item.width,
                height=item.height,
                aspect_ratio=item.width / item.height,
                byte_size=item.byte_size,
                checksum_sha256=item.checksum_sha256,
                captured_at=item.captured_at,
                orientation=item.orientation,
                processing_state="registered",
                availability_state="original_available_online",
                published_revision=manifest.target_revision,
                sort_rank=item.sort_rank,
            )
        )
        for declared in item.variants:
            provider = verified.variants[declared.kind]
            pending_variants.append(
                MyPhotoAssetVariantModel(
                    id=uuid.uuid4(),
                    media_asset_id=asset_id,
                    agency_id=request.agency_id,
                    group_id=request.group_id,
                    variant_kind=declared.kind,
                    storage_reference=provider.storage_reference,
                    mime_type=cast(str, provider.content_type),
                    width=cast(int, provider.width),
                    height=cast(int, provider.height),
                    byte_size=cast(int, provider.byte_size),
                    checksum_sha256=cast(str, provider.checksum_sha256),
                    availability_state=provider.state,
                    delivery_version=provider.delivery_version,
                    expires_at=manifest.availability_ends_at,
                )
            )
    await ctx.session.flush()
    ctx.session.add_all(pending_variants)
    ctx.session.add(
        MyPhotoGalleryManifestBatchModel(
            id=uuid.uuid4(),
            manifest_id=manifest.id,
            agency_id=request.agency_id,
            group_id=request.group_id,
            batch_index=request.batch_index,
            batch_fingerprint=batch_fingerprint,
            asset_count=len(verified_assets),
        )
    )
    manifest.received_asset_count += len(verified_assets)
    await ctx.session.flush()
    await AuditLogRepository(ctx.session).record(
        action="my_photos_gallery_manifest_batch_registered",
        entity_type="my_photos_gallery",
        agency_id=request.agency_id,
        user_id=actor.id,
        actor_email=actor.email,
        entity_id=str(gallery.id),
        metadata={
            "group_id": str(request.group_id),
            "target_revision": manifest.target_revision,
            "batch_index": request.batch_index,
            "batch_count": manifest.batch_count,
            "asset_count": len(verified_assets),
        },
    )
