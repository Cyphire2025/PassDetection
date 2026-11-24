"""Validated AWS adapter configuration; raw signing material is excluded from repr."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, cast


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
    scope_hmac_secret: bytes = field(repr=False)
    reference_active_key_id: str
    reference_signing_keys: Mapping[str, bytes] = field(repr=False)
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
