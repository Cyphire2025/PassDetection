"""Durable photo operation index jobs."""

from __future__ import annotations

import asyncio
from typing import cast

from sqlalchemy import select

from app.application.my_photos.errors import MyPhotosUnavailable
from app.application.my_photos.providers import FaceIndexAsset, FaceIndexBatchRequest
from app.core.config.settings import Settings
from app.infrastructure.database.my_photos_models import (
    MyPhotoGalleryManifestModel,
    MyPhotoGalleryModel,
    MyPhotoMediaAssetModel,
)
from app.infrastructure.my_photos.operational_index_publication import (
    _finalize_index_batch,
    _publish_index_if_complete,
)
from app.infrastructure.my_photos.operational_job_contracts import (
    OperationalJobResult,
    OperationalWorkerContext,
    _OperationalClaim,
)
from app.infrastructure.my_photos.operational_job_lifecycle import _retry_or_fail, _terminal_claim
from app.infrastructure.my_photos.operational_job_policy import _validated_index_result
from app.infrastructure.my_photos.operational_job_queries import _latest_ready_analysis_variants
from app.infrastructure.my_photos.providers import MyPhotosProviderBundle


async def _execute_index_batch(
    ctx: OperationalWorkerContext,
    claim: _OperationalClaim,
    settings: Settings,
    providers: MyPhotosProviderBundle,
) -> OperationalJobResult:
    if claim.target_revision is None:
        return await _terminal_claim(ctx, claim, "INDEX_REVISION_MISSING")
    checkpoint_rank = int(claim.checkpoint_cursor or "-1")
    async with ctx.session_factory() as session:
        gallery = (
            await session.execute(
                select(MyPhotoGalleryModel).where(
                    MyPhotoGalleryModel.id == claim.gallery_id,
                    MyPhotoGalleryModel.agency_id == claim.agency_id,
                    MyPhotoGalleryModel.group_id == claim.group_id,
                )
            )
        ).scalar_one_or_none()
        if gallery is None:
            return await _terminal_claim(ctx, claim, "INDEX_COLLECTION_MISSING")
        if providers.provider_name == "aws":
            manifest = (
                await session.execute(
                    select(MyPhotoGalleryManifestModel).where(
                        MyPhotoGalleryManifestModel.gallery_id == claim.gallery_id,
                        MyPhotoGalleryManifestModel.agency_id == claim.agency_id,
                        MyPhotoGalleryManifestModel.group_id == claim.group_id,
                        MyPhotoGalleryManifestModel.manifest_identity == claim.idempotency_key,
                        MyPhotoGalleryManifestModel.target_revision == claim.target_revision,
                        MyPhotoGalleryManifestModel.content_fingerprint
                        == claim.request_fingerprint,
                        MyPhotoGalleryManifestModel.status == "indexing",
                    )
                )
            ).scalar_one_or_none()
            if manifest is None:
                return await _terminal_claim(ctx, claim, "INDEX_MANIFEST_INVALID")
            collection_reference = manifest.provider_collection_reference
            index_version = manifest.target_revision
        else:
            if gallery.provider_collection_reference is None:
                return await _terminal_claim(ctx, claim, "INDEX_COLLECTION_MISSING")
            collection_reference = gallery.provider_collection_reference
            index_version = gallery.face_index_version
        assets = list(
            (
                await session.execute(
                    select(MyPhotoMediaAssetModel)
                    .where(
                        MyPhotoMediaAssetModel.gallery_id == claim.gallery_id,
                        MyPhotoMediaAssetModel.agency_id == claim.agency_id,
                        MyPhotoMediaAssetModel.group_id == claim.group_id,
                        MyPhotoMediaAssetModel.published_revision == claim.target_revision,
                        MyPhotoMediaAssetModel.sort_rank > checkpoint_rank,
                        MyPhotoMediaAssetModel.processing_state.notin_(("failed", "removed")),
                    )
                    .order_by(MyPhotoMediaAssetModel.sort_rank, MyPhotoMediaAssetModel.id)
                    .limit(settings.my_photos.job_batch_size)
                )
            ).scalars()
        )
    if not assets:
        return await _publish_index_if_complete(ctx, claim, settings)
    async with ctx.session_factory() as session:
        analysis_variants = await _latest_ready_analysis_variants(
            session, assets=assets, agency_id=claim.agency_id, group_id=claim.group_id
        )
    if len(analysis_variants) != len(assets):
        return await _retry_or_fail(ctx, claim, settings, "INDEX_ANALYSIS_NOT_READY")
    request_assets = tuple(
        (
            FaceIndexAsset(
                asset_identity=asset.immutable_asset_key,
                analysis_media_reference=cast(str, analysis_variants[asset.id].storage_reference),
                idempotency_identity=f"index:{claim.gallery_id}:{index_version}:{asset.id}",
            )
            for asset in assets
        )
    )
    try:
        async with asyncio.timeout(settings.my_photos.face_search_provider_timeout_seconds):
            raw_result = await providers.face_search.index_faces(
                FaceIndexBatchRequest(
                    tenant_scope=str(claim.agency_id),
                    group_scope=str(claim.group_id),
                    collection_reference=collection_reference,
                    index_version=index_version,
                    assets=request_assets,
                )
            )
        result = _validated_index_result(raw_result, request_assets)
    except (MyPhotosUnavailable, TimeoutError):
        return await _retry_or_fail(ctx, claim, settings, "INDEX_PROVIDER_UNAVAILABLE")
    except (ValueError, TypeError):
        return await _terminal_claim(ctx, claim, "INDEX_PROVIDER_RESULT_INVALID")
    except Exception:
        return await _retry_or_fail(ctx, claim, settings, "INDEX_PROVIDER_UNAVAILABLE")
    return await _finalize_index_batch(ctx, claim, assets, result, settings)
