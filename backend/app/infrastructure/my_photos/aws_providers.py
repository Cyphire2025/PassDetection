"""Production AWS Rekognition and S3 adapters for My Photos.

The adapters accept already-constructed clients so tests and callers can keep
credential acquisition outside this module. The default factory uses boto3's
standard credential chain; no access key is accepted by My Photos settings or
placed in a mobile/API contract.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import math
import re
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, NoReturn, cast
from urllib.parse import unquote, urlsplit

from botocore.exceptions import ClientError

from app.application.my_photos.errors import MyPhotosUnavailable
from app.application.my_photos.limits import MAX_MY_PHOTOS_MEDIA_BYTES
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
    FaceIndexAsset,
    FaceIndexBatchRequest,
    FaceIndexBatchResult,
    FaceIndexFailure,
    FaceSearchRequest,
    FaceSearchResult,
    IndexedFaceOccurrence,
    LivenessResult,
    LivenessSessionHandle,
    LivenessSessionRequest,
    MediaAvailabilityRequest,
    MediaAvailabilityResult,
    MediaDeletionRequest,
    MediaDeletionResult,
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

_FACE_ID = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
_SESSION_ID = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
_CHECKSUM = re.compile(r"^[0-9a-f]{64}$")
_SUPPORTED_MIME = {"image/jpeg", "image/png", "image/webp"}
_THROTTLE_CODES = {
    "ThrottlingException",
    "ProvisionedThroughputExceededException",
    "SlowDown",
    "TooManyRequestsException",
}
_NOT_FOUND_CODES = {
    "404",
    "NoSuchKey",
    "NotFound",
    "ResourceNotFoundException",
    "SessionNotFoundException",
}
_PERMANENT_INDEX_FAILURES = {
    "ImageTooLargeException": "IMAGE_TOO_LARGE",
    "InvalidImageFormatException": "IMAGE_FORMAT_INVALID",
    "InvalidParameterException": "IMAGE_INVALID",
    "InvalidS3ObjectException": "MEDIA_OBJECT_INVALID",
}
_CHALLENGE_TYPES = {
    "movement_and_light": "FaceMovementAndLightChallenge",
    "movement_only": "FaceMovementChallenge",
}


@dataclass(frozen=True, slots=True)
class AwsMyPhotosProviderConfig:
    region: str
    liveness_output_bucket: str | None
    liveness_output_prefix: str
    liveness_kms_key_id: str | None
    liveness_audit_images_limit: int
    reference_frame_retention_seconds: int
    liveness_confidence_threshold: float
    media_bucket: str | None
    media_kms_key_id: str | None
    media_key_prefix: str
    expected_bucket_owner: str | None
    s3_endpoint_url: str | None
    s3_addressing_style: Literal["auto", "virtual", "path"]
    collection_prefix: str
    scope_hmac_secret: bytes
    reference_active_key_id: str
    reference_signing_keys: Mapping[str, bytes]
    possible_match_threshold: float
    index_quality_filter: str
    index_max_faces_per_asset: int
    index_concurrency: int
    search_quality_filter: str
    delivery_authorization_ttl_seconds: int


def aws_provider_config(settings: Any) -> AwsMyPhotosProviderConfig:
    """Translate validated My Photos settings without accepting AWS key material."""

    scope_secret = settings.aws_scope_hmac_secret
    active_key_id = settings.aws_provider_hmac_key_id
    active_secret = settings.aws_provider_hmac_secret
    if scope_secret is None:
        raise RuntimeError("My Photos AWS scope derivation secret is not configured")
    if active_key_id is None or active_secret is None:
        raise RuntimeError("My Photos AWS provider signing secret is not configured")
    scope_secret_value = scope_secret.get_secret_value()
    secret_value = active_secret.get_secret_value()
    if len(scope_secret_value) < 32 or len(secret_value) < 32:
        raise RuntimeError("My Photos AWS provider signing secret is invalid")
    signing_keys = {
        active_key_id: secret_value.encode("utf-8"),
        **{
            key_id: secret.get_secret_value().encode("utf-8")
            for key_id, secret in settings.aws_provider_hmac_previous_keys.items()
        },
    }
    return AwsMyPhotosProviderConfig(
        region=cast(str, settings.aws_region),
        liveness_output_bucket=settings.aws_liveness_output_bucket,
        liveness_output_prefix=settings.aws_liveness_output_prefix,
        liveness_kms_key_id=settings.aws_liveness_kms_key_id,
        liveness_audit_images_limit=settings.aws_liveness_audit_images_limit,
        reference_frame_retention_seconds=settings.reference_frame_retention_seconds,
        liveness_confidence_threshold=settings.liveness_confidence_threshold,
        media_bucket=settings.aws_media_bucket,
        media_kms_key_id=settings.aws_media_kms_key_id,
        media_key_prefix=settings.aws_media_key_prefix,
        expected_bucket_owner=settings.aws_expected_bucket_owner,
        s3_endpoint_url=settings.aws_s3_endpoint_url,
        s3_addressing_style=settings.aws_s3_addressing_style,
        collection_prefix=settings.aws_collection_prefix,
        scope_hmac_secret=scope_secret_value.encode("utf-8"),
        reference_active_key_id=active_key_id,
        reference_signing_keys=signing_keys,
        possible_match_threshold=settings.possible_match_threshold,
        index_quality_filter=settings.aws_index_quality_filter,
        index_max_faces_per_asset=settings.aws_index_max_faces_per_asset,
        index_concurrency=settings.aws_index_concurrency,
        search_quality_filter=settings.aws_search_quality_filter,
        delivery_authorization_ttl_seconds=settings.delivery_authorization_ttl_seconds,
    )


class _OpaqueReferenceCodec:
    def __init__(
        self,
        active_key_id: str,
        signing_keys: Mapping[str, bytes],
        *,
        maximum_reference_length: int = 512,
    ) -> None:
        if (
            active_key_id not in signing_keys
            or len(signing_keys) > 4
            or any(len(secret) < 32 for secret in signing_keys.values())
        ):
            raise ValueError("Provider reference key ring is invalid")
        self._active_key_id = active_key_id
        self._signing_keys = dict(signing_keys)
        self._maximum_reference_length = maximum_reference_length

    def encode(self, kind: str, values: Mapping[str, object]) -> str:
        payload = {"k": kind, "v": 1, **values}
        body = _b64url(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
        signature = _b64url(
            hmac.new(
                self._signing_keys[self._active_key_id],
                body.encode(),
                hashlib.sha256,
            ).digest()
        )
        reference = f"aw1.{self._active_key_id}.{body}.{signature}"
        if len(reference.encode("utf-8")) > self._maximum_reference_length:
            raise ValueError("Provider reference exceeds the persistence boundary")
        return reference

    def decode(self, reference: str, kind: str) -> dict[str, object]:
        if (
            not isinstance(reference, str)
            or len(reference.encode("utf-8")) > self._maximum_reference_length
        ):
            raise ValueError("Invalid opaque provider reference")
        try:
            prefix, key_id, body, signature = reference.split(".", 3)
            secret = self._signing_keys.get(key_id)
            if secret is None:
                raise ValueError
            expected = _b64url(hmac.new(secret, body.encode(), hashlib.sha256).digest())
            if prefix != "aw1" or not hmac.compare_digest(signature, expected):
                raise ValueError
            decoded = json.loads(_b64url_decode(body))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid opaque provider reference") from exc
        if not isinstance(decoded, dict) or decoded.get("v") != 1 or decoded.get("k") != kind:
            raise ValueError("Invalid opaque provider reference")
        return cast(dict[str, object], decoded)


class AwsRekognitionLivenessProvider:
    """Server-owned Face Liveness session creation and result verification."""

    def __init__(
        self,
        *,
        rekognition_client: Any,
        s3_client: Any,
        config: AwsMyPhotosProviderConfig,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if config.liveness_output_bucket is None:
            raise ValueError("Liveness output bucket is required")
        if config.liveness_kms_key_id is None:
            raise ValueError("Liveness output KMS key is required")
        if not 0 <= config.liveness_audit_images_limit <= 4:
            raise ValueError("Liveness audit-image limit is invalid")
        if config.reference_frame_retention_seconds <= 0:
            raise ValueError("Liveness reference retention must be explicit")
        self._rekognition = rekognition_client
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

    @property
    def client_flow(self) -> Literal["native"]:
        return "native"

    async def create_session(self, request: LivenessSessionRequest) -> LivenessSessionHandle:
        now = self._clock()
        requested_expiry = _as_utc(request.expires_at)
        expires_at = min(requested_expiry, now + timedelta(seconds=180))
        if expires_at <= now:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_SESSION_EXPIRED", "Face Scan session expired. Start again."
            )
        tenant_digest, group_digest = self._scope_digests(request.tenant_scope, request.group_scope)
        session_digest = hashlib.sha256(request.session_identity.encode()).hexdigest()[:32]
        key_prefix = (
            f"{self._config.liveness_output_prefix}/{tenant_digest}/{group_digest}/{session_digest}"
        )
        audit_limit = (
            self._config.liveness_audit_images_limit if request.audit_image_retention_enabled else 0
        )
        settings: dict[str, object] = {
            "OutputConfig": {
                "S3Bucket": cast(str, self._config.liveness_output_bucket),
                "S3KeyPrefix": key_prefix,
            },
            "AuditImagesLimit": audit_limit,
            "ChallengePreferences": [{"Type": _CHALLENGE_TYPES[request.challenge_mode]}],
        }
        parameters: dict[str, object] = {
            "Settings": settings,
            "ClientRequestToken": _aws_idempotency_token(request.session_identity),
        }
        parameters["KmsKeyId"] = self._config.liveness_kms_key_id
        try:
            response = await _async_client_call(
                self._rekognition.create_face_liveness_session,
                **parameters,
            )
        except ClientError as exc:
            _raise_provider_failure(exc, operation="Face Scan")
        session_id = _required_text(response, "SessionId", maximum=64)
        if _SESSION_ID.fullmatch(session_id) is None:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_RESULT_INVALID",
                "Face Scan is temporarily unavailable.",
            )
        provider_reference = self._codec.encode(
            "ls",
            {
                "a": tenant_digest,
                "e": int(expires_at.timestamp()),
                "g": group_digest,
                "p": key_prefix,
                "s": session_id,
            },
        )
        return LivenessSessionHandle(
            provider_reference=provider_reference,
            native_launch_handle=session_id,
            expires_at=expires_at,
        )

    async def get_result(self, provider_reference: str) -> LivenessResult:
        try:
            reference = self._codec.decode(provider_reference, "ls")
            session_id = _mapping_text(reference, "s", maximum=64)
            key_prefix = _mapping_text(reference, "p", maximum=512)
            tenant_digest = _mapping_text(reference, "a", maximum=64)
            group_digest = _mapping_text(reference, "g", maximum=64)
            session_expiry = _mapping_epoch(reference, "e")
        except ValueError:
            return LivenessResult(
                outcome="failed",
                retryable=False,
                stable_error_code="PROVIDER_SESSION_INVALID",
            )
        if session_expiry <= self._clock():
            return LivenessResult(
                outcome="expired",
                retryable=True,
                stable_error_code="SESSION_EXPIRED",
            )
        try:
            response = await _async_client_call(
                self._rekognition.get_face_liveness_session_results,
                SessionId=session_id,
            )
        except ClientError as exc:
            code = _client_error_code(exc)
            if code in {"SessionNotFoundException", "ResourceNotFoundException"}:
                return LivenessResult(
                    outcome="expired",
                    retryable=True,
                    stable_error_code="SESSION_EXPIRED",
                )
            _raise_provider_failure(exc, operation="Face Scan")
        status = str(response.get("Status", ""))
        if status in {"CREATED", "IN_PROGRESS"}:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_RESULT_PENDING",
                "Face Scan verification is still processing.",
            )
        if status == "EXPIRED":
            return LivenessResult(
                outcome="expired", retryable=True, stable_error_code="SESSION_EXPIRED"
            )
        if status == "FAILED":
            return LivenessResult(
                outcome="rejected", retryable=True, stable_error_code="LIVENESS_REJECTED"
            )
        if status != "SUCCEEDED":
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_RESULT_INVALID",
                "Face Scan verification is temporarily unavailable.",
            )

        image = _s3_image_from_liveness_response(
            response,
            expected_bucket=cast(str, self._config.liveness_output_bucket),
            expected_prefix=key_prefix,
        )
        image = await self._verify_reference_object(image)
        face_count = await self._detect_face_count(image)
        confidence = response.get("Confidence")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_RESULT_INVALID",
                "Face Scan verification is temporarily unavailable.",
            )
        bounded_confidence = float(confidence)
        if not math.isfinite(bounded_confidence) or not 0 <= bounded_confidence <= 100:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_RESULT_INVALID",
                "Face Scan verification is temporarily unavailable.",
            )
        if face_count == 0:
            await self._discard_reference(image)
            return LivenessResult(outcome="no_face", retryable=True, stable_error_code="NO_FACE")
        if face_count != 1:
            await self._discard_reference(image)
            return LivenessResult(
                outcome="multiple_faces",
                retryable=True,
                stable_error_code="MULTIPLE_FACES",
            )
        if bounded_confidence < self._config.liveness_confidence_threshold:
            await self._discard_reference(image)
            return LivenessResult(
                outcome="rejected", retryable=True, stable_error_code="LIVENESS_REJECTED"
            )
        reference_expiry = self._clock() + timedelta(
            seconds=self._config.reference_frame_retention_seconds
        )
        values: dict[str, object] = {
            "a": tenant_digest,
            "e": int(reference_expiry.timestamp()),
            "g": group_digest,
            "n": image["Name"],
        }
        values["o"] = image["Version"]
        return LivenessResult(
            outcome="passed",
            reference_face_handle=self._codec.encode("rf", values),
        )

    async def delete_reference(self, request: ReferenceDeletionRequest) -> ReferenceDeletionResult:
        try:
            image = self.reference_image(
                request.provider_reference,
                tenant_scope=request.tenant_scope,
                group_scope=request.group_scope,
                allow_expired=True,
            )
        except ValueError:
            return ReferenceDeletionResult(outcome="not_found")
        parameters = self._s3_object_parameters(image)
        try:
            await _async_client_call(self._s3.delete_object, **parameters)
        except ClientError as exc:
            if _client_error_code(exc) in _NOT_FOUND_CODES:
                return ReferenceDeletionResult(outcome="not_found")
            _raise_provider_failure(exc, operation="Face Scan deletion")
        return ReferenceDeletionResult(outcome="deleted")

    def reference_image(
        self,
        reference: str,
        *,
        tenant_scope: str,
        group_scope: str,
        allow_expired: bool = False,
    ) -> dict[str, str]:
        decoded = self._codec.decode(reference, "rf")
        expected_tenant, expected_group = self._scope_digests(tenant_scope, group_scope)
        if decoded.get("a") != expected_tenant or decoded.get("g") != expected_group:
            raise ValueError("Reference scope does not match")
        expiry = _mapping_epoch(decoded, "e")
        if not allow_expired and expiry <= self._clock():
            raise ValueError("Reference has expired")
        image = {"Bucket": cast(str, self._config.liveness_output_bucket)}
        image["Name"] = _mapping_text(decoded, "n", maximum=512)
        version = decoded.get("o")
        if not _valid_s3_version_id(version):
            raise ValueError("Reference version is invalid")
        image["Version"] = cast(str, version)
        return image

    async def detect_reference_faces(self, image: Mapping[str, str]) -> int:
        return await self._detect_face_count(dict(image))

    def _scope_digests(self, tenant_scope: str, group_scope: str) -> tuple[str, str]:
        tenant = _canonical_uuid_scope(tenant_scope)
        group = _canonical_uuid_scope(group_scope)
        tenant_digest = _hmac_hex(self._config.scope_hmac_secret, f"tenant|{tenant}")[:32]
        group_digest = _hmac_hex(
            self._config.scope_hmac_secret,
            f"group|{tenant}|{group}",
        )[:32]
        return tenant_digest, group_digest

    async def _detect_face_count(self, image: dict[str, str]) -> int:
        try:
            response = await _async_client_call(
                self._rekognition.detect_faces,
                Image={"S3Object": image},
                Attributes=["DEFAULT"],
            )
        except ClientError as exc:
            code = _client_error_code(exc)
            if code in {"InvalidParameterException", "InvalidImageFormatException"}:
                return 0
            _raise_provider_failure(exc, operation="Face Scan verification")
        faces = response.get("FaceDetails", ())
        if not isinstance(faces, (list, tuple)) or len(faces) > 100:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_RESULT_INVALID",
                "Face Scan verification is temporarily unavailable.",
            )
        return len(faces)

    async def _verify_reference_object(self, image: Mapping[str, str]) -> dict[str, str]:
        try:
            response = await _async_client_call(
                self._s3.head_object,
                **self._s3_object_parameters(image),
            )
        except ClientError as exc:
            _raise_provider_failure(exc, operation="Face Scan reference verification")
        content_length = response.get("ContentLength")
        version_id = response.get("VersionId")
        if (
            response.get("ServerSideEncryption") != "aws:kms"
            or response.get("SSEKMSKeyId") != self._config.liveness_kms_key_id
            or not _valid_s3_version_id(version_id)
            or ("Version" in image and image["Version"] != version_id)
            or isinstance(content_length, bool)
            or not isinstance(content_length, int)
            or not 1 <= content_length <= 15 * 1024 * 1024
            or response.get("ContentType") not in {"image/jpeg", "image/png"}
        ):
            raise MyPhotosUnavailable(
                "MY_PHOTOS_REFERENCE_ENCRYPTION_INVALID",
                "Face Scan verification is temporarily unavailable.",
            )
        verified = dict(image)
        verified["Version"] = cast(str, version_id)
        return verified

    async def _discard_reference(self, image: Mapping[str, str]) -> None:
        try:
            await _async_client_call(
                self._s3.delete_object,
                **self._s3_object_parameters(image),
            )
        except Exception:
            # A reviewed bucket lifecycle is still mandatory. Rejection must
            # not become a liveness pass merely because best-effort cleanup was
            # unavailable.
            return

    def _s3_object_parameters(self, image: Mapping[str, str]) -> dict[str, object]:
        parameters: dict[str, object] = {
            "Bucket": image["Bucket"],
            "Key": image["Name"],
        }
        if "Version" in image:
            parameters["VersionId"] = image["Version"]
        if self._config.expected_bucket_owner is not None:
            parameters["ExpectedBucketOwner"] = self._config.expected_bucket_owner
        return parameters


class AwsRekognitionFaceIndexSearchProvider:
    """One Rekognition collection per HMAC-derived tenant/group scope."""

    def __init__(
        self,
        *,
        rekognition_client: Any,
        liveness_provider: AwsRekognitionLivenessProvider,
        config: AwsMyPhotosProviderConfig,
    ) -> None:
        if config.media_bucket is None:
            raise ValueError("Face indexing media bucket is required")
        self._rekognition = rekognition_client
        self._liveness = liveness_provider
        self._config = config
        self._media_codec = _OpaqueReferenceCodec(
            config.reference_active_key_id,
            config.reference_signing_keys,
            maximum_reference_length=4_096,
        )

    @property
    def ready(self) -> bool:
        return True

    def collection_reference(self, *, tenant_scope: str, group_scope: str) -> str:
        tenant = _canonical_uuid_scope(tenant_scope)
        group = _canonical_uuid_scope(group_scope)
        digest = _hmac_hex(
            self._config.scope_hmac_secret,
            f"collection|{tenant}|{group}",
        )[:48]
        return f"{self._config.collection_prefix}-{digest}"

    async def ensure_collection(self, request: FaceCollectionRequest) -> FaceCollectionResult:
        collection_id = self._required_collection(request)
        try:
            response = await _async_client_call(
                self._rekognition.describe_collection,
                CollectionId=collection_id,
            )
        except ClientError as exc:
            if _client_error_code(exc) != "ResourceNotFoundException":
                _raise_provider_failure(exc, operation="Face collection")
            try:
                response = await _async_client_call(
                    self._rekognition.create_collection,
                    CollectionId=collection_id,
                    Tags={"Application": "PassDetection", "DataClass": "MyPhotos"},
                )
            except ClientError as create_exc:
                if _client_error_code(create_exc) != "ResourceAlreadyExistsException":
                    _raise_provider_failure(create_exc, operation="Face collection")
                try:
                    response = await _async_client_call(
                        self._rekognition.describe_collection,
                        CollectionId=collection_id,
                    )
                except ClientError as describe_exc:
                    _raise_provider_failure(describe_exc, operation="Face collection")
        version = _provider_model_version(response)
        return FaceCollectionResult(
            collection_reference=collection_id,
            provider_model_version=version,
        )

    async def index_faces(self, request: FaceIndexBatchRequest) -> FaceIndexBatchResult:
        self._required_collection(request)
        if not request.assets or len(request.assets) > 500:
            raise ValueError("Face index batch is outside the bounded contract")
        semaphore = asyncio.Semaphore(self._config.index_concurrency)

        async def index_one(
            asset: FaceIndexAsset,
        ) -> tuple[tuple[IndexedFaceOccurrence, ...], FaceIndexFailure | None]:
            async with semaphore:
                return await self._index_one(request, asset)

        results = await asyncio.gather(*(index_one(asset) for asset in request.assets))
        occurrences = tuple(occurrence for result, _failure in results for occurrence in result)
        failures = tuple(failure for _result, failure in results if failure is not None)
        return FaceIndexBatchResult(occurrences=occurrences, failures=failures)

    async def search(self, request: FaceSearchRequest) -> FaceSearchResult:
        collection_id = self._required_collection(request)
        if not 1 <= request.maximum_results <= 4_096:
            raise ValueError("Search result limit is outside the Rekognition boundary")
        try:
            image = self._liveness.reference_image(
                request.reference_face_handle,
                tenant_scope=request.tenant_scope,
                group_scope=request.group_scope,
            )
        except ValueError as exc:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_REFERENCE_INVALID", "Face reference is no longer available."
            ) from exc
        face_count = await self._liveness.detect_reference_faces(image)
        if face_count == 0:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_REFERENCE_NO_FACE", "Face reference is no longer usable."
            )
        if face_count != 1:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_REFERENCE_MULTIPLE_FACES", "Face reference is no longer usable."
            )
        try:
            response = await _async_client_call(
                self._rekognition.search_faces_by_image,
                CollectionId=collection_id,
                Image={"S3Object": image},
                FaceMatchThreshold=self._config.possible_match_threshold,
                MaxFaces=request.maximum_results,
                QualityFilter=self._config.search_quality_filter,
            )
        except ClientError as exc:
            if _client_error_code(exc) == "InvalidParameterException":
                raise MyPhotosUnavailable(
                    "MY_PHOTOS_REFERENCE_NO_FACE", "Face reference is no longer usable."
                ) from None
            _raise_provider_failure(exc, operation="Face search")
        raw_matches = response.get("FaceMatches", ())
        if not isinstance(raw_matches, (list, tuple)) or len(raw_matches) > request.maximum_results:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_RESULT_INVALID", "Face search is temporarily unavailable."
            )
        matches: list[ProviderFaceMatch] = []
        for raw in raw_matches:
            if not isinstance(raw, Mapping):
                raise MyPhotosUnavailable(
                    "MY_PHOTOS_PROVIDER_RESULT_INVALID",
                    "Face search is temporarily unavailable.",
                )
            face = raw.get("Face")
            similarity = raw.get("Similarity")
            if not isinstance(face, Mapping):
                raise MyPhotosUnavailable(
                    "MY_PHOTOS_PROVIDER_RESULT_INVALID",
                    "Face search is temporarily unavailable.",
                )
            face_id = str(face.get("FaceId", ""))
            if (
                _FACE_ID.fullmatch(face_id) is None
                or isinstance(similarity, bool)
                or not isinstance(similarity, (int, float))
                or not math.isfinite(float(similarity))
                or not 0 <= float(similarity) <= 100
            ):
                raise MyPhotosUnavailable(
                    "MY_PHOTOS_PROVIDER_RESULT_INVALID",
                    "Face search is temporarily unavailable.",
                )
            matches.append(
                ProviderFaceMatch(
                    provider_face_reference=face_id,
                    similarity=float(similarity),
                )
            )
        return FaceSearchResult(
            matches=tuple(matches),
            provider_model_version=_provider_model_version(response),
        )

    async def delete_faces(self, request: FaceDeletionRequest) -> FaceDeletionResult:
        collection_id = self._required_collection(request)
        requested = tuple(dict.fromkeys(request.provider_face_references))
        if not requested or len(requested) > 4_096:
            raise ValueError("Face deletion batch is outside the provider boundary")
        if any(_FACE_ID.fullmatch(reference) is None for reference in requested):
            raise ValueError("Face deletion reference is invalid")
        try:
            response = await _async_client_call(
                self._rekognition.delete_faces,
                CollectionId=collection_id,
                FaceIds=list(requested),
            )
        except ClientError as exc:
            if _client_error_code(exc) == "ResourceNotFoundException":
                return FaceDeletionResult(
                    deleted_face_references=(),
                    not_found_face_references=requested,
                )
            _raise_provider_failure(exc, operation="Face deletion")
        deleted = tuple(str(value) for value in response.get("DeletedFaces", ()))
        if any(value not in requested for value in deleted):
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_RESULT_INVALID", "Face deletion is temporarily unavailable."
            )
        not_found: list[str] = []
        unsuccessful = response.get("UnsuccessfulFaceDeletions", ())
        if not isinstance(unsuccessful, (list, tuple)):
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_RESULT_INVALID", "Face deletion is temporarily unavailable."
            )
        for item in unsuccessful:
            if not isinstance(item, Mapping):
                raise MyPhotosUnavailable(
                    "MY_PHOTOS_PROVIDER_RESULT_INVALID",
                    "Face deletion is temporarily unavailable.",
                )
            face_id = str(item.get("FaceId", ""))
            reasons = item.get("Reasons", ())
            if face_id not in requested or not isinstance(reasons, (list, tuple)):
                raise MyPhotosUnavailable(
                    "MY_PHOTOS_PROVIDER_RESULT_INVALID",
                    "Face deletion is temporarily unavailable.",
                )
            if "FACE_NOT_FOUND" in reasons:
                not_found.append(face_id)
                continue
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_DELETION_BLOCKED",
                "Face deletion is temporarily unavailable.",
            )
        accounted = set(deleted) | set(not_found)
        # A successful retry may omit an already-absent ID. Normalize those as
        # not found so callers can complete deletion idempotently.
        not_found.extend(value for value in requested if value not in accounted)
        return FaceDeletionResult(
            deleted_face_references=deleted,
            not_found_face_references=tuple(not_found),
        )

    async def delete_collection(
        self, request: FaceCollectionRequest
    ) -> FaceCollectionDeletionResult:
        collection_id = self._required_collection(request)
        try:
            await _async_client_call(
                self._rekognition.delete_collection,
                CollectionId=collection_id,
            )
        except ClientError as exc:
            if _client_error_code(exc) == "ResourceNotFoundException":
                return FaceCollectionDeletionResult(outcome="not_found")
            _raise_provider_failure(exc, operation="Face collection deletion")
        return FaceCollectionDeletionResult(outcome="deleted")

    async def _index_one(
        self,
        request: FaceIndexBatchRequest,
        asset: FaceIndexAsset,
    ) -> tuple[tuple[IndexedFaceOccurrence, ...], FaceIndexFailure | None]:
        expected_reference = media_object_reference(
            self._config,
            tenant_scope=request.tenant_scope,
            group_scope=request.group_scope,
            asset_identity=asset.asset_identity,
            variant="analysis",
        )
        try:
            media_key, media_version = _decode_versioned_media_reference(
                self._media_codec,
                asset.analysis_media_reference,
                config=self._config,
                tenant_scope=request.tenant_scope,
                group_scope=request.group_scope,
            )
        except ValueError:
            return (), FaceIndexFailure(
                asset_identity=asset.asset_identity,
                stable_error_code="MEDIA_REFERENCE_SCOPE_INVALID",
            )
        if media_key != expected_reference:
            return (), FaceIndexFailure(
                asset_identity=asset.asset_identity,
                stable_error_code="MEDIA_REFERENCE_SCOPE_INVALID",
            )
        external_id = f"pd-{hashlib.sha256(asset.idempotency_identity.encode()).hexdigest()}"
        try:
            response = await _async_client_call(
                self._rekognition.index_faces,
                CollectionId=request.collection_reference,
                Image={
                    "S3Object": {
                        "Bucket": cast(str, self._config.media_bucket),
                        "Name": media_key,
                        "Version": media_version,
                    }
                },
                ExternalImageId=external_id,
                DetectionAttributes=[],
                MaxFaces=self._config.index_max_faces_per_asset,
                QualityFilter=self._config.index_quality_filter,
            )
        except ClientError as exc:
            code = _client_error_code(exc)
            if code in _PERMANENT_INDEX_FAILURES:
                return (), FaceIndexFailure(
                    asset_identity=asset.asset_identity,
                    stable_error_code=_PERMANENT_INDEX_FAILURES[code],
                )
            _raise_provider_failure(exc, operation="Face indexing")
        model_version = _provider_model_version(response)
        records = response.get("FaceRecords", ())
        if not isinstance(records, (list, tuple)) or len(records) > 100:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_RESULT_INVALID", "Face indexing is temporarily unavailable."
            )
        occurrences: list[IndexedFaceOccurrence] = []
        for record in records:
            occurrence = _indexed_occurrence(
                record,
                asset=asset,
                model_version=model_version,
            )
            occurrences.append(occurrence)
        if occurrences:
            return tuple(occurrences), None
        return (), FaceIndexFailure(
            asset_identity=asset.asset_identity,
            stable_error_code=_unindexed_reason(response),
        )

    def _required_collection(self, request: Any) -> str:
        expected = self.collection_reference(
            tenant_scope=request.tenant_scope,
            group_scope=request.group_scope,
        )
        if request.collection_reference != expected:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_COLLECTION_SCOPE_INVALID", "Face collection is unavailable."
            )
        return expected


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
        remaining = max(1, math.floor((expiry - now).total_seconds()))
        parameters: dict[str, object] = {
            "Bucket": cast(str, self._config.media_bucket),
            "Key": media_key,
            "VersionId": media_version,
            "ResponseContentType": request.content_type,
        }
        if self._config.expected_bucket_owner is not None:
            parameters["ExpectedBucketOwner"] = self._config.expected_bucket_owner
        try:
            location = await _async_client_call(
                self._s3.generate_presigned_url,
                "get_object",
                Params=parameters,
                ExpiresIn=min(
                    remaining,
                    self._config.delivery_authorization_ttl_seconds,
                ),
                HttpMethod="GET",
            )
        except ClientError as exc:
            _raise_provider_failure(exc, operation="Photo delivery")
        location = _validated_presigned_media_location(
            location,
            config=self._config,
            media_key=media_key,
        )
        return DeliveryResolution(
            location=location,
            expires_at=expiry,
            supports_ranges=True,
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


class _MediaObjectNotFound(Exception):
    pass


@dataclass(frozen=True, slots=True)
class _MediaMetadata:
    size: int
    checksum: str
    content_type: str
    width: int
    height: int
    delivery_version: int
    version_id: str


def media_object_reference(
    config: AwsMyPhotosProviderConfig,
    *,
    tenant_scope: str,
    group_scope: str,
    asset_identity: str,
    variant: Literal["thumbnail", "preview", "analysis", "original", "optimized"],
) -> str:
    tenant = _canonical_uuid_scope(tenant_scope)
    group = _canonical_uuid_scope(group_scope)
    scope = _hmac_hex(config.scope_hmac_secret, f"media|{tenant}|{group}")[:48]
    asset = hashlib.sha256(asset_identity.encode("utf-8")).hexdigest()
    reference = f"{config.media_key_prefix}/{scope}/{asset}/{variant}"
    if len(reference) > 512:
        raise ValueError("Media object reference exceeds the persistence boundary")
    return reference


def _require_scoped_media_reference(
    config: AwsMyPhotosProviderConfig,
    reference: str,
    *,
    tenant_scope: str,
    group_scope: str,
) -> None:
    tenant = _canonical_uuid_scope(tenant_scope)
    group = _canonical_uuid_scope(group_scope)
    scope = _hmac_hex(config.scope_hmac_secret, f"media|{tenant}|{group}")[:48]
    prefix = f"{config.media_key_prefix}/{scope}/"
    if (
        not reference.startswith(prefix)
        or len(reference) > 512
        or reference != reference.strip()
        or not reference.isprintable()
        or "//" in reference
        or any(part in {"", ".", ".."} for part in reference.split("/"))
    ):
        raise MyPhotosUnavailable(
            "MY_PHOTOS_MEDIA_SCOPE_INVALID", "Photo storage reference is invalid."
        )


def _encode_versioned_media_reference(
    codec: _OpaqueReferenceCodec,
    media_key: str,
    version_id: str,
) -> str:
    if not _valid_s3_version_id(version_id):
        raise MyPhotosUnavailable(
            "MY_PHOTOS_MEDIA_VERSION_INVALID", "Photo storage version is invalid."
        )
    try:
        return codec.encode("mo", {"n": media_key, "o": version_id})
    except ValueError as exc:
        raise MyPhotosUnavailable(
            "MY_PHOTOS_MEDIA_VERSION_INVALID", "Photo storage version is invalid."
        ) from exc


def _decode_versioned_media_reference(
    codec: _OpaqueReferenceCodec,
    reference: str,
    *,
    config: AwsMyPhotosProviderConfig,
    tenant_scope: str,
    group_scope: str,
) -> tuple[str, str]:
    decoded = codec.decode(reference, "mo")
    media_key = _mapping_text(decoded, "n", maximum=512)
    version_id = _mapping_text(decoded, "o", maximum=1_024)
    if not _valid_s3_version_id(version_id):
        raise ValueError("Invalid media object version")
    _require_scoped_media_reference(
        config,
        media_key,
        tenant_scope=tenant_scope,
        group_scope=group_scope,
    )
    return media_key, version_id


def _valid_s3_version_id(value: object) -> bool:
    if not isinstance(value, str) or value == "null" or value != value.strip():
        return False
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return 1 <= len(encoded) <= 1_024 and value.isprintable()


def _indexed_occurrence(
    record: object,
    *,
    asset: FaceIndexAsset,
    model_version: str,
) -> IndexedFaceOccurrence:
    if not isinstance(record, Mapping):
        raise MyPhotosUnavailable(
            "MY_PHOTOS_PROVIDER_RESULT_INVALID", "Face indexing is temporarily unavailable."
        )
    face = record.get("Face")
    if not isinstance(face, Mapping):
        raise MyPhotosUnavailable(
            "MY_PHOTOS_PROVIDER_RESULT_INVALID", "Face indexing is temporarily unavailable."
        )
    face_id = str(face.get("FaceId", ""))
    box = face.get("BoundingBox")
    confidence = face.get("Confidence")
    if _FACE_ID.fullmatch(face_id) is None or not isinstance(box, Mapping):
        raise MyPhotosUnavailable(
            "MY_PHOTOS_PROVIDER_RESULT_INVALID", "Face indexing is temporarily unavailable."
        )
    values: list[float] = []
    for name in ("Left", "Top", "Width", "Height"):
        value = box.get(name)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or not 0 <= float(value) <= 1
        ):
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_RESULT_INVALID", "Face indexing is temporarily unavailable."
            )
        values.append(float(value))
    quality: float | None = None
    if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
        quality = float(confidence)
        if not math.isfinite(quality) or not 0 <= quality <= 100:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_RESULT_INVALID", "Face indexing is temporarily unavailable."
            )
    idempotency = hashlib.sha256(
        f"{asset.idempotency_identity}|{face_id}".encode("utf-8")
    ).hexdigest()
    return IndexedFaceOccurrence(
        asset_identity=asset.asset_identity,
        provider_face_reference=face_id,
        bounding_box=CanonicalFaceBox(
            left=values[0],
            top=values[1],
            width=values[2],
            height=values[3],
        ),
        quality_score=quality,
        provider_model_version=model_version,
        idempotency_identity=f"aws-index:{idempotency}",
    )


def _unindexed_reason(response: Mapping[str, object]) -> str:
    unindexed = response.get("UnindexedFaces", ())
    if not isinstance(unindexed, (list, tuple)) or not unindexed:
        return "NO_FACE"
    first = unindexed[0]
    if not isinstance(first, Mapping):
        return "FACE_NOT_INDEXED"
    reasons = first.get("Reasons", ())
    if not isinstance(reasons, (list, tuple)):
        return "FACE_NOT_INDEXED"
    normalized = {str(reason) for reason in reasons}
    if "EXCEEDS_MAX_FACES" in normalized:
        return "FACE_LIMIT_EXCEEDED"
    if normalized & {
        "LOW_BRIGHTNESS",
        "LOW_SHARPNESS",
        "LOW_CONFIDENCE",
        "EXTREME_POSE",
        "FACE_OCCLUDED",
    }:
        return "FACE_QUALITY_INSUFFICIENT"
    return "FACE_NOT_INDEXED"


def _provider_model_version(response: Mapping[str, object]) -> str:
    value = response.get("FaceModelVersion") or response.get("FaceModelVersionNumber")
    if not isinstance(value, str) or not value or len(value) > 64 or not value.isprintable():
        raise MyPhotosUnavailable(
            "MY_PHOTOS_PROVIDER_RESULT_INVALID", "Face provider is temporarily unavailable."
        )
    return value


def _s3_image_from_liveness_response(
    response: Mapping[str, object],
    *,
    expected_bucket: str,
    expected_prefix: str,
) -> dict[str, str]:
    reference = response.get("ReferenceImage")
    if not isinstance(reference, Mapping):
        raise MyPhotosUnavailable(
            "MY_PHOTOS_REFERENCE_NO_FACE", "Face Scan did not return a usable face."
        )
    image = reference.get("S3Object")
    if not isinstance(image, Mapping):
        # Production always supplies OutputConfig so raw biometric bytes never
        # enter application memory or cross the domain adapter.
        raise MyPhotosUnavailable(
            "MY_PHOTOS_PROVIDER_RESULT_INVALID",
            "Face Scan verification is temporarily unavailable.",
        )
    bucket = image.get("Bucket")
    name = image.get("Name")
    if (
        bucket != expected_bucket
        or not isinstance(name, str)
        or not name.startswith(f"{expected_prefix}/")
        or len(name) > 512
        or not name.isprintable()
        or ".." in name.split("/")
    ):
        raise MyPhotosUnavailable(
            "MY_PHOTOS_PROVIDER_RESULT_INVALID",
            "Face Scan verification is temporarily unavailable.",
        )
    result = {"Bucket": bucket, "Name": name}
    version = image.get("Version")
    if version is not None:
        if not _valid_s3_version_id(version):
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_RESULT_INVALID",
                "Face Scan verification is temporarily unavailable.",
            )
        result["Version"] = cast(str, version)
    return result


def _media_metadata(
    response: Mapping[str, object],
    *,
    expected_kms_key_id: str,
    expected_version_id: str | None,
) -> _MediaMetadata:
    size = response.get("ContentLength")
    content_type = response.get("ContentType")
    metadata = response.get("Metadata")
    if (
        isinstance(size, bool)
        or not isinstance(size, int)
        or not 1 <= size <= MAX_MY_PHOTOS_MEDIA_BYTES
        or content_type not in _SUPPORTED_MIME
        or not isinstance(metadata, Mapping)
        or response.get("ServerSideEncryption") != "aws:kms"
        or response.get("SSEKMSKeyId") != expected_kms_key_id
    ):
        raise MyPhotosUnavailable(
            "MY_PHOTOS_MEDIA_METADATA_INVALID", "Photo storage metadata is invalid."
        )
    checksum = metadata.get("sha256")
    native_checksum = _full_object_sha256(response)
    width = _positive_metadata_int(metadata.get("width"))
    height = _positive_metadata_int(metadata.get("height"))
    delivery_version = _positive_metadata_int(metadata.get("delivery-version", "1"))
    version_id = response.get("VersionId")
    if (
        not isinstance(checksum, str)
        or _CHECKSUM.fullmatch(checksum) is None
        or checksum != native_checksum
        or not _valid_s3_version_id(version_id)
        or (expected_version_id is not None and version_id != expected_version_id)
    ):
        raise MyPhotosUnavailable(
            "MY_PHOTOS_MEDIA_METADATA_INVALID", "Photo storage metadata is invalid."
        )
    return _MediaMetadata(
        size=size,
        checksum=checksum,
        content_type=content_type,
        width=width,
        height=height,
        delivery_version=delivery_version,
        version_id=cast(str, version_id),
    )


def _validated_presigned_media_location(
    location: object,
    *,
    config: AwsMyPhotosProviderConfig,
    media_key: str,
) -> str:
    """Accept only a signed URL bound to the reviewed bucket endpoint and key."""

    if not isinstance(location, str) or len(location) > 8_192:
        _raise_invalid_delivery_location()
    try:
        parsed = urlsplit(location)
        port = parsed.port
    except ValueError:
        _raise_invalid_delivery_location()
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.hostname is None
        or parsed.fragment
    ):
        _raise_invalid_delivery_location()
    try:
        decoded_path = unquote(parsed.path, errors="strict")
    except (UnicodeDecodeError, ValueError):
        _raise_invalid_delivery_location()
    if not decoded_path.startswith("/") or "\x00" in decoded_path:
        _raise_invalid_delivery_location()

    bucket = cast(str, config.media_bucket)
    host = parsed.hostname.lower()
    candidates: set[tuple[str, str]] = set()
    if config.s3_endpoint_url is not None:
        endpoint = urlsplit(config.s3_endpoint_url)
        if endpoint.hostname is None:
            _raise_invalid_delivery_location()
        try:
            endpoint_port = endpoint.port
        except ValueError:
            _raise_invalid_delivery_location()
        if (port or 443) != (endpoint_port or 443):
            _raise_invalid_delivery_location()
        endpoint_host = endpoint.hostname.lower()
        base_path = unquote(endpoint.path, errors="strict").rstrip("/")
        if config.s3_addressing_style in {"auto", "virtual"}:
            candidates.add((f"{bucket}.{endpoint_host}", f"{base_path}/{media_key}"))
        if config.s3_addressing_style in {"auto", "path"}:
            candidates.add((endpoint_host, f"{base_path}/{bucket}/{media_key}"))
    else:
        if (port or 443) != 443:
            _raise_invalid_delivery_location()
        china_partition = config.region.startswith("cn-")
        govcloud_partition = "-gov-" in config.region
        suffix = "amazonaws.com.cn" if china_partition else "amazonaws.com"
        if config.s3_addressing_style in {"auto", "virtual"}:
            candidates.add((f"{bucket}.s3.{config.region}.{suffix}", f"/{media_key}"))
            # Botocore's ``auto`` addressing uses the legacy global virtual
            # hostname for DNS-compatible buckets in commercial AWS regions,
            # even though the client endpoint itself is regional. Keep the
            # allowlist bound to this exact bucket and official AWS hostname;
            # GovCloud and China remain regional-only.
            if config.region == "us-east-1" or (
                config.s3_addressing_style == "auto"
                and not china_partition
                and not govcloud_partition
            ):
                candidates.add((f"{bucket}.s3.{suffix}", f"/{media_key}"))
        if config.s3_addressing_style in {"auto", "path"}:
            candidates.add((f"s3.{config.region}.{suffix}", f"/{bucket}/{media_key}"))
            if config.region == "us-east-1":
                candidates.add((f"s3.{suffix}", f"/{bucket}/{media_key}"))
    if (host, decoded_path) not in candidates:
        _raise_invalid_delivery_location()
    return location


def _raise_invalid_delivery_location() -> NoReturn:
    raise MyPhotosUnavailable(
        "MY_PHOTOS_PROVIDER_RESULT_INVALID", "Photo delivery is temporarily unavailable."
    )


def _full_object_sha256(response: Mapping[str, object]) -> str:
    """Require uploader-supplied S3-native SHA-256 for a non-composite object."""

    encoded = response.get("ChecksumSHA256")
    if response.get("ChecksumType") != "FULL_OBJECT" or not isinstance(encoded, str):
        raise MyPhotosUnavailable(
            "MY_PHOTOS_MEDIA_CHECKSUM_INVALID",
            "Photo storage checksum is invalid.",
        )
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise MyPhotosUnavailable(
            "MY_PHOTOS_MEDIA_CHECKSUM_INVALID",
            "Photo storage checksum is invalid.",
        ) from exc
    if len(decoded) != 32 or base64.b64encode(decoded).decode("ascii") != encoded:
        raise MyPhotosUnavailable(
            "MY_PHOTOS_MEDIA_CHECKSUM_INVALID",
            "Photo storage checksum is invalid.",
        )
    return decoded.hex()


def _positive_metadata_int(value: object) -> int:
    try:
        parsed = int(cast(Any, value))
    except (TypeError, ValueError) as exc:
        raise MyPhotosUnavailable(
            "MY_PHOTOS_MEDIA_METADATA_INVALID", "Photo storage metadata is invalid."
        ) from exc
    if not 1 <= parsed <= 100_000:
        raise MyPhotosUnavailable(
            "MY_PHOTOS_MEDIA_METADATA_INVALID", "Photo storage metadata is invalid."
        )
    return parsed


def _require_media_integrity(
    metadata: _MediaMetadata,
    *,
    expected_size: int,
    expected_checksum: str,
    expected_content_type: str,
    expected_width: int | None = None,
    expected_height: int | None = None,
) -> None:
    if (
        metadata.size != expected_size
        or metadata.checksum != expected_checksum
        or metadata.content_type != expected_content_type
        or (expected_width is not None and metadata.width != expected_width)
        or (expected_height is not None and metadata.height != expected_height)
    ):
        raise MyPhotosUnavailable(
            "MY_PHOTOS_MEDIA_INTEGRITY_CHANGED", "Photo storage integrity check failed."
        )


def _delivery_fingerprint(
    tenant_scope: str,
    group_scope: str,
    passenger_scope: str,
    authorization_identity: str,
    asset_identity: str,
    media_reference: str,
    quality: str,
    expected_size_bytes: int,
    checksum_sha256: str,
    content_type: str,
) -> str:
    values = (
        _canonical_uuid_scope(tenant_scope),
        _canonical_uuid_scope(group_scope),
        _canonical_uuid_scope(passenger_scope),
        authorization_identity,
        asset_identity,
        media_reference,
        quality,
        str(expected_size_bytes),
        checksum_sha256,
        content_type,
    )
    return hashlib.sha256("\x1f".join(values).encode("utf-8")).hexdigest()


def _canonical_uuid_scope(value: str) -> str:
    try:
        normalized = str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Provider scope must be a canonical UUID") from exc
    if value.lower() != normalized:
        raise ValueError("Provider scope must be a canonical UUID")
    return normalized


def _aws_idempotency_token(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_-]", "-", value)[:64]
    if 1 <= len(normalized) <= 64 and normalized == value:
        return normalized
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def _async_client_call(method: Callable[..., Any], *args: object, **kwargs: object) -> Any:
    return await asyncio.to_thread(method, *args, **kwargs)


def _client_error_code(exc: ClientError) -> str:
    error = exc.response.get("Error", {})
    return (
        str(error.get("Code", "ProviderError")) if isinstance(error, Mapping) else "ProviderError"
    )


def _raise_provider_failure(exc: ClientError, *, operation: str) -> None:
    code = _client_error_code(exc)
    if code in _THROTTLE_CODES:
        raise MyPhotosUnavailable(
            "MY_PHOTOS_PROVIDER_THROTTLED", f"{operation} is busy. Try again shortly."
        ) from None
    raise MyPhotosUnavailable(
        "MY_PHOTOS_PROVIDER_UNAVAILABLE", f"{operation} is temporarily unavailable."
    ) from None


def _required_text(response: Mapping[str, object], key: str, *, maximum: int) -> str:
    value = response.get(key)
    if not isinstance(value, str) or not value or len(value) > maximum or not value.isprintable():
        raise MyPhotosUnavailable(
            "MY_PHOTOS_PROVIDER_RESULT_INVALID", "Provider response is temporarily unavailable."
        )
    return value


def _mapping_text(response: Mapping[str, object], key: str, *, maximum: int) -> str:
    value = response.get(key)
    if not isinstance(value, str) or not value or len(value) > maximum or not value.isprintable():
        raise ValueError("Opaque reference value is invalid")
    return value


def _mapping_epoch(response: Mapping[str, object], key: str) -> datetime:
    value = response.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("Opaque reference expiry is invalid")
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise ValueError("Opaque reference expiry is invalid") from exc


def _hmac_hex(secret: bytes, value: str) -> str:
    return hmac.new(secret, value.encode("utf-8"), hashlib.sha256).hexdigest()


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + ("=" * (-len(value) % 4)))


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
