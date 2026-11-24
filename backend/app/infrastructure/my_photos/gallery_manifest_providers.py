"""Gallery manifest providers owner."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.application.my_photos.errors import MyPhotosUnavailable
from app.application.my_photos.providers import (
    FaceCollectionRequest,
    MediaAvailabilityRequest,
    MediaAvailabilityResult,
    MediaRegistrationRequest,
)
from app.infrastructure.my_photos.gallery_manifest_context import GalleryManifestContext
from app.infrastructure.my_photos.gallery_manifest_contracts import (
    GalleryManifestAsset,
    GalleryManifestRequest,
    _VerifiedAsset,
)
from app.infrastructure.my_photos.gallery_manifest_fingerprints import _json_fingerprint
from app.infrastructure.my_photos.gallery_manifest_policy import (
    _require_variant_match,
    _valid_stable,
)
from app.infrastructure.my_photos.provider_tasks import gather_provider_results

_PROVIDER_CONCURRENCY = 4
_ProviderResultT = TypeVar("_ProviderResultT")


async def _ensure_collection(
    ctx: GalleryManifestContext, request: GalleryManifestRequest
) -> tuple[str, str]:
    if (
        ctx.providers.provider_name != "aws"
        or not ctx.providers.face_search.ready
        or (not ctx.providers.media.ready)
    ):
        raise MyPhotosUnavailable(
            "MY_PHOTOS_PROVIDER_NOT_CONFIGURED",
            "Production My Photos providers are not configured.",
        )
    collection_reference = ctx.providers.face_search.collection_reference(
        tenant_scope=str(request.agency_id), group_scope=str(request.group_id)
    )
    try:
        async with asyncio.timeout(ctx.settings.my_photos.face_search_provider_timeout_seconds):
            collection = await ctx.providers.face_search.ensure_collection(
                FaceCollectionRequest(
                    tenant_scope=str(request.agency_id),
                    group_scope=str(request.group_id),
                    collection_reference=collection_reference,
                )
            )
    except MyPhotosUnavailable:
        raise
    except Exception as exc:
        raise MyPhotosUnavailable(
            "MY_PHOTOS_PROVIDER_UNAVAILABLE",
            "Photo collection verification is temporarily unavailable.",
        ) from exc
    if collection.collection_reference != collection_reference or not _valid_stable(
        collection.provider_model_version, maximum=64
    ):
        raise MyPhotosUnavailable(
            "MY_PHOTOS_PROVIDER_RESULT_INVALID",
            "Photo collection verification returned an invalid result.",
        )
    return (collection_reference, collection.provider_model_version)


def _provider_configuration_fingerprint(ctx: GalleryManifestContext) -> str:
    config = ctx.settings.my_photos
    scope_secret = config.aws_scope_hmac_secret
    scope_secret_fingerprint = (
        hashlib.sha256(scope_secret.get_secret_value().encode("utf-8")).hexdigest()
        if scope_secret is not None
        else None
    )
    return _json_fingerprint(
        {
            "provider_bundle": ctx.providers.provider_name,
            "liveness_provider": config.liveness_provider,
            "face_search_provider": config.face_search_provider,
            "media_provider": config.media_provider,
            "match_config_version": config.match_config_version,
            "best_match_threshold": config.best_match_threshold,
            "possible_match_threshold": config.possible_match_threshold,
            "maximum_search_results": config.maximum_search_results,
            "aws_region": config.aws_region,
            "aws_media_bucket": config.aws_media_bucket,
            "aws_media_kms_key_id": config.aws_media_kms_key_id,
            "aws_media_key_prefix": config.aws_media_key_prefix,
            "aws_s3_endpoint_url": config.aws_s3_endpoint_url,
            "aws_s3_addressing_style": config.aws_s3_addressing_style,
            "aws_expected_bucket_owner": config.aws_expected_bucket_owner,
            "aws_collection_prefix": config.aws_collection_prefix,
            "aws_scope_hmac_secret_fingerprint": scope_secret_fingerprint,
            "aws_provider_hmac_key_id": config.aws_provider_hmac_key_id,
            "aws_provider_hmac_previous_key_ids": sorted(config.aws_provider_hmac_previous_keys),
            "aws_index_quality_filter": config.aws_index_quality_filter,
            "aws_index_max_faces_per_asset": config.aws_index_max_faces_per_asset,
            "aws_search_quality_filter": config.aws_search_quality_filter,
        }
    )


async def _verify_media(
    ctx: GalleryManifestContext, request: GalleryManifestRequest
) -> tuple[_VerifiedAsset, ...]:
    semaphore = asyncio.Semaphore(_PROVIDER_CONCURRENCY)

    async def call_provider(
        awaitable_factory: Callable[[], Awaitable[_ProviderResultT]],
    ) -> _ProviderResultT:
        async with semaphore:
            async with asyncio.timeout(ctx.settings.my_photos.media_provider_timeout_seconds):
                return await awaitable_factory()

    async def verify_asset(asset: GalleryManifestAsset) -> _VerifiedAsset:
        try:
            registered = await call_provider(
                lambda: ctx.providers.media.register(
                    MediaRegistrationRequest(
                        tenant_scope=str(request.agency_id),
                        group_scope=str(request.group_id),
                        asset_identity=asset.immutable_asset_key,
                        archive_reference=asset.archive_reference,
                        mime_type=asset.mime_type,
                        byte_size=asset.byte_size,
                        checksum_sha256=asset.checksum_sha256,
                        width=asset.width,
                        height=asset.height,
                        idempotency_identity=f"manifest:{request.manifest_identity}:{request.batch_index}:{asset.immutable_asset_key}",
                    )
                )
            )
            if (
                registered.storage_reference is None
                or registered.source_object_reference != asset.archive_reference
                or registered.availability_state != "original_available_online"
            ):
                raise ValueError("Original media registration result is invalid")
            results: dict[str, MediaAvailabilityResult] = {}
            for variant in asset.variants:
                availability_request = MediaAvailabilityRequest(
                    tenant_scope=str(request.agency_id),
                    group_scope=str(request.group_id),
                    asset_identity=asset.immutable_asset_key,
                    variant=variant.kind,
                )

                async def get_availability() -> MediaAvailabilityResult:
                    return await ctx.providers.media.availability(availability_request)

                provider_result = await call_provider(get_availability)
                _require_variant_match(variant, provider_result)
                results[variant.kind] = provider_result
            return _VerifiedAsset(
                asset=asset,
                original_storage_reference=registered.storage_reference,
                variants=results,
            )
        except MyPhotosUnavailable:
            raise
        except (TypeError, ValueError) as exc:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_MEDIA_INTEGRITY_CHANGED", "Photo storage integrity check failed."
            ) from exc
        except Exception as exc:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_UNAVAILABLE",
                "Photo storage verification is temporarily unavailable.",
            ) from exc

    return tuple(await gather_provider_results([verify_asset(asset) for asset in request.assets]))
