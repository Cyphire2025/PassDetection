"""Gallery manifest registration owner."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select

from app.application.my_photos.errors import MyPhotosConflict
from app.domain.entities.entities import User
from app.infrastructure.database.my_photos_models import (
    MyPhotoGalleryManifestModel,
    MyPhotoGalleryModel,
)
from app.infrastructure.my_photos.gallery_manifest_context import GalleryManifestContext
from app.infrastructure.my_photos.gallery_manifest_contracts import (
    GalleryManifestRequest,
    GalleryManifestResult,
)
from app.infrastructure.my_photos.gallery_manifest_finalization import finalize_manifest
from app.infrastructure.my_photos.gallery_manifest_persistence import _persist_batch_assets
from app.infrastructure.my_photos.gallery_manifest_policy import (
    _require_gallery_scope,
    _require_manifest_header,
    _require_operator,
)
from app.infrastructure.my_photos.gallery_manifest_providers import (
    _ensure_collection,
    _provider_configuration_fingerprint,
    _verify_media,
)
from app.infrastructure.my_photos.gallery_manifest_queries import (
    _load_scope,
    _locked_batch,
    _locked_gallery,
    _locked_manifest,
)
from app.infrastructure.my_photos.gallery_manifest_results import (
    _existing_batch_result,
    _result_for_manifest,
)


async def register_batch(
    ctx: GalleryManifestContext,
    *,
    actor: User,
    mfa_verified_at: datetime,
    request: GalleryManifestRequest,
    dispatch: Callable[[uuid.UUID], None],
) -> GalleryManifestResult:
    if ctx.session.in_transaction():
        raise RuntimeError("Manifest registration requires a fresh database session")
    _require_operator(actor, request.agency_id, mfa_verified_at)
    header_fingerprint = request.header_fingerprint(
        provider_configuration_fingerprint=_provider_configuration_fingerprint(ctx)
    )
    batch_fingerprint = request.batch_fingerprint()
    try:
        _group, access = await _load_scope(ctx, request, lock=False)
        access_id = access.id
        existing = await _existing_batch_result(
            ctx, request, header_fingerprint=header_fingerprint, batch_fingerprint=batch_fingerprint
        )
    finally:
        await ctx.session.rollback()
    if existing is not None:
        if request.finalize:
            return await finalize_manifest(
                ctx,
                actor=actor,
                mfa_verified_at=mfa_verified_at,
                request=request,
                dispatch=dispatch,
                batch_replay=True,
            )
        return existing
    collection_reference, provider_model_version = await _ensure_collection(ctx, request)
    verified_assets = await _verify_media(ctx, request)
    batch_replay = False
    async with ctx.session.begin():
        _locked_group, locked_access = await _load_scope(ctx, request, lock=True)
        if locked_access.id != access_id:
            raise MyPhotosConflict(
                "MY_PHOTOS_GALLERY_SCOPE_CHANGED",
                "The gallery scope changed while media was being verified.",
            )
        gallery = await _locked_gallery(ctx, request)
        if gallery is None:
            if request.target_revision != 1:
                raise MyPhotosConflict(
                    "MY_PHOTOS_GALLERY_REVISION_CONFLICT",
                    "The first gallery manifest must target revision one.",
                )
            gallery = MyPhotoGalleryModel(
                id=uuid.uuid4(),
                agency_id=request.agency_id,
                group_id=request.group_id,
                gc_group_access_id=locked_access.id,
                feature_enabled=True,
                status="processing",
                media_version=0,
                face_index_version=0,
                published_revision=0,
                total_asset_count=0,
                indexed_asset_count=0,
                failed_asset_count=0,
                all_group_photos_enabled=False,
                provider_collection_reference=None,
                provider_name=None,
                index_model_version=None,
                match_config_version="unconfigured",
                retention_policy_version="v1",
                retention_days=None,
                availability_starts_at=None,
                availability_ends_at=None,
            )
            ctx.session.add(gallery)
            await ctx.session.flush()
        _require_gallery_scope(
            gallery,
            request=request,
            access_id=locked_access.id,
            collection_reference=collection_reference,
        )
        manifest = await _locked_manifest(ctx, gallery.id, request.manifest_identity)
        if manifest is None:
            if gallery.published_revision + 1 != request.target_revision:
                raise MyPhotosConflict(
                    "MY_PHOTOS_GALLERY_REVISION_CONFLICT", "The gallery manifest revision is stale."
                )
            conflicting_manifest = (
                await ctx.session.execute(
                    select(MyPhotoGalleryManifestModel.id).where(
                        MyPhotoGalleryManifestModel.gallery_id == gallery.id,
                        MyPhotoGalleryManifestModel.target_revision == request.target_revision,
                        MyPhotoGalleryManifestModel.status != "cancelled",
                    )
                )
            ).scalar_one_or_none()
            if conflicting_manifest is not None:
                raise MyPhotosConflict(
                    "MY_PHOTOS_GALLERY_REVISION_CONFLICT",
                    "A different manifest already owns this gallery revision.",
                )
            manifest = MyPhotoGalleryManifestModel(
                id=uuid.uuid4(),
                gallery_id=gallery.id,
                agency_id=request.agency_id,
                group_id=request.group_id,
                manifest_identity=request.manifest_identity,
                target_revision=request.target_revision,
                header_fingerprint=header_fingerprint,
                content_fingerprint=None,
                total_asset_count=request.total_asset_count,
                batch_count=request.batch_count,
                received_asset_count=0,
                status="receiving",
                all_group_photos_enabled=request.all_group_photos_enabled,
                retention_policy_version=request.retention_policy_version,
                retention_days=request.retention_days,
                availability_starts_at=request.availability_starts_at,
                availability_ends_at=request.availability_ends_at,
                provider_collection_reference=collection_reference,
                provider_model_version=provider_model_version,
                match_config_version=ctx.settings.my_photos.match_config_version,
                created_by_user_id=actor.id,
            )
            ctx.session.add(manifest)
            await ctx.session.flush()
        else:
            _require_manifest_header(manifest, request, header_fingerprint)
            if manifest.cancellation_requested_at is not None:
                raise MyPhotosConflict(
                    "MY_PHOTOS_MANIFEST_CANCELLATION_PENDING",
                    "This gallery manifest is being cancelled.",
                )
            if (
                manifest.provider_collection_reference != collection_reference
                or manifest.provider_model_version != provider_model_version
            ):
                raise MyPhotosConflict(
                    "MY_PHOTOS_MANIFEST_PROVIDER_CONFLICT",
                    "The manifest provider version changed between batches.",
                )
            if manifest.status != "receiving":
                raise MyPhotosConflict(
                    "MY_PHOTOS_MANIFEST_FINALIZED",
                    "This gallery manifest no longer accepts batches.",
                )
        batch = await _locked_batch(ctx, manifest.id, request.batch_index)
        if batch is not None:
            if batch.batch_fingerprint != batch_fingerprint:
                raise MyPhotosConflict(
                    "MY_PHOTOS_MANIFEST_BATCH_CONFLICT",
                    "The manifest batch index was already used for different input.",
                )
            batch_replay = True
        else:
            await _persist_batch_assets(
                ctx,
                request=request,
                gallery=gallery,
                manifest=manifest,
                verified_assets=verified_assets,
                batch_fingerprint=batch_fingerprint,
                actor=actor,
            )
        result = await _result_for_manifest(
            ctx, manifest, batch_replay=batch_replay, manifest_replay=False
        )
    if request.finalize:
        return await finalize_manifest(
            ctx,
            actor=actor,
            mfa_verified_at=mfa_verified_at,
            request=request,
            dispatch=dispatch,
            batch_replay=batch_replay,
        )
    return result
