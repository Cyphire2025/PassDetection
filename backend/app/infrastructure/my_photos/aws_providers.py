"""Compatibility imports for the focused My Photos AWS adapters."""

from app.infrastructure.my_photos.aws_client_runtime import (
    _NOT_FOUND_CODES as _NOT_FOUND_CODES,
)
from app.infrastructure.my_photos.aws_client_runtime import (
    _THROTTLE_CODES as _THROTTLE_CODES,
)
from app.infrastructure.my_photos.aws_client_runtime import (
    _as_utc as _as_utc,
)
from app.infrastructure.my_photos.aws_client_runtime import (
    _async_client_call as _async_client_call,
)
from app.infrastructure.my_photos.aws_client_runtime import (
    _client_error_code as _client_error_code,
)
from app.infrastructure.my_photos.aws_client_runtime import (
    _mapping_epoch as _mapping_epoch,
)
from app.infrastructure.my_photos.aws_client_runtime import (
    _mapping_text as _mapping_text,
)
from app.infrastructure.my_photos.aws_client_runtime import (
    _raise_provider_failure as _raise_provider_failure,
)
from app.infrastructure.my_photos.aws_client_runtime import (
    _required_text as _required_text,
)
from app.infrastructure.my_photos.aws_client_runtime import (
    _utcnow as _utcnow,
)
from app.infrastructure.my_photos.aws_face_results import (
    _FACE_ID as _FACE_ID,
)
from app.infrastructure.my_photos.aws_face_results import (
    _PERMANENT_INDEX_FAILURES as _PERMANENT_INDEX_FAILURES,
)
from app.infrastructure.my_photos.aws_face_results import (
    _indexed_occurrence as _indexed_occurrence,
)
from app.infrastructure.my_photos.aws_face_results import (
    _provider_model_version as _provider_model_version,
)
from app.infrastructure.my_photos.aws_face_results import (
    _s3_image_from_liveness_response as _s3_image_from_liveness_response,
)
from app.infrastructure.my_photos.aws_face_results import (
    _unindexed_reason as _unindexed_reason,
)
from app.infrastructure.my_photos.aws_face_search import (
    AwsRekognitionFaceIndexSearchProvider as AwsRekognitionFaceIndexSearchProvider,
)
from app.infrastructure.my_photos.aws_liveness import (
    _CHALLENGE_TYPES as _CHALLENGE_TYPES,
)
from app.infrastructure.my_photos.aws_liveness import (
    _SESSION_ID as _SESSION_ID,
)
from app.infrastructure.my_photos.aws_liveness import (
    AwsRekognitionLivenessProvider as AwsRekognitionLivenessProvider,
)
from app.infrastructure.my_photos.aws_media_delivery import (
    S3DirectMediaDeliveryProvider as S3DirectMediaDeliveryProvider,
)
from app.infrastructure.my_photos.aws_media_location import (
    _raise_invalid_delivery_location as _raise_invalid_delivery_location,
)
from app.infrastructure.my_photos.aws_media_location import (
    _require_presigned_expiry as _require_presigned_expiry,
)
from app.infrastructure.my_photos.aws_media_location import (
    _validated_presigned_media_location as _validated_presigned_media_location,
)
from app.infrastructure.my_photos.aws_media_metadata import (
    _CHECKSUM as _CHECKSUM,
)
from app.infrastructure.my_photos.aws_media_metadata import (
    _SUPPORTED_MIME as _SUPPORTED_MIME,
)
from app.infrastructure.my_photos.aws_media_metadata import (
    _full_object_sha256 as _full_object_sha256,
)
from app.infrastructure.my_photos.aws_media_metadata import (
    _media_metadata as _media_metadata,
)
from app.infrastructure.my_photos.aws_media_metadata import (
    _MediaMetadata as _MediaMetadata,
)
from app.infrastructure.my_photos.aws_media_metadata import (
    _MediaObjectNotFound as _MediaObjectNotFound,
)
from app.infrastructure.my_photos.aws_media_metadata import (
    _positive_metadata_int as _positive_metadata_int,
)
from app.infrastructure.my_photos.aws_media_metadata import (
    _require_media_integrity as _require_media_integrity,
)
from app.infrastructure.my_photos.aws_provider_config import (
    AwsMyPhotosProviderConfig as AwsMyPhotosProviderConfig,
)
from app.infrastructure.my_photos.aws_provider_config import (
    aws_provider_config as aws_provider_config,
)
from app.infrastructure.my_photos.aws_references import (
    _aws_idempotency_token as _aws_idempotency_token,
)
from app.infrastructure.my_photos.aws_references import (
    _b64url as _b64url,
)
from app.infrastructure.my_photos.aws_references import (
    _b64url_decode as _b64url_decode,
)
from app.infrastructure.my_photos.aws_references import (
    _canonical_uuid_scope as _canonical_uuid_scope,
)
from app.infrastructure.my_photos.aws_references import (
    _decode_versioned_media_reference as _decode_versioned_media_reference,
)
from app.infrastructure.my_photos.aws_references import (
    _delivery_fingerprint as _delivery_fingerprint,
)
from app.infrastructure.my_photos.aws_references import (
    _encode_versioned_media_reference as _encode_versioned_media_reference,
)
from app.infrastructure.my_photos.aws_references import (
    _hmac_hex as _hmac_hex,
)
from app.infrastructure.my_photos.aws_references import (
    _OpaqueReferenceCodec as _OpaqueReferenceCodec,
)
from app.infrastructure.my_photos.aws_references import (
    _require_scoped_media_reference as _require_scoped_media_reference,
)
from app.infrastructure.my_photos.aws_references import (
    _valid_s3_version_id as _valid_s3_version_id,
)
from app.infrastructure.my_photos.aws_references import (
    media_object_reference as media_object_reference,
)
