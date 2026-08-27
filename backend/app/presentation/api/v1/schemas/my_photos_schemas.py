"""Strict passenger-facing API contracts for My Photos."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.application.my_photos.limits import MAX_MY_PHOTOS_MEDIA_BYTES
from app.application.my_photos.states import (
    ChallengeMode,
    EnrollmentStatus,
    ExperienceState,
    GalleryStatus,
    MatchFeedback,
    MatchFilter,
    MatchTier,
    MediaAvailability,
)


class MyPhotosStrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class MyPhotosCapabilityResponse(MyPhotosStrictModel):
    feature_enabled: bool
    provider_ready: bool
    provider_state: Literal["ready", "not_configured", "temporarily_unavailable"]
    client_flow: Literal["unavailable", "development_simulator", "native"]
    supported_challenge_modes: list[ChallengeMode] = Field(max_length=2)
    retryable: bool

    @model_validator(mode="after")
    def validate_provider_shape(self) -> Self:
        if self.provider_ready != (self.provider_state == "ready"):
            raise ValueError("Provider readiness and state must agree")
        if self.provider_state == "not_configured":
            if self.client_flow != "unavailable" or self.retryable:
                raise ValueError("Unconfigured providers must fail closed")
        elif self.client_flow == "unavailable":
            raise ValueError("Configured providers require a configured client flow")
        if self.provider_state == "temporarily_unavailable" and not self.retryable:
            raise ValueError("Temporary provider outages must be retryable")
        return self


class MyPhotosGalleryResponse(MyPhotosStrictModel):
    status: GalleryStatus
    published_revision: int = Field(ge=0)
    media_version: int = Field(ge=0)
    face_index_version: int = Field(ge=0)
    total_asset_count: int = Field(ge=0, le=1_000_000)
    indexed_asset_count: int = Field(ge=0, le=1_000_000)
    failed_asset_count: int = Field(ge=0, le=1_000_000)
    all_group_photos_enabled: bool
    published_at: datetime | None
    updated_at: datetime

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        if self.indexed_asset_count + self.failed_asset_count > self.total_asset_count:
            raise ValueError("Gallery progress counts exceed total assets")
        return self


class MyPhotosConsentResponse(MyPhotosStrictModel):
    required: bool
    required_version: str = Field(min_length=3, max_length=64)
    accepted_version: str | None = Field(default=None, min_length=3, max_length=64)
    accepted_at: datetime | None
    purpose: str = Field(min_length=10, max_length=500)
    biometric_data_used: str = Field(min_length=10, max_length=500)
    retention: str = Field(min_length=10, max_length=500)
    provider_processing: str = Field(min_length=10, max_length=500)
    deletion: str = Field(min_length=10, max_length=500)


class MyPhotosEnrollmentResponse(MyPhotosStrictModel):
    status: EnrollmentStatus
    reference_version: int | None = Field(default=None, ge=1)
    attempts_remaining: int = Field(ge=0, le=20)
    cooldown_until: datetime | None
    enrolled_at: datetime | None
    updated_at: datetime


class MyPhotosSearchRunResponse(MyPhotosStrictModel):
    id: uuid.UUID
    status: Literal["queued", "searching", "complete", "failed", "cancelled"]
    processed_face_count: int = Field(ge=0, le=1_000_000)
    total_face_count: int = Field(ge=0, le=1_000_000)
    progress_percent: int = Field(ge=0, le=100)
    matched_photo_count: int = Field(ge=0, le=1_000_000)
    best_match_count: int = Field(ge=0, le=1_000_000)
    possible_match_count: int = Field(ge=0, le=1_000_000)
    started_at: datetime | None
    completed_at: datetime | None
    error_code: str | None = Field(
        default=None, min_length=3, max_length=64, pattern=r"^[A-Z0-9_]+$"
    )

    @model_validator(mode="after")
    def validate_progress(self) -> Self:
        if self.processed_face_count > self.total_face_count:
            raise ValueError("Search processed count exceeds total")
        if self.best_match_count + self.possible_match_count != self.matched_photo_count:
            raise ValueError("Search tier counts must equal matched-photo count")
        return self


class MyPhotosResultsResponse(MyPhotosStrictModel):
    # Exact active match snapshot served by Best/Possible page requests. Zero
    # means no materialized match snapshot; All Group Photos instead follows
    # gallery.published_revision.
    snapshot_revision: int = Field(ge=0)
    match_count: int = Field(ge=0, le=1_000_000)
    new_photo_count: int = Field(ge=0, le=1_000_000)
    downloadable_count: int = Field(ge=0, le=1_000_000)
    preparing_count: int = Field(ge=0, le=1_000_000)
    last_updated_at: datetime | None


class MyPhotosSummaryResponse(MyPhotosStrictModel):
    group_id: uuid.UUID
    group_name: str = Field(min_length=1, max_length=255)
    experience_state: ExperienceState
    server_time: datetime
    capability: MyPhotosCapabilityResponse
    gallery: MyPhotosGalleryResponse
    consent: MyPhotosConsentResponse
    enrollment: MyPhotosEnrollmentResponse
    search: MyPhotosSearchRunResponse | None
    results: MyPhotosResultsResponse

    @model_validator(mode="after")
    def validate_feature_state(self) -> Self:
        if not self.capability.feature_enabled and self.experience_state != "feature_unavailable":
            raise ValueError("Disabled My Photos must use feature_unavailable")
        if (
            self.capability.feature_enabled
            and self.gallery.status == "ready"
            and self.results.snapshot_revision == 0
        ):
            raise ValueError("A ready My Photos gallery requires a published result snapshot")
        return self


class MyPhotosConsentRequest(MyPhotosStrictModel):
    consent_version: str = Field(min_length=3, max_length=64)
    accepted: Literal[True]
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class MyPhotosLivenessStartRequest(MyPhotosStrictModel):
    challenge_mode: ChallengeMode
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class MyPhotosLivenessSessionResponse(MyPhotosStrictModel):
    session_id: uuid.UUID
    status: Literal["created"]
    challenge_mode: ChallengeMode
    client_flow: Literal["development_simulator", "native"]
    native_launch_handle: str | None = Field(default=None, min_length=1, max_length=512)
    expires_at: datetime
    attempts_remaining: int = Field(ge=0, le=20)
    photosensitivity_warning: str = Field(min_length=10, max_length=500)

    @model_validator(mode="after")
    def validate_native_launch_shape(self) -> Self:
        if self.client_flow == "native":
            if self.native_launch_handle is None:
                raise ValueError("Native Face Scan requires an opaque launch handle")
            if (
                self.native_launch_handle != self.native_launch_handle.strip()
                or not self.native_launch_handle.isprintable()
                or "://" in self.native_launch_handle
            ):
                raise ValueError("Invalid native Face Scan launch handle")
        elif self.native_launch_handle is not None:
            raise ValueError("Development Face Scan cannot expose native launch data")
        return self


class MyPhotosLivenessCompleteRequest(MyPhotosStrictModel):
    outcome: Literal["completed", "cancelled", "expired", "failed"]
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class MyPhotosLivenessCompleteResponse(MyPhotosStrictModel):
    session_id: uuid.UUID
    session_status: Literal["completed", "cancelled", "expired", "rejected", "failed"]
    enrollment_status: EnrollmentStatus
    search_run_id: uuid.UUID | None
    search_status: Literal["not_started", "queued"]
    retryable: bool
    error_code: str | None = Field(
        default=None, min_length=3, max_length=64, pattern=r"^[A-Z0-9_]+$"
    )
    cooldown_until: datetime | None


class MyPhotosSearchResponse(MyPhotosStrictModel):
    search: MyPhotosSearchRunResponse | None


class MyPhotosMediaDescriptor(MyPhotosStrictModel):
    state: MediaAvailability
    transport: Literal[
        "unavailable", "development_fixture", "authenticated_api", "direct_object_storage"
    ]
    cache_key: str = Field(min_length=8, max_length=192, pattern=r"^[A-Za-z0-9._:-]+$")
    max_width: int = Field(ge=1, le=4096)
    max_height: int = Field(ge=1, le=4096)
    resource_path: str | None = Field(
        default=None,
        min_length=20,
        max_length=512,
        pattern=r"^/api/v1/mobile/trips/[0-9a-f-]+/my-photos/photos/[0-9a-f-]+/content/(thumbnail|preview)$",
    )
    authorization_id: uuid.UUID | None
    expires_at: datetime | None

    @model_validator(mode="after")
    def validate_transport_shape(self) -> Self:
        if self.transport == "authenticated_api":
            if self.resource_path is None or self.authorization_id is not None:
                raise ValueError("Authenticated media requires only a relative resource path")
        elif self.transport == "direct_object_storage":
            if self.authorization_id is None or self.resource_path is not None:
                raise ValueError("Direct media requires only an opaque authorization ID")
        elif self.resource_path is not None or self.authorization_id is not None:
            raise ValueError("Unavailable or fixture media cannot carry delivery locators")
        return self


class MyPhotosPhotoResponse(MyPhotosStrictModel):
    asset_id: uuid.UUID
    match_id: uuid.UUID | None
    tier: MatchTier | None
    feedback: MatchFeedback
    width: int = Field(ge=1, le=100_000)
    height: int = Field(ge=1, le=100_000)
    aspect_ratio: float = Field(gt=0, le=100)
    captured_at: datetime | None
    thumbnail_state: MediaAvailability
    preview_state: MediaAvailability
    original_state: MediaAvailability
    availability_state: MediaAvailability
    thumbnail: MyPhotosMediaDescriptor
    preview: MyPhotosMediaDescriptor
    download_qualities: list[Literal["original", "optimized"]] = Field(max_length=2)
    original_byte_size: int = Field(gt=0, le=MAX_MY_PHOTOS_MEDIA_BYTES)
    original_checksum_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    preparing: bool


class MyPhotosPhotoPageResponse(MyPhotosStrictModel):
    snapshot_revision: int = Field(ge=1)
    filter: MatchFilter
    items: list[MyPhotosPhotoResponse] = Field(max_length=60)
    next_cursor: str | None = Field(default=None, min_length=16, max_length=768)
    page_size: int = Field(ge=1, le=60)
    total_count: int = Field(ge=0, le=1_000_000)

    @model_validator(mode="after")
    def validate_page_window(self) -> Self:
        if len(self.items) > self.page_size:
            raise ValueError("Photo page exceeds the declared page size")
        if len({item.asset_id for item in self.items}) != len(self.items):
            raise ValueError("Photo page contains duplicate assets")
        return self


class MyPhotosFeedbackRequest(MyPhotosStrictModel):
    feedback: Literal["this_is_me", "not_me"]
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class MyPhotosFeedbackResponse(MyPhotosStrictModel):
    asset_id: uuid.UUID
    feedback: Literal["this_is_me", "not_me"]
    updated_at: datetime


class MyPhotosDeleteEnrollmentRequest(MyPhotosStrictModel):
    scope: Literal["enrollment_only", "enrollment_and_search_data"]
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class MyPhotosDeleteEnrollmentResponse(MyPhotosStrictModel):
    enrollment_status: Literal["deleted"]
    removed_search_data: bool
    local_downloads_affected: Literal[False]
    provider_deletion_status: Literal["not_required", "pending", "complete", "failed"]
    provider_deletion_retryable: bool
    deleted_at: datetime


class MyPhotosPrepareRequest(MyPhotosStrictModel):
    quality: Literal["original", "optimized"]
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


class MyPhotosPrepareResponse(MyPhotosStrictModel):
    asset_id: uuid.UUID
    state: Literal["rehydration_requested", "preparing_delivery", "delivery_available"]
    preparation_id: uuid.UUID | None
    retry_after_seconds: int | None = Field(default=None, ge=1, le=86_400)


class MyPhotosDownloadItemRequest(MyPhotosStrictModel):
    asset_id: uuid.UUID
    quality: Literal["original", "optimized"]


class MyPhotosDownloadAuthorizationRequest(MyPhotosStrictModel):
    items: list[MyPhotosDownloadItemRequest] = Field(min_length=1, max_length=50)
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")

    @model_validator(mode="after")
    def validate_unique_items(self) -> Self:
        identities = {(item.asset_id, item.quality) for item in self.items}
        if len(identities) != len(self.items):
            raise ValueError("Download items must be unique by asset and quality")
        return self


class MyPhotosDownloadAuthorizationItemResponse(MyPhotosStrictModel):
    asset_id: uuid.UUID
    authorization_id: uuid.UUID | None
    quality: Literal["original", "optimized"]
    delivery_version: int = Field(ge=1)
    state: Literal["preparing", "available", "unavailable"]
    transport: Literal["unavailable", "development_fixture", "direct_object_storage"]
    expected_size_bytes: int | None = Field(
        default=None,
        gt=0,
        le=MAX_MY_PHOTOS_MEDIA_BYTES,
    )
    checksum_sha256: str | None = Field(
        default=None, min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    supports_ranges: bool
    expires_at: datetime | None
    retry_after_seconds: int | None = Field(default=None, ge=1, le=86_400)
    content_type: Literal["image/jpeg", "image/png", "image/webp"] | None
    resource_path: str | None = Field(
        default=None,
        min_length=20,
        max_length=512,
        pattern=r"^/api/v1/mobile/trips/[0-9a-f-]+/my-photos/download-authorizations/[0-9a-f-]+/content$",
    )

    @model_validator(mode="after")
    def validate_delivery_shape(self) -> Self:
        if self.transport == "development_fixture":
            if (
                self.state != "available"
                or self.authorization_id is None
                or self.resource_path is None
            ):
                raise ValueError("Development delivery requires an authenticated content resource")
        elif self.resource_path is not None:
            raise ValueError("Only development delivery may expose an API resource path")
        if self.transport == "direct_object_storage" and self.authorization_id is None:
            raise ValueError("Direct delivery requires an opaque authorization ID")
        if self.state == "available" and (
            self.expected_size_bytes is None
            or self.checksum_sha256 is None
            or self.expires_at is None
            or self.content_type is None
        ):
            raise ValueError("Available delivery metadata must be complete")
        if self.state != "available" and (
            self.authorization_id is not None
            or self.expected_size_bytes is not None
            or self.checksum_sha256 is not None
            or self.expires_at is not None
            or self.content_type is not None
            or self.transport != "unavailable"
        ):
            raise ValueError("Unavailable delivery cannot expose authorization metadata")
        return self


class MyPhotosDownloadAuthorizationResponse(MyPhotosStrictModel):
    authorizations: list[MyPhotosDownloadAuthorizationItemResponse] = Field(
        min_length=1, max_length=50
    )


class MyPhotosDownloadEstimateQualityResponse(MyPhotosStrictModel):
    quality: Literal["original", "optimized"]
    supported_item_count: int = Field(ge=0, le=1_000_000)
    exact_byte_total: int = Field(ge=0, le=1_000_000_000_000_000)
    maximum_item_bytes: int = Field(ge=0, le=MAX_MY_PHOTOS_MEDIA_BYTES)
    estimate_complete: bool


class MyPhotosDownloadPlanResponse(MyPhotosStrictModel):
    snapshot_revision: int = Field(ge=1)
    matched_item_count: int = Field(ge=0, le=1_000_000)
    downloadable_item_count: int = Field(ge=0, le=1_000_000)
    preparing_item_count: int = Field(ge=0, le=1_000_000)
    qualities: list[MyPhotosDownloadEstimateQualityResponse] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def validate_quality_estimates(self) -> Self:
        if {item.quality for item in self.qualities} != {"original", "optimized"}:
            raise ValueError("Download plan must include original and optimized estimates")
        if self.downloadable_item_count + self.preparing_item_count > self.matched_item_count:
            raise ValueError("Download plan availability counts exceed matched items")
        for item in self.qualities:
            if item.supported_item_count > self.matched_item_count:
                raise ValueError("Download plan supported count exceeds matched items")
            if item.estimate_complete != (item.supported_item_count == self.matched_item_count):
                raise ValueError("Download estimate completeness is inconsistent")
        return self
