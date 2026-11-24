"""AWS activation, reference-key and object-storage admission for My Photos."""

from __future__ import annotations

import ipaddress
import re
from typing import TYPE_CHECKING, TypeVar
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from app.core.config.my_photos_settings import MyPhotosSettings

_MyPhotosT = TypeVar("_MyPhotosT", bound="MyPhotosSettings")

_S3_BUCKET_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")


_KMS_KEY_ARN_PATTERN = re.compile(
    r"^arn:(aws|aws-us-gov|aws-cn):kms:([a-z0-9-]+):([0-9]{12}):"
    r"key/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$"
)


def _validate_s3_bucket_name(value: str) -> None:
    if (
        _S3_BUCKET_PATTERN.fullmatch(value) is None
        or ".." in value
        or ".-" in value
        or "-." in value
    ):
        raise ValueError("My Photos AWS bucket names must use normalized S3 DNS syntax")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return
    raise ValueError("My Photos AWS bucket names cannot be formatted as IP addresses")


def _validate_kms_key_arn(value: str, *, region: str) -> str:
    match = _KMS_KEY_ARN_PATTERN.fullmatch(value)
    expected_partition = (
        "aws-cn" if region.startswith("cn-") else "aws-us-gov" if "-gov-" in region else "aws"
    )
    if match is None or match.group(1) != expected_partition or match.group(2) != region:
        raise ValueError(
            "My Photos KMS keys must be canonical key ARNs in the configured AWS region"
        )
    return match.group(3)


def validate_production_provider_shape(settings: _MyPhotosT) -> _MyPhotosT:
    aws_rekognition_selected = "aws_rekognition" in {
        settings.liveness_provider,
        settings.face_search_provider,
    }
    s3_selected = settings.media_provider == "s3"
    if not (aws_rekognition_selected or s3_selected):
        return settings
    if (settings.liveness_provider, settings.face_search_provider, settings.media_provider) != (
        "aws_rekognition",
        "aws_rekognition",
        "s3",
    ):
        raise ValueError(
            "Production My Photos activation requires the complete AWS Rekognition/S3 provider set"
        )
    if settings.aws_region is None:
        raise ValueError("MY_PHOTOS_AWS_REGION is required for production providers")
    _validate_reference_keys(settings)
    _validate_storage_origins(settings)
    liveness_kms_account = _validate_liveness_storage(settings, region=settings.aws_region)
    _validate_gallery_storage(
        settings, region=settings.aws_region, liveness_kms_account=liveness_kms_account
    )
    return settings


def _validate_reference_keys(settings: MyPhotosSettings) -> None:
    scope_secret = (
        settings.aws_scope_hmac_secret.get_secret_value()
        if settings.aws_scope_hmac_secret is not None
        else ""
    )
    if len(scope_secret) < 32:
        raise ValueError("MY_PHOTOS_AWS_SCOPE_HMAC_SECRET must contain at least 32 characters")
    if settings.aws_provider_hmac_key_id is None:
        raise ValueError("MY_PHOTOS_AWS_PROVIDER_HMAC_KEY_ID is required")
    secret = (
        settings.aws_provider_hmac_secret.get_secret_value()
        if settings.aws_provider_hmac_secret is not None
        else ""
    )
    if len(secret) < 32:
        raise ValueError(
            "MY_PHOTOS_AWS_PROVIDER_HMAC_SECRET must contain at least 32 characters"
        )
    if len(settings.aws_provider_hmac_previous_keys) > 3:
        raise ValueError("My Photos AWS reference verification key ring exceeds 3 keys")
    if settings.aws_provider_hmac_key_id in settings.aws_provider_hmac_previous_keys:
        raise ValueError(
            "Active My Photos AWS reference key cannot appear in the previous ring"
        )
    key_pattern = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    previous_values: list[str] = []
    for key_id, previous_secret in settings.aws_provider_hmac_previous_keys.items():
        value = previous_secret.get_secret_value()
        if key_pattern.fullmatch(key_id) is None or len(value) < 32:
            raise ValueError("My Photos AWS previous reference key ring is invalid")
        previous_values.append(value)
    if len({secret, *previous_values}) != 1 + len(previous_values):
        raise ValueError("My Photos AWS reference signing secrets must be distinct")


