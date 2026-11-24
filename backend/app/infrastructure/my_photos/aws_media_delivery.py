"""S3 media registration, availability and passenger-scoped delivery."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Literal, cast

from botocore.exceptions import ClientError

from app.application.my_photos.errors import MyPhotosUnavailable
from app.application.my_photos.providers import (
    DeliveryAuthorization,
    DeliveryRequest,
    DeliveryResolution,
    DeliveryResolutionRequest,
    MediaAvailabilityRequest,
    MediaAvailabilityResult,
    MediaDeletionRequest,
    MediaDeletionResult,
    MediaPreparationRequest,
    MediaRegistrationRequest,
    MediaRegistrationResult,
)
from app.application.my_photos.states import (
    MEDIA_DELIVERY_READY_STATES,
    MEDIA_PREPARING_STATES,
)
from app.infrastructure.my_photos.aws_client_runtime import (
    _NOT_FOUND_CODES,
    _as_utc,
    _async_client_call,
    _client_error_code,
    _mapping_epoch,
    _mapping_text,
    _raise_provider_failure,
    _utcnow,
)
from app.infrastructure.my_photos.aws_media_location import (
    _validated_presigned_media_location,
)
from app.infrastructure.my_photos.aws_media_metadata import (
    _media_metadata,
    _MediaMetadata,
    _MediaObjectNotFound,
    _require_media_integrity,
)
from app.infrastructure.my_photos.aws_provider_config import (
    AwsMyPhotosProviderConfig,
)
from app.infrastructure.my_photos.aws_references import (
    _decode_versioned_media_reference,
    _delivery_fingerprint,
    _encode_versioned_media_reference,
    _OpaqueReferenceCodec,
    media_object_reference,
)


class S3DirectMediaDeliveryProvider:
    """Exact-version S3 media metadata, authorization, resolution, and deletion."""

    def __init__(
        self,
        *,
        s3_client: Any,
        config: AwsMyPhotosProviderConfig,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if config.media_bucket is None:
            raise ValueError("S3 media bucket is required")
        if config.media_kms_key_id is None:
            raise ValueError("S3 media KMS key is required")
        self._s3 = s3_client
        self._config = config
        self._codec = _OpaqueReferenceCodec(
            config.reference_active_key_id,
            config.reference_signing_keys,
            maximum_reference_length=4_096,
        )
        self._clock = clock or _utcnow

    @property
    def ready(self) -> bool:
        return True

    def object_reference(
        self,
        *,
        tenant_scope: str,
        group_scope: str,
        asset_identity: str,
        variant: Literal["thumbnail", "preview", "analysis", "original", "optimized"],
    ) -> str:
        return media_object_reference(
            self._config,
            tenant_scope=tenant_scope,
            group_scope=group_scope,
            asset_identity=asset_identity,
            variant=variant,
        )

    async def register(self, request: MediaRegistrationRequest) -> MediaRegistrationResult:
        expected = self.object_reference(
            tenant_scope=request.tenant_scope,
            group_scope=request.group_scope,
            asset_identity=request.asset_identity,
            variant="original",
        )
        if request.archive_reference != expected:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_MEDIA_SCOPE_INVALID", "Photo storage reference is invalid."
            )
        metadata = await self._head(expected)
        _require_media_integrity(
            metadata,
            expected_size=request.byte_size,
            expected_checksum=request.checksum_sha256,
            expected_content_type=request.mime_type,
            expected_width=request.width,
            expected_height=request.height,
        )
        return MediaRegistrationResult(
            storage_reference=_encode_versioned_media_reference(
                self._codec, expected, metadata.version_id
            ),
            availability_state="original_available_online",
            source_object_reference=expected,
        )

    async def prepare(self, request: MediaPreparationRequest) -> MediaAvailabilityResult:
        reference = self.object_reference(
            tenant_scope=request.tenant_scope,
            group_scope=request.group_scope,
            asset_identity=request.asset_identity,
            variant=request.variant,
        )
        return await self._availability(reference)

    async def availability(self, request: MediaAvailabilityRequest) -> MediaAvailabilityResult:
        reference = self.object_reference(
            tenant_scope=request.tenant_scope,
            group_scope=request.group_scope,
            asset_identity=request.asset_identity,
            variant=request.variant,
        )
        return await self._availability(reference)

    async def authorize(self, request: DeliveryRequest) -> DeliveryAuthorization:
        if request.availability_state not in MEDIA_DELIVERY_READY_STATES:
            return DeliveryAuthorization(
                state=(
                    "preparing_delivery"
                    if request.availability_state in MEDIA_PREPARING_STATES
                    else "failed"
                ),
                provider_authorization_reference=None,
                expected_size_bytes=None,
                checksum_sha256=None,
                supports_ranges=False,
                expires_at=None,
                content_type=None,
                transport="unavailable",
            )
        expected = self.object_reference(
            tenant_scope=request.tenant_scope,
            group_scope=request.group_scope,
            asset_identity=request.asset_identity,
            variant=request.quality,
        )
        try:
            media_key, media_version = _decode_versioned_media_reference(
                self._codec,
                request.media_reference,
                config=self._config,
                tenant_scope=request.tenant_scope,
                group_scope=request.group_scope,
            )
        except ValueError as exc:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_MEDIA_SCOPE_INVALID", "Photo delivery is unavailable."
            ) from exc
        if media_key != expected or request.content_type is None:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_MEDIA_SCOPE_INVALID", "Photo delivery is unavailable."
            )
        metadata = await self._head(media_key, version_id=media_version)
        _require_media_integrity(
            metadata,
            expected_size=request.expected_size_bytes,
            expected_checksum=request.checksum_sha256,
            expected_content_type=request.content_type,
        )
        now = self._clock()
        expires_at = now + timedelta(seconds=self._config.delivery_authorization_ttl_seconds)
        fingerprint = _delivery_fingerprint(
            request.tenant_scope,
            request.group_scope,
            request.passenger_scope,
            request.authorization_identity,
            request.asset_identity,
            request.media_reference,
            request.quality,
            request.expected_size_bytes,
            request.checksum_sha256,
            request.content_type,
        )
        provider_reference = self._codec.encode(
            "dl",
            {"e": int(expires_at.timestamp()), "f": fingerprint},
        )
        return DeliveryAuthorization(
            state="delivery_available",
            provider_authorization_reference=provider_reference,
            expected_size_bytes=request.expected_size_bytes,
            checksum_sha256=request.checksum_sha256,
            supports_ranges=True,
            expires_at=expires_at,
            content_type=request.content_type,
            transport="direct_object_storage",
        )

    async def resolve(self, request: DeliveryResolutionRequest) -> DeliveryResolution:
        expected_fingerprint = _delivery_fingerprint(
            request.tenant_scope,
            request.group_scope,
            request.passenger_scope,
            request.authorization_identity,
            request.asset_identity,
            request.media_reference,
            request.quality,
            request.expected_size_bytes,
            request.checksum_sha256,
            request.content_type,
        )
        try:
            decoded = self._codec.decode(request.provider_authorization_reference, "dl")
            token_expiry = _mapping_epoch(decoded, "e")
            fingerprint = _mapping_text(decoded, "f", maximum=64)
        except ValueError as exc:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_DELIVERY_AUTHORIZATION_INVALID",
                "Photo download authorization is invalid.",
            ) from exc
        expiry = min(token_expiry, _as_utc(request.expires_at))
        now = self._clock()
        if fingerprint != expected_fingerprint or expiry <= now:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_DELIVERY_EXPIRED", "Photo download authorization expired."
            )
        try:
            media_key, media_version = _decode_versioned_media_reference(
                self._codec,
                request.media_reference,
                config=self._config,
                tenant_scope=request.tenant_scope,
                group_scope=request.group_scope,
            )
        except ValueError as exc:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_DELIVERY_AUTHORIZATION_INVALID",
                "Photo download authorization is invalid.",
            ) from exc
        expected_key = self.object_reference(
            tenant_scope=request.tenant_scope,
            group_scope=request.group_scope,
            asset_identity=request.asset_identity,
            variant=request.quality,
        )
        if media_key != expected_key:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_DELIVERY_AUTHORIZATION_INVALID",
                "Photo download authorization is invalid.",
            )
        metadata = await self._head(media_key, version_id=media_version)
        _require_media_integrity(
            metadata,
            expected_size=request.expected_size_bytes,
            expected_checksum=request.checksum_sha256,
            expected_content_type=request.content_type,
        )
        parameters: dict[str, object] = {
            "Bucket": cast(str, self._config.media_bucket),
            "Key": media_key,
            "VersionId": media_version,
            "ResponseContentType": request.content_type,
        }
        if self._config.expected_bucket_owner is not None:
            parameters["ExpectedBucketOwner"] = self._config.expected_bucket_owner
        try:
            location = await _async_client_call(self._sign_delivery_location, parameters, expiry)
        except ClientError as exc:
            _raise_provider_failure(exc, operation="Photo delivery")
        now = self._clock()
        if expiry <= now:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_DELIVERY_EXPIRED", "Photo download authorization expired."
            )
        location = _validated_presigned_media_location(
            location,
            config=self._config,
            media_key=media_key,
            expires_at=expiry,
            now=now,
        )
        return DeliveryResolution(
            location=location,
            expires_at=expiry,
            supports_ranges=True,
        )

    def _sign_delivery_location(self, parameters: dict[str, object], expiry: datetime) -> str:
        # Storage lookup, thread dispatch and credential refresh consume the same
        # absolute authorization window; do not restart it when signing begins.
        remaining = math.floor((expiry - self._clock()).total_seconds())
        if remaining < 1:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_DELIVERY_EXPIRED", "Photo download authorization expired."
            )
        return cast(
            str,
            self._s3.generate_presigned_url(
                "get_object",
                Params=parameters,
                ExpiresIn=min(remaining, self._config.delivery_authorization_ttl_seconds),
                HttpMethod="GET",
            ),
        )

    async def delete(self, request: MediaDeletionRequest) -> MediaDeletionResult:
        references = tuple(dict.fromkeys(request.media_references))
        if not references or len(references) > 100:
            raise ValueError("Media deletion batch is outside the bounded contract")
        decoded_references: list[tuple[str, str, str]] = []
        for reference in references:
            try:
                key, version = _decode_versioned_media_reference(
                    self._codec,
                    reference,
                    config=self._config,
                    tenant_scope=request.tenant_scope,
                    group_scope=request.group_scope,
                )
            except ValueError as exc:
                raise MyPhotosUnavailable(
                    "MY_PHOTOS_MEDIA_SCOPE_INVALID", "Photo storage reference is invalid."
                ) from exc
            decoded_references.append((reference, key, version))
        deleted: list[str] = []
        not_found: list[str] = []
        for reference, key, version in decoded_references:
            try:
                await _async_client_call(
                    self._s3.delete_object,
                    **self._object_parameters(key, version_id=version),
                )
            except ClientError as exc:
                if _client_error_code(exc) in _NOT_FOUND_CODES:
                    not_found.append(reference)
                    continue
                _raise_provider_failure(exc, operation="Photo deletion")
            deleted.append(reference)
        return MediaDeletionResult(
            deleted_references=tuple(deleted),
            not_found_references=tuple(not_found),
        )

    async def _availability(self, reference: str) -> MediaAvailabilityResult:
        try:
            metadata = await self._head(reference)
        except _MediaObjectNotFound:
            return MediaAvailabilityResult(
                state="preparing_delivery",
                byte_size=None,
                checksum_sha256=None,
                delivery_version=1,
            )
        return MediaAvailabilityResult(
            state="delivery_available",
            byte_size=metadata.size,
            checksum_sha256=metadata.checksum,
            delivery_version=metadata.delivery_version,
            storage_reference=_encode_versioned_media_reference(
                self._codec, reference, metadata.version_id
            ),
            content_type=cast(Any, metadata.content_type),
            width=metadata.width,
            height=metadata.height,
            source_object_reference=reference,
        )

    async def _head(self, reference: str, *, version_id: str | None = None) -> _MediaMetadata:
        try:
            parameters = self._object_parameters(reference, version_id=version_id)
            parameters["ChecksumMode"] = "ENABLED"
            response = await _async_client_call(
                self._s3.head_object,
                **parameters,
            )
        except ClientError as exc:
            if _client_error_code(exc) in _NOT_FOUND_CODES:
                raise _MediaObjectNotFound from None
            _raise_provider_failure(exc, operation="Photo storage")
        return _media_metadata(
            response,
            expected_kms_key_id=cast(str, self._config.media_kms_key_id),
            expected_version_id=version_id,
        )

    def _object_parameters(
        self, reference: str, *, version_id: str | None = None
    ) -> dict[str, object]:
        parameters: dict[str, object] = {
            "Bucket": cast(str, self._config.media_bucket),
            "Key": reference,
        }
        if version_id is not None:
            parameters["VersionId"] = version_id
        if self._config.expected_bucket_owner is not None:
            parameters["ExpectedBucketOwner"] = self._config.expected_bucket_owner
        return parameters
