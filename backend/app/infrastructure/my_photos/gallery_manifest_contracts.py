"""Gallery manifest contracts owner."""

from __future__ import annotations

import math
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.application.my_photos.limits import MAX_MY_PHOTOS_MEDIA_BYTES
from app.application.my_photos.providers import MediaAvailabilityResult
from app.infrastructure.my_photos.gallery_manifest_fingerprints import _json_fingerprint

_BATCH_SIZE = 100
_MAX_MANIFEST_ASSETS = 5000
_MAX_BATCHES = _MAX_MANIFEST_ASSETS // _BATCH_SIZE


class GalleryManifestVariant(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    kind: Literal["thumbnail", "preview", "analysis", "optimized"]
    storage_reference: str = Field(min_length=1, max_length=512)
    mime_type: Literal["image/jpeg", "image/png", "image/webp"]
    width: int = Field(ge=1, le=100000)
    height: int = Field(ge=1, le=100000)
    byte_size: int = Field(ge=1, le=MAX_MY_PHOTOS_MEDIA_BYTES)
    checksum_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    delivery_version: int = Field(ge=1, le=2147483647)

    @model_validator(mode="after")
    def reject_public_locator(self) -> GalleryManifestVariant:
        if "://" in self.storage_reference:
            raise ValueError("Variant storage references must be opaque object keys")
        return self


class GalleryManifestAsset(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    immutable_asset_key: str = Field(min_length=8, max_length=128, pattern="^[A-Za-z0-9._:-]+$")
    archive_reference: str = Field(min_length=1, max_length=512)
    original_filename: str = Field(min_length=1, max_length=255)
    mime_type: Literal["image/jpeg", "image/png", "image/webp"]
    width: int = Field(ge=1, le=100000)
    height: int = Field(ge=1, le=100000)
    byte_size: int = Field(ge=1, le=MAX_MY_PHOTOS_MEDIA_BYTES)
    checksum_sha256: str = Field(pattern="^[0-9a-f]{64}$")
    captured_at: datetime | None = None
    orientation: int = Field(default=1, ge=1, le=8)
    sort_rank: int = Field(ge=0, le=9223372036854775807)
    variants: tuple[GalleryManifestVariant, ...] = Field(min_length=3, max_length=4)

    @model_validator(mode="after")
    def validate_asset_shape(self) -> GalleryManifestAsset:
        if "://" in self.archive_reference:
            raise ValueError("Archive references must be opaque object keys")
        if "/" in self.original_filename or "\\" in self.original_filename:
            raise ValueError("Original filename must not contain a path")
        if self.original_filename.strip() != self.original_filename:
            raise ValueError("Original filename must be trimmed")
        if self.captured_at is not None and self.captured_at.utcoffset() is None:
            raise ValueError("Captured timestamps must carry a timezone")
        kinds = {variant.kind for variant in self.variants}
        if len(kinds) != len(self.variants):
            raise ValueError("Manifest variant kinds must be unique")
        if {"thumbnail", "preview", "analysis"} - kinds:
            raise ValueError("Thumbnail, preview, and analysis variants are required")
        return self


class GalleryManifestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    agency_id: uuid.UUID
    group_id: uuid.UUID
    manifest_identity: str = Field(min_length=8, max_length=128, pattern="^[A-Za-z0-9._:-]+$")
    target_revision: int = Field(ge=1, le=2147483647)
    total_asset_count: int = Field(ge=1, le=_MAX_MANIFEST_ASSETS)
    batch_count: int = Field(ge=1, le=_MAX_BATCHES)
    batch_index: int = Field(ge=0, le=_MAX_BATCHES - 1)
    finalize: bool = False
    retention_policy_version: str = Field(min_length=3, max_length=64, pattern="^[A-Za-z0-9._:-]+$")
    retention_days: int = Field(ge=1, le=3650)
    availability_starts_at: datetime
    availability_ends_at: datetime
    all_group_photos_enabled: bool = False
    assets: tuple[GalleryManifestAsset, ...] = Field(min_length=1, max_length=_BATCH_SIZE)

    @model_validator(mode="after")
    def validate_manifest_shape(self) -> GalleryManifestRequest:
        if self.availability_starts_at.utcoffset() is None:
            raise ValueError("Gallery availability start must carry a timezone")
        if self.availability_ends_at.utcoffset() is None:
            raise ValueError("Gallery availability end must carry a timezone")
        if self.availability_ends_at <= self.availability_starts_at:
            raise ValueError("Gallery availability end must follow its start")
        expected_batches = math.ceil(self.total_asset_count / _BATCH_SIZE)
        if self.batch_count != expected_batches or self.batch_index >= self.batch_count:
            raise ValueError("Manifest batch count/index does not match the declared total")
        expected_batch_assets = min(
            _BATCH_SIZE, self.total_asset_count - self.batch_index * _BATCH_SIZE
        )
        if len(self.assets) != expected_batch_assets:
            raise ValueError("Manifest batch asset count is incomplete")
        keys = {asset.immutable_asset_key for asset in self.assets}
        ranks = {asset.sort_rank for asset in self.assets}
        if len(keys) != len(self.assets):
            raise ValueError("Manifest asset identities must be unique within a batch")
        if len(ranks) != len(self.assets):
            raise ValueError("Manifest sort ranks must be unique within a batch")
        return self

    def header_fingerprint(self, *, provider_configuration_fingerprint: str) -> str:
        canonical = self.model_dump(mode="json", exclude={"assets", "batch_index", "finalize"})
        canonical["provider_configuration_fingerprint"] = provider_configuration_fingerprint
        return _json_fingerprint(canonical)

    def batch_fingerprint(self) -> str:
        return _json_fingerprint(
            {
                "batch_index": self.batch_index,
                "assets": [asset.model_dump(mode="json") for asset in self.assets],
            }
        )


class GalleryManifestLocator(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    agency_id: uuid.UUID
    group_id: uuid.UUID
    manifest_identity: str = Field(min_length=8, max_length=128, pattern="^[A-Za-z0-9._:-]+$")


ManifestDispatchState = Literal["dispatched", "deferred", "not_required"]
ManifestState = Literal["receiving", "queued", "running", "succeeded", "failed", "cancelled"]


@dataclass(frozen=True, slots=True)
class GalleryManifestResult:
    manifest_id: uuid.UUID
    gallery_id: uuid.UUID
    index_job_id: uuid.UUID | None
    target_revision: int
    received_asset_count: int
    total_asset_count: int
    batch_count: int
    state: ManifestState
    batch_replay: bool
    manifest_replay: bool
    content_fingerprint: str | None
    dispatch_state: ManifestDispatchState


@dataclass(frozen=True, slots=True)
class GalleryManifestStatus:
    manifest_id: uuid.UUID
    gallery_id: uuid.UUID
    index_job_id: uuid.UUID | None
    target_revision: int
    received_asset_count: int
    total_asset_count: int
    batch_count: int
    received_batch_indices: tuple[int, ...]
    missing_batch_indices: tuple[int, ...]
    state: str
    cancellation_requested: bool
    content_fingerprint: str | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class _VerifiedAsset:
    asset: GalleryManifestAsset
    original_storage_reference: str
    variants: Mapping[str, MediaAvailabilityResult]


GalleryManifestVariant.__module__ = "app.infrastructure.my_photos.gallery_ingestion"

GalleryManifestAsset.__module__ = "app.infrastructure.my_photos.gallery_ingestion"

GalleryManifestRequest.__module__ = "app.infrastructure.my_photos.gallery_ingestion"

GalleryManifestLocator.__module__ = "app.infrastructure.my_photos.gallery_ingestion"

GalleryManifestResult.__module__ = "app.infrastructure.my_photos.gallery_ingestion"

GalleryManifestStatus.__module__ = "app.infrastructure.my_photos.gallery_ingestion"

_VerifiedAsset.__module__ = "app.infrastructure.my_photos.gallery_ingestion"
