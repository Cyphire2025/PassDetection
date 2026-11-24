"""My Photos provider admission, matching and retention policy."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config.my_photos_aws_policy import (
    _validate_kms_key_arn as _validate_kms_key_arn,
)
from app.core.config.my_photos_aws_policy import (
    _validate_s3_bucket_name as _validate_s3_bucket_name,
)
from app.core.config.my_photos_aws_policy import (
    validate_production_provider_shape,
)


class MyPhotosSettings(BaseSettings):
    """Fail-closed provider, matching, pagination, and job policy for My Photos."""

    model_config = SettingsConfigDict(env_prefix="MY_PHOTOS_", env_file=".env", extra="ignore")

    liveness_provider: Literal["disabled", "development", "aws_rekognition"] = "disabled"
    face_search_provider: Literal["disabled", "development", "aws_rekognition"] = "disabled"
    media_provider: Literal["disabled", "development", "s3"] = "disabled"
    development_fixtures_enabled: bool = False
    development_scenario: Literal[
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
    ] = "success"
    consent_version: str = Field(default="my-photos-biometric-v1", min_length=3, max_length=64)
    liveness_session_ttl_seconds: int = Field(default=180, ge=30, le=300)
    liveness_provider_claim_seconds: int = Field(default=30, ge=10, le=120)
    liveness_provider_timeout_seconds: int = Field(default=20, ge=1, le=60)
    provider_audit_image_retention_enabled: bool = False
    # A production reference may be needed by later gallery revisions. The
    # value remains disabled by default and must align with the reviewed trip/
    # enrollment window plus the output bucket lifecycle.
    reference_frame_retention_seconds: int = Field(default=0, ge=0, le=31_536_000)
    liveness_confidence_threshold: float = Field(default=90.0, ge=0.0, le=100.0)
    maximum_liveness_attempts: int = Field(default=5, ge=1, le=20)
    liveness_cooldown_seconds: int = Field(default=900, ge=30, le=86_400)
    page_size: int = Field(default=48, ge=12, le=60)
    maximum_page_size: int = Field(default=60, ge=12, le=100)
    best_match_threshold: float = Field(default=92.0, ge=0.0, le=100.0)
    possible_match_threshold: float = Field(default=80.0, ge=0.0, le=100.0)
    match_config_version: str = Field(default="uncalibrated-v1", min_length=3, max_length=64)
    # The provider adapter may internally paginate, but the domain result must
    # not silently truncate a passenger's matches below a full V1 gallery.
    maximum_search_results: int = Field(default=5_000, ge=1, le=5_000)
    job_batch_size: int = Field(default=100, ge=10, le=500)
    index_max_failure_ratio: float = Field(default=0.05, ge=0.0, le=1.0)
    job_max_attempts: int = Field(default=5, ge=1, le=20)
    # Celery's My Photos hard envelope is 75 seconds; the durable lease must
    # outlive it so a killed task cannot race its redelivery finalizer.
    job_lease_seconds: int = Field(default=120, ge=90, le=900)
    face_search_provider_timeout_seconds: int = Field(default=20, ge=1, le=60)
    job_retry_base_seconds: int = Field(default=5, ge=1, le=60)
    job_retry_max_seconds: int = Field(default=300, ge=30, le=3_600)
    provider_retry_after_seconds: int = Field(default=30, ge=1, le=3_600)
    provider_deletion_batch_size: int = Field(default=25, ge=1, le=100)
    provider_deletion_concurrency: int = Field(default=4, ge=1, le=8)
    provider_deletion_max_attempts: int = Field(default=10, ge=1, le=20)
    provider_deletion_claim_seconds: int = Field(default=180, ge=30, le=300)
    recovery_batch_size: int = Field(default=100, ge=10, le=500)
    delivery_authorization_ttl_seconds: int = Field(default=300, ge=60, le=900)
    delivery_claim_seconds: int = Field(default=60, ge=15, le=300)
    delivery_authorization_concurrency: int = Field(default=4, ge=1, le=8)
    media_provider_timeout_seconds: int = Field(default=20, ge=1, le=60)
    maximum_delivery_batch: int = Field(default=50, ge=1, le=100)
    development_fixture_asset_count: int = Field(default=5_000, ge=5_000, le=5_000)
    development_fixture_match_count: int = Field(default=57, ge=57, le=57)

    # Production AWS values are deliberately unset. Selecting an AWS adapter
    # without every required scope/retention/credential-broker value fails
    # validation before any provider client is constructed.
    aws_region: str | None = Field(
        default=None,
        min_length=3,
        max_length=32,
        pattern=r"^[a-z]{2}(?:-gov)?-[a-z]+-\d$",
    )
    aws_liveness_output_bucket: str | None = Field(default=None, min_length=3, max_length=63)
    aws_liveness_output_prefix: str = Field(
        default="my-photos/liveness",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9!_.*'()/-]*$",
    )
    aws_liveness_kms_key_id: str | None = Field(default=None, min_length=1, max_length=2_048)
    aws_liveness_audit_images_limit: int = Field(default=0, ge=0, le=4)
    native_temporary_credentials_mode: Literal["disabled", "cognito_identity_pool"] = "disabled"
    aws_cognito_identity_pool_id: str | None = Field(
        default=None,
        min_length=8,
        max_length=128,
        pattern=r"^[a-z]{2}(?:-gov)?-[a-z]+-\d:[0-9a-f-]{36}$",
    )
    aws_media_bucket: str | None = Field(default=None, min_length=3, max_length=63)
    aws_media_kms_key_id: str | None = Field(default=None, min_length=1, max_length=2_048)
    aws_media_key_prefix: str = Field(
        default="my-photos/media",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9!_.*'()/-]*$",
    )
    aws_s3_endpoint_url: str | None = Field(default=None, min_length=8, max_length=512)
    aws_s3_addressing_style: Literal["auto", "virtual", "path"] = "auto"
    aws_expected_bucket_owner: str | None = Field(
        default=None,
        min_length=12,
        max_length=12,
        pattern=r"^[0-9]{12}$",
    )
    aws_collection_prefix: str = Field(
        default="pd-my-photos",
        min_length=1,
        max_length=48,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$",
    )
    # Scope derivation is deliberately separate from opaque-reference signing:
    # changing it requires an explicit collection/object migration. Reference
    # signing can rotate normally through the bounded previous-key ring.
    aws_scope_hmac_secret: SecretStr | None = Field(default=None, repr=False)
    aws_provider_hmac_key_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )
    aws_provider_hmac_secret: SecretStr | None = Field(default=None, repr=False)
    aws_provider_hmac_previous_keys: dict[str, SecretStr] = Field(
        default_factory=dict,
        repr=False,
    )
    aws_index_quality_filter: Literal["NONE", "LOW", "MEDIUM", "HIGH", "AUTO"] = "AUTO"
    aws_index_max_faces_per_asset: int = Field(default=100, ge=1, le=100)
    aws_index_concurrency: int = Field(default=4, ge=1, le=8)
    aws_search_quality_filter: Literal["NONE", "LOW", "MEDIUM", "HIGH", "AUTO"] = "AUTO"
    aws_connect_timeout_seconds: float = Field(default=3.0, ge=0.5, le=10.0)
    aws_read_timeout_seconds: float = Field(default=10.0, ge=1.0, le=30.0)
    aws_max_attempts: int = Field(default=3, ge=1, le=5)
    aws_max_pool_connections: int = Field(default=16, ge=4, le=64)

    @model_validator(mode="after")
    def validate_thresholds_and_pages(self) -> Self:
        if self.possible_match_threshold >= self.best_match_threshold:
            raise ValueError(
                "MY_PHOTOS_POSSIBLE_MATCH_THRESHOLD must be lower than "
                "MY_PHOTOS_BEST_MATCH_THRESHOLD"
            )
        if self.page_size > self.maximum_page_size:
            raise ValueError("MY_PHOTOS_PAGE_SIZE cannot exceed MY_PHOTOS_MAXIMUM_PAGE_SIZE")
        if self.job_retry_base_seconds > self.job_retry_max_seconds:
            raise ValueError(
                "MY_PHOTOS_JOB_RETRY_BASE_SECONDS cannot exceed MY_PHOTOS_JOB_RETRY_MAX_SECONDS"
            )
        if self.liveness_provider_timeout_seconds >= self.liveness_provider_claim_seconds:
            raise ValueError(
                "MY_PHOTOS_LIVENESS_PROVIDER_TIMEOUT_SECONDS must be shorter than "
                "MY_PHOTOS_LIVENESS_PROVIDER_CLAIM_SECONDS"
            )
        if self.face_search_provider_timeout_seconds >= self.job_lease_seconds:
            raise ValueError(
                "MY_PHOTOS_FACE_SEARCH_PROVIDER_TIMEOUT_SECONDS must be shorter than "
                "MY_PHOTOS_JOB_LEASE_SECONDS"
            )
        if self.media_provider_timeout_seconds >= self.delivery_claim_seconds:
            raise ValueError(
                "MY_PHOTOS_MEDIA_PROVIDER_TIMEOUT_SECONDS must be shorter than "
                "MY_PHOTOS_DELIVERY_CLAIM_SECONDS"
            )
        if self.face_search_provider_timeout_seconds > 60:
            raise ValueError("My Photos face-search timeout exceeds the worker envelope")
        if self.media_provider_timeout_seconds > 60:
            raise ValueError("My Photos media timeout exceeds the worker envelope")
        if self.liveness_provider_timeout_seconds >= self.provider_deletion_claim_seconds:
            raise ValueError(
                "MY_PHOTOS_LIVENESS_PROVIDER_TIMEOUT_SECONDS must be shorter than "
                "MY_PHOTOS_PROVIDER_DELETION_CLAIM_SECONDS"
            )
        return self

    @model_validator(mode="after")
    def validate_development_fixture_provider_shape(self) -> Self:
        if not self.development_fixtures_enabled:
            return self
        if {
            self.liveness_provider,
            self.face_search_provider,
            self.media_provider,
        } != {"development"}:
            raise ValueError(
                "MY_PHOTOS_DEVELOPMENT_FIXTURES_ENABLED requires every My Photos "
                "provider to be development"
            )
        return self

    @model_validator(mode="after")
    def validate_production_provider_shape(self) -> Self:
        return validate_production_provider_shape(self)

    def validate_runtime_environment(
        self,
        app_env: Literal["development", "staging", "production"],
    ) -> None:
        """Reject provider options that exist only for explicit local adapter tests."""

        development_selected = "development" in {
            self.liveness_provider,
            self.face_search_provider,
            self.media_provider,
        }
        if app_env != "development" and (development_selected or self.development_fixtures_enabled):
            raise ValueError(
                "Development My Photos providers and fixtures are forbidden outside "
                "development (APP_ENV=development only)"
            )
        aws_selected = (
            "aws_rekognition"
            in {
                self.liveness_provider,
                self.face_search_provider,
            }
            or self.media_provider == "s3"
        )
        if app_env != "development" and aws_selected and self.aws_s3_endpoint_url is not None:
            raise ValueError(
                "MY_PHOTOS_AWS_S3_ENDPOINT_URL is allowed only in APP_ENV=development; "
                "production AWS media must use the distinct AWS S3 object origin"
            )
