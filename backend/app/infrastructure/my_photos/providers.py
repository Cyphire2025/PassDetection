"""Fail-closed and deterministic trusted-environment My Photos adapters."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

import boto3
from botocore.config import Config as BotoConfig

from app.application.my_photos.errors import MyPhotosUnavailable
from app.application.my_photos.providers import (
    CanonicalFaceBox,
    DeliveryAuthorization,
    DeliveryRequest,
    DeliveryResolution,
    DeliveryResolutionRequest,
    FaceCollectionDeletionResult,
    FaceCollectionRequest,
    FaceCollectionResult,
    FaceDeletionRequest,
    FaceDeletionResult,
    FaceIndexBatchRequest,
    FaceIndexBatchResult,
    FaceIndexFailure,
    FaceIndexSearchProvider,
    FaceSearchRequest,
    FaceSearchResult,
    IndexedFaceOccurrence,
    LivenessProvider,
    LivenessResult,
    LivenessSessionHandle,
    LivenessSessionRequest,
    MediaAvailabilityRequest,
    MediaAvailabilityResult,
    MediaDeletionRequest,
    MediaDeletionResult,
    MediaDeliveryProvider,
    MediaPreparationRequest,
    MediaRegistrationRequest,
    MediaRegistrationResult,
    ProviderFaceMatch,
    ReferenceDeletionRequest,
    ReferenceDeletionResult,
)
from app.application.my_photos.states import (
    MEDIA_DELIVERY_READY_STATES,
    MEDIA_PREPARING_STATES,
)
from app.infrastructure.my_photos.aws_providers import (
    AwsRekognitionFaceIndexSearchProvider,
    AwsRekognitionLivenessProvider,
    S3DirectMediaDeliveryProvider,
    aws_provider_config,
)
from app.infrastructure.my_photos.synthetic_media import (
    synthetic_media_checksum,
    synthetic_media_dimensions,
)
from app.infrastructure.my_photos.telemetry import my_photos_metrics

if TYPE_CHECKING:
    from app.core.config.settings import Settings

DevelopmentScenario = Literal[
    "success",
    "rejected",
    "expired",
    "cancelled",
    "throttled",
    "unavailable",
    "no_face",
    "multiple_faces",
    "no_matches",
    "partial_matches",
]

_DEVELOPMENT_NAMESPACE = uuid.UUID("3bf1023e-9ccd-4bcc-8795-196692ba7d32")


class DisabledLivenessProvider:
    @property
    def ready(self) -> bool:
        return False

    @property
    def client_flow(self) -> Literal["unavailable"]:
        return "unavailable"

    async def create_session(self, request: LivenessSessionRequest) -> LivenessSessionHandle:
        del request
        my_photos_metrics.provider("unavailable")
        raise MyPhotosUnavailable(
            "MY_PHOTOS_PROVIDER_NOT_CONFIGURED", "Face Scan is not available yet."
        )

    async def get_result(self, provider_reference: str) -> LivenessResult:
        del provider_reference
        my_photos_metrics.provider("unavailable")
        raise MyPhotosUnavailable(
            "MY_PHOTOS_PROVIDER_NOT_CONFIGURED", "Face Scan is not available yet."
        )

    async def delete_reference(self, request: ReferenceDeletionRequest) -> ReferenceDeletionResult:
        del request
        my_photos_metrics.provider("unavailable")
        raise MyPhotosUnavailable(
            "MY_PHOTOS_PROVIDER_NOT_CONFIGURED",
            "Face Scan deletion is temporarily unavailable.",
        )


class DisabledFaceSearchProvider:
    @property
    def ready(self) -> bool:
        return False

    def collection_reference(self, *, tenant_scope: str, group_scope: str) -> str:
        del tenant_scope, group_scope
        raise MyPhotosUnavailable(
            "MY_PHOTOS_PROVIDER_NOT_CONFIGURED", "Face indexing is not available yet."
        )

    async def ensure_collection(self, request: FaceCollectionRequest) -> FaceCollectionResult:
        del request
        raise MyPhotosUnavailable(
            "MY_PHOTOS_PROVIDER_NOT_CONFIGURED", "Face indexing is not available yet."
        )

    async def index_faces(self, request: FaceIndexBatchRequest) -> FaceIndexBatchResult:
        del request
        my_photos_metrics.provider("unavailable")
        raise MyPhotosUnavailable(
            "MY_PHOTOS_PROVIDER_NOT_CONFIGURED", "Face indexing is not available yet."
        )

    async def search(self, request: FaceSearchRequest) -> FaceSearchResult:
        del request
        my_photos_metrics.provider("unavailable")
        raise MyPhotosUnavailable(
            "MY_PHOTOS_PROVIDER_NOT_CONFIGURED", "Face search is not available yet."
        )

    async def delete_faces(self, request: FaceDeletionRequest) -> FaceDeletionResult:
        del request
        raise MyPhotosUnavailable(
            "MY_PHOTOS_PROVIDER_NOT_CONFIGURED", "Face deletion is not available yet."
        )

    async def delete_collection(
        self, request: FaceCollectionRequest
    ) -> FaceCollectionDeletionResult:
        del request
        raise MyPhotosUnavailable(
            "MY_PHOTOS_PROVIDER_NOT_CONFIGURED", "Face deletion is not available yet."
        )


class DisabledMediaDeliveryProvider:
    @property
    def ready(self) -> bool:
        return False

    async def register(self, request: MediaRegistrationRequest) -> MediaRegistrationResult:
        del request
        my_photos_metrics.provider("unavailable")
        raise MyPhotosUnavailable(
            "MY_PHOTOS_MEDIA_NOT_CONFIGURED", "Photo storage is not available yet."
        )

    async def prepare(self, request: MediaPreparationRequest) -> MediaAvailabilityResult:
        del request
        my_photos_metrics.provider("unavailable")
        raise MyPhotosUnavailable(
            "MY_PHOTOS_MEDIA_NOT_CONFIGURED", "Photo preparation is not available yet."
        )

    async def availability(self, request: MediaAvailabilityRequest) -> MediaAvailabilityResult:
        del request
        my_photos_metrics.provider("unavailable")
        raise MyPhotosUnavailable(
            "MY_PHOTOS_MEDIA_NOT_CONFIGURED", "Photo availability is not available yet."
        )

    async def authorize(self, request: DeliveryRequest) -> DeliveryAuthorization:
        del request
        my_photos_metrics.provider("unavailable")
        raise MyPhotosUnavailable(
            "MY_PHOTOS_MEDIA_NOT_CONFIGURED", "Photo delivery is not available yet."
        )

    async def resolve(self, request: DeliveryResolutionRequest) -> DeliveryResolution:
        del request
        raise MyPhotosUnavailable(
            "MY_PHOTOS_MEDIA_NOT_CONFIGURED", "Photo delivery is not available yet."
        )

    async def delete(self, request: MediaDeletionRequest) -> MediaDeletionResult:
        del request
        raise MyPhotosUnavailable(
            "MY_PHOTOS_MEDIA_NOT_CONFIGURED", "Photo deletion is not available yet."
        )


class DevelopmentLivenessProvider:
    """Lifecycle simulator; it does not perform liveness or biometric recognition."""

    def __init__(self, *, scenario: DevelopmentScenario, app_env: str) -> None:
        _require_local_development(app_env)
        self._scenario = scenario

    @property
    def ready(self) -> bool:
        return True

    @property
    def client_flow(self) -> Literal["development_simulator"]:
        return "development_simulator"

    async def create_session(self, request: LivenessSessionRequest) -> LivenessSessionHandle:
        if self._scenario == "unavailable":
            my_photos_metrics.provider("unavailable")
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_UNAVAILABLE", "Face Scan is temporarily unavailable."
            )
        if self._scenario == "throttled":
            my_photos_metrics.provider("throttled")
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_THROTTLED", "Face Scan is busy. Try again shortly."
            )
        seed = "|".join(
            (
                request.tenant_scope,
                request.group_scope,
                request.passenger_scope,
                request.session_identity,
                request.challenge_mode,
            )
        )
        handle = uuid.uuid5(_DEVELOPMENT_NAMESPACE, seed).hex
        return LivenessSessionHandle(
            provider_reference=f"dev-liveness:{handle}", expires_at=request.expires_at
        )

    async def get_result(self, provider_reference: str) -> LivenessResult:
        if not provider_reference.startswith("dev-liveness:"):
            return LivenessResult(
                outcome="failed", retryable=False, stable_error_code="PROVIDER_SESSION_INVALID"
            )
        if self._scenario == "success" or self._scenario in {
            "no_matches",
            "partial_matches",
        }:
            digest = hashlib.sha256(provider_reference.encode("utf-8")).hexdigest()
            return LivenessResult(outcome="passed", reference_face_handle=f"dev-reference:{digest}")
        outcomes: dict[DevelopmentScenario, tuple[str, bool, str]] = {
            "rejected": ("rejected", True, "LIVENESS_REJECTED"),
            "expired": ("expired", True, "SESSION_EXPIRED"),
            "cancelled": ("failed", True, "SESSION_CANCELLED"),
            "throttled": ("throttled", True, "PROVIDER_THROTTLED"),
            "unavailable": ("unavailable", True, "PROVIDER_UNAVAILABLE"),
            "no_face": ("no_face", True, "NO_FACE"),
            "multiple_faces": ("multiple_faces", True, "MULTIPLE_FACES"),
        }
        outcome, retryable, error_code = outcomes[self._scenario]
        return LivenessResult(
            outcome=outcome,  # type: ignore[arg-type]
            retryable=retryable,
            stable_error_code=error_code,
        )

    async def delete_reference(self, request: ReferenceDeletionRequest) -> ReferenceDeletionResult:
        if not request.provider_reference.startswith("dev-reference:"):
            return ReferenceDeletionResult(outcome="not_found")
        # Deterministic no-op: the simulator retains no biometric content or
        # mutable provider-side record, while exercising the real deletion contract.
        return ReferenceDeletionResult(outcome="deleted")


class DevelopmentFaceSearchProvider:
    """Repeatable metadata-only search over pre-indexed synthetic face references."""

    def __init__(self, *, scenario: DevelopmentScenario, app_env: str) -> None:
        _require_local_development(app_env)
        self._scenario = scenario

    @property
    def ready(self) -> bool:
        return True

    def collection_reference(self, *, tenant_scope: str, group_scope: str) -> str:
        del tenant_scope
        return f"dev-collection:{group_scope}"

    async def ensure_collection(self, request: FaceCollectionRequest) -> FaceCollectionResult:
        expected = self.collection_reference(
            tenant_scope=request.tenant_scope,
            group_scope=request.group_scope,
        )
        if request.collection_reference != expected:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_COLLECTION_SCOPE_INVALID", "Face collection is unavailable."
            )
        return FaceCollectionResult(
            collection_reference=expected,
            provider_model_version="development-metadata-v1",
        )

    async def index_faces(self, request: FaceIndexBatchRequest) -> FaceIndexBatchResult:
        if not request.assets or len(request.assets) > 500:
            return FaceIndexBatchResult(
                occurrences=(),
                failures=tuple(
                    FaceIndexFailure(
                        asset_identity=asset.asset_identity,
                        stable_error_code="INDEX_BATCH_INVALID",
                    )
                    for asset in request.assets[:500]
                ),
            )
        occurrences: list[IndexedFaceOccurrence] = []
        for asset in request.assets:
            index_text = asset.asset_identity.removeprefix("dev-asset-")
            if len(index_text) != 5 or not index_text.isdigit():
                return FaceIndexBatchResult(
                    occurrences=tuple(occurrences),
                    failures=(
                        FaceIndexFailure(
                            asset_identity=asset.asset_identity,
                            stable_error_code="ASSET_IDENTITY_INVALID",
                        ),
                    ),
                )
            asset_index = int(index_text)
            face_count = 2 if asset_index % 5 == 0 else 1
            for position in range(face_count):
                occurrence_identity = f"{asset.idempotency_identity}:{position}"
                suffix = "primary" if position == 0 else "secondary"
                occurrences.append(
                    IndexedFaceOccurrence(
                        asset_identity=asset.asset_identity,
                        provider_face_reference=(f"dev-face-{asset_index:05d}-{suffix}"),
                        bounding_box=CanonicalFaceBox(
                            left=0.15 + (position * 0.35),
                            top=0.2,
                            width=0.25,
                            height=0.35,
                        ),
                        quality_score=90.0 - position,
                        provider_model_version="development-metadata-v1",
                        idempotency_identity=occurrence_identity,
                    )
                )
        return FaceIndexBatchResult(occurrences=tuple(occurrences), failures=())

    async def search(self, request: FaceSearchRequest) -> FaceSearchResult:
        if self._scenario == "unavailable":
            my_photos_metrics.provider("unavailable")
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_UNAVAILABLE", "Face search is temporarily unavailable."
            )
        if self._scenario == "throttled":
            my_photos_metrics.provider("throttled")
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_THROTTLED", "Face search is busy. Try again shortly."
            )
        count = (
            0
            if self._scenario == "no_matches"
            else 12
            if self._scenario == "partial_matches"
            else 57
        )
        count = min(count, request.maximum_results)
        passenger_hash = int(
            hashlib.sha256(request.reference_face_handle.encode("utf-8")).hexdigest()[:8], 16
        )
        reference_digest = hashlib.sha256(request.reference_face_handle.encode("utf-8")).digest()
        shared_occurrence = "secondary" if reference_digest[1] & 0x80 else "primary"
        indices: list[int] = [0] if count else []
        candidate = (passenger_hash % 4_943) + 1
        while len(indices) < count:
            if candidate not in indices:
                indices.append(candidate)
            candidate = ((candidate + 71 - 1) % 4_999) + 1
        matches = tuple(
            ProviderFaceMatch(
                provider_face_reference=(
                    f"dev-face-{asset_index:05d}-{shared_occurrence}"
                    if position == 0 and asset_index == 0
                    else f"dev-face-{asset_index:05d}-primary"
                ),
                similarity=96.0 - (position * 0.12) if position < 41 else 88.0 - (position * 0.1),
            )
            for position, asset_index in enumerate(indices)
        )
        return FaceSearchResult(matches=matches, provider_model_version="development-metadata-v1")

    async def delete_faces(self, request: FaceDeletionRequest) -> FaceDeletionResult:
        expected = self.collection_reference(
            tenant_scope=request.tenant_scope,
            group_scope=request.group_scope,
        )
        if request.collection_reference != expected:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_COLLECTION_SCOPE_INVALID", "Face collection is unavailable."
            )
        return FaceDeletionResult(
            deleted_face_references=request.provider_face_references,
            not_found_face_references=(),
        )

    async def delete_collection(
        self, request: FaceCollectionRequest
    ) -> FaceCollectionDeletionResult:
        expected = self.collection_reference(
            tenant_scope=request.tenant_scope,
            group_scope=request.group_scope,
        )
        if request.collection_reference != expected:
            return FaceCollectionDeletionResult(outcome="not_found")
        return FaceCollectionDeletionResult(outcome="deleted")


class DevelopmentMediaDeliveryProvider:
    """Authorizes deterministic local fixture bytes; never contacts object storage."""

    def __init__(self, *, app_env: str, ttl_seconds: int) -> None:
        _require_local_development(app_env)
        self._ttl_seconds = ttl_seconds

    @property
    def ready(self) -> bool:
        return True

    async def register(self, request: MediaRegistrationRequest) -> MediaRegistrationResult:
        digest = hashlib.sha256(
            f"{request.group_scope}|{request.asset_identity}|{request.checksum_sha256}".encode()
        ).hexdigest()
        return MediaRegistrationResult(
            storage_reference=f"dev-media:{digest}",
            availability_state="registered",
        )

    async def prepare(self, request: MediaPreparationRequest) -> MediaAvailabilityResult:
        digest = int(hashlib.sha256(request.asset_identity.encode()).hexdigest()[:8], 16)
        if request.variant == "original" and digest % 17 == 0:
            return MediaAvailabilityResult(
                state="rehydration_requested",
                byte_size=None,
                checksum_sha256=None,
                delivery_version=1,
            )
        variant: Literal["thumbnail", "preview", "analysis", "original", "optimized"] = (
            request.variant
            if request.variant in {"thumbnail", "preview", "analysis", "original"}
            else "optimized"
        )
        size, checksum = synthetic_media_checksum(request.asset_identity, variant)
        width, height = synthetic_media_dimensions(variant)
        return MediaAvailabilityResult(
            state="delivery_available",
            byte_size=size,
            checksum_sha256=checksum,
            delivery_version=1,
            storage_reference=(
                f"development/{request.group_scope}/{request.asset_identity}/{variant}"
            ),
            content_type="image/png",
            width=width,
            height=height,
        )

    async def availability(self, request: MediaAvailabilityRequest) -> MediaAvailabilityResult:
        return await self.prepare(
            MediaPreparationRequest(
                tenant_scope=request.tenant_scope,
                group_scope=request.group_scope,
                asset_identity=request.asset_identity,
                variant=request.variant,
                idempotency_identity=f"availability:{request.asset_identity}:{request.variant}",
            )
        )

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
        variant: Literal["thumbnail", "preview", "original", "optimized"] = request.quality
        expected_size, checksum = synthetic_media_checksum(request.asset_identity, variant)
        expires_at = datetime.now(tz=UTC) + timedelta(seconds=self._ttl_seconds)
        digest = hashlib.sha256(
            f"{request.passenger_scope}|{request.authorization_identity}|{request.media_reference}|{request.quality}".encode()
        ).hexdigest()
        return DeliveryAuthorization(
            state="delivery_available",
            provider_authorization_reference=f"dev-delivery:{digest}",
            expected_size_bytes=expected_size,
            checksum_sha256=checksum,
            supports_ranges=True,
            expires_at=expires_at,
            content_type="image/png",
            transport="development_fixture",
        )

    async def resolve(self, request: DeliveryResolutionRequest) -> DeliveryResolution:
        del request
        raise MyPhotosUnavailable(
            "MY_PHOTOS_MEDIA_TRANSPORT_INVALID",
            "Development photo delivery uses the authenticated API stream.",
        )

    async def delete(self, request: MediaDeletionRequest) -> MediaDeletionResult:
        # The deterministic adapter owns no mutable objects, but returning the
        # requested bounded references exercises idempotent deletion callers.
        return MediaDeletionResult(
            deleted_references=request.media_references,
            not_found_references=(),
        )


@dataclass(frozen=True, slots=True)
class MyPhotosProviderBundle:
    liveness: LivenessProvider
    face_search: FaceIndexSearchProvider
    media: MediaDeliveryProvider
    provider_name: str


def build_provider_bundle(
    settings: Settings,
    *,
    rekognition_client: object | None = None,
    s3_client: object | None = None,
) -> MyPhotosProviderBundle:
    """Select providers from trusted server settings, with an independent environment guard."""

    config = settings.my_photos
    try:
        config.validate_runtime_environment(settings.app_env)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    any_development = "development" in {
        config.liveness_provider,
        config.face_search_provider,
        config.media_provider,
    }
    if any_development and settings.app_env != "development":
        raise RuntimeError("Development My Photos providers are forbidden outside development")

    any_aws = (
        "aws_rekognition"
        in {
            config.liveness_provider,
            config.face_search_provider,
        }
        or config.media_provider == "s3"
    )
    if any_aws and (
        config.liveness_provider,
        config.face_search_provider,
        config.media_provider,
    ) != ("aws_rekognition", "aws_rekognition", "s3"):
        raise RuntimeError("Incomplete production My Photos provider selection was rejected")

    liveness: LivenessProvider
    face_search: FaceIndexSearchProvider
    media: MediaDeliveryProvider
    if any_aws:
        client_config = BotoConfig(
            connect_timeout=config.aws_connect_timeout_seconds,
            read_timeout=config.aws_read_timeout_seconds,
            retries={"max_attempts": config.aws_max_attempts, "mode": "standard"},
            max_pool_connections=config.aws_max_pool_connections,
            signature_version="v4",
            s3={"addressing_style": config.aws_s3_addressing_style},
        )
        resolved_rekognition = rekognition_client or boto3.client(
            "rekognition",
            region_name=config.aws_region,
            config=client_config,
        )
        s3_arguments: dict[str, object] = {
            "region_name": config.aws_region,
            "config": client_config,
        }
        if config.aws_s3_endpoint_url is not None:
            s3_arguments["endpoint_url"] = config.aws_s3_endpoint_url
        resolved_s3 = s3_client or boto3.client("s3", **s3_arguments)
        aws_config = aws_provider_config(config)
        aws_liveness = AwsRekognitionLivenessProvider(
            rekognition_client=resolved_rekognition,
            s3_client=resolved_s3,
            config=aws_config,
        )
        liveness = aws_liveness
        face_search = AwsRekognitionFaceIndexSearchProvider(
            rekognition_client=resolved_rekognition,
            liveness_provider=aws_liveness,
            config=aws_config,
        )
        media = S3DirectMediaDeliveryProvider(
            s3_client=resolved_s3,
            config=aws_config,
        )
    elif config.liveness_provider == "development":
        liveness = DevelopmentLivenessProvider(
            scenario=config.development_scenario, app_env=settings.app_env
        )
    else:
        liveness = DisabledLivenessProvider()
    if not any_aws and config.face_search_provider == "development":
        face_search = DevelopmentFaceSearchProvider(
            scenario=config.development_scenario, app_env=settings.app_env
        )
    elif not any_aws:
        face_search = DisabledFaceSearchProvider()
    if not any_aws and config.media_provider == "development":
        media = DevelopmentMediaDeliveryProvider(
            app_env=settings.app_env,
            ttl_seconds=config.delivery_authorization_ttl_seconds,
        )
    elif not any_aws:
        media = DisabledMediaDeliveryProvider()
    provider_name = "aws" if any_aws else "development" if any_development else "disabled"
    return MyPhotosProviderBundle(
        liveness=liveness,
        face_search=face_search,
        media=media,
        provider_name=provider_name,
    )


def _require_local_development(app_env: str) -> None:
    if app_env != "development":
        raise RuntimeError("Development My Photos provider activation was rejected")
