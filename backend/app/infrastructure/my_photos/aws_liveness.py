"""Server-owned AWS liveness creation, verification and exact reference deletion."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any, Literal, cast

from botocore.exceptions import ClientError

from app.application.my_photos.errors import MyPhotosUnavailable
from app.application.my_photos.providers import (
    LivenessResult,
    LivenessSessionHandle,
    LivenessSessionRequest,
    ReferenceDeletionRequest,
    ReferenceDeletionResult,
)
from app.infrastructure.my_photos.aws_client_runtime import (
    _NOT_FOUND_CODES,
    _as_utc,
    _async_client_call,
    _client_error_code,
    _mapping_epoch,
    _mapping_text,
    _raise_provider_failure,
    _required_text,
    _utcnow,
)
from app.infrastructure.my_photos.aws_face_results import (
    _s3_image_from_liveness_response,
)
from app.infrastructure.my_photos.aws_provider_config import (
    AwsMyPhotosProviderConfig,
)
from app.infrastructure.my_photos.aws_references import (
    _aws_idempotency_token,
    _canonical_uuid_scope,
    _hmac_hex,
    _OpaqueReferenceCodec,
    _valid_s3_version_id,
)

_SESSION_ID = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")


_CHALLENGE_TYPES = {
    "movement_and_light": "FaceMovementAndLightChallenge",
    "movement_only": "FaceMovementChallenge",
}


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