def _validate_storage_origins(settings: MyPhotosSettings) -> None:
    for name, prefix in (
        ("MY_PHOTOS_AWS_LIVENESS_OUTPUT_PREFIX", settings.aws_liveness_output_prefix),
        ("MY_PHOTOS_AWS_MEDIA_KEY_PREFIX", settings.aws_media_key_prefix),
    ):
        if (
            prefix.endswith("/")
            or "//" in prefix
            or any(part in {".", ".."} for part in prefix.split("/"))
        ):
            raise ValueError(f"{name} must be a normalized object-key prefix")
    if settings.aws_s3_endpoint_url is not None:
        endpoint = urlsplit(settings.aws_s3_endpoint_url)
        try:
            endpoint.port
        except ValueError as exc:
            raise ValueError(
                "MY_PHOTOS_AWS_S3_ENDPOINT_URL must be a reviewed HTTPS origin"
            ) from exc
        if (
            endpoint.scheme != "https"
            or endpoint.hostname is None
            or endpoint.username is not None
            or endpoint.password is not None
            or endpoint.query
            or endpoint.fragment
            or "//" in endpoint.path
            or any(part in {".", ".."} for part in endpoint.path.split("/"))
        ):
            raise ValueError("MY_PHOTOS_AWS_S3_ENDPOINT_URL must be a reviewed HTTPS origin")
    elif settings.aws_expected_bucket_owner is None:
        raise ValueError(
            "MY_PHOTOS_AWS_EXPECTED_BUCKET_OWNER is required for the AWS S3 endpoint"
        )


def _validate_liveness_storage(settings: MyPhotosSettings, *, region: str) -> str:
    if settings.aws_liveness_output_bucket is None:
        raise ValueError("MY_PHOTOS_AWS_LIVENESS_OUTPUT_BUCKET is required for Face Liveness")
    _validate_s3_bucket_name(settings.aws_liveness_output_bucket)
    if settings.aws_liveness_kms_key_id is None:
        raise ValueError("MY_PHOTOS_AWS_LIVENESS_KMS_KEY_ID is required")
    liveness_kms_account = _validate_kms_key_arn(
        settings.aws_liveness_kms_key_id,
        region=region,
    )
    if settings.liveness_session_ttl_seconds > 180:
        raise ValueError(
            "MY_PHOTOS_LIVENESS_SESSION_TTL_SECONDS cannot exceed AWS's 180-second session"
        )
    if settings.reference_frame_retention_seconds <= 0:
        raise ValueError(
            "MY_PHOTOS_REFERENCE_FRAME_RETENTION_SECONDS must be explicitly reviewed "
            "for AWS Face Liveness"
        )
    if settings.provider_audit_image_retention_enabled != (
        settings.aws_liveness_audit_images_limit > 0
    ):
        raise ValueError("AWS liveness audit-image retention flag and limit must agree")
    if settings.native_temporary_credentials_mode != "cognito_identity_pool":
        raise ValueError(
            "MY_PHOTOS_NATIVE_TEMPORARY_CREDENTIALS_MODE must equal "
            "cognito_identity_pool for AWS Face Liveness"
        )
    if settings.aws_cognito_identity_pool_id is None:
        raise ValueError("MY_PHOTOS_AWS_COGNITO_IDENTITY_POOL_ID is required for Cognito mode")
    return liveness_kms_account


def _validate_gallery_storage(
    settings: MyPhotosSettings, *, region: str, liveness_kms_account: str
) -> None:
    if settings.aws_media_bucket is None:
        raise ValueError("MY_PHOTOS_AWS_MEDIA_BUCKET is required for Rekognition and S3 media")
    _validate_s3_bucket_name(settings.aws_media_bucket)
    if settings.aws_media_kms_key_id is None:
        raise ValueError("MY_PHOTOS_AWS_MEDIA_KMS_KEY_ID is required")
    media_kms_account = _validate_kms_key_arn(
        settings.aws_media_kms_key_id,
        region=region,
    )
    if media_kms_account != liveness_kms_account or (
        settings.aws_expected_bucket_owner is not None
        and media_kms_account != settings.aws_expected_bucket_owner
    ):
        raise ValueError(
            "My Photos KMS key ARNs must use the reviewed AWS bucket-owner account"
        )
    if settings.maximum_search_results > 4_096:
        raise ValueError(
            "MY_PHOTOS_MAXIMUM_SEARCH_RESULTS cannot exceed SearchFacesByImage's 4096 limit"
        )
    if settings.match_config_version.startswith("uncalibrated"):
        raise ValueError(
            "A calibrated MY_PHOTOS_MATCH_CONFIG_VERSION is required for AWS matching"
        )
