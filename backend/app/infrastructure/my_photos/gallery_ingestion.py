"""Authenticated multi-batch control plane for direct-uploaded My Photos media.

Only metadata crosses this boundary. Each request carries at most 100 already-
uploaded objects; no index job exists until all batches for one revision are
durably present and an explicit finalization succeeds.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import and_, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.my_photos.errors import MyPhotosConflict, MyPhotosUnavailable
from app.application.my_photos.limits import MAX_MY_PHOTOS_MEDIA_BYTES
from app.application.my_photos.providers import (
    FaceCollectionRequest,
    FaceDeletionRequest,
    MediaAvailabilityRequest,
    MediaAvailabilityResult,
    MediaDeletionRequest,
    MediaRegistrationRequest,
)
from app.application.my_photos.states import MEDIA_DELIVERY_READY_STATES
from app.core.config.settings import Settings
from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import (
    AuthorizationError,
    EntityNotFoundError,
    StepUpRequiredError,
)
from app.infrastructure.database.gc_mobile_models import GCGroupAccessModel
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.my_photos_models import (
    MyPhotoAssetVariantModel,
    MyPhotoFaceOccurrenceModel,
    MyPhotoGalleryManifestBatchModel,
    MyPhotoGalleryManifestModel,
    MyPhotoGalleryModel,
    MyPhotoJobModel,
    MyPhotoMediaAssetModel,
)
from app.infrastructure.my_photos.providers import MyPhotosProviderBundle
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository

_BATCH_SIZE = 100
_MAX_MANIFEST_ASSETS = 5_000
_MAX_BATCHES = _MAX_MANIFEST_ASSETS // _BATCH_SIZE
_PROVIDER_CONCURRENCY = 4
_ADMIN_MFA_MAX_AGE = timedelta(minutes=10)
_STABLE_ID = re.compile(r"^[A-Za-z0-9._:-]+$")
_ProviderResultT = TypeVar("_ProviderResultT")


class GalleryManifestVariant(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    kind: Literal["thumbnail", "preview", "analysis", "optimized"]
    storage_reference: str = Field(min_length=1, max_length=512)
    mime_type: Literal["image/jpeg", "image/png", "image/webp"]
    width: int = Field(ge=1, le=100_000)
    height: int = Field(ge=1, le=100_000)
    byte_size: int = Field(ge=1, le=MAX_MY_PHOTOS_MEDIA_BYTES)
    checksum_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    delivery_version: int = Field(ge=1, le=2_147_483_647)

    @model_validator(mode="after")
    def reject_public_locator(self) -> GalleryManifestVariant:
        if "://" in self.storage_reference:
            raise ValueError("Variant storage references must be opaque object keys")
        return self


class GalleryManifestAsset(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    immutable_asset_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    archive_reference: str = Field(min_length=1, max_length=512)
    original_filename: str = Field(min_length=1, max_length=255)
    mime_type: Literal["image/jpeg", "image/png", "image/webp"]
    width: int = Field(ge=1, le=100_000)
    height: int = Field(ge=1, le=100_000)
    byte_size: int = Field(ge=1, le=MAX_MY_PHOTOS_MEDIA_BYTES)
    checksum_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    captured_at: datetime | None = None
    orientation: int = Field(default=1, ge=1, le=8)
    sort_rank: int = Field(ge=0, le=9_223_372_036_854_775_807)
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
    manifest_identity: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    target_revision: int = Field(ge=1, le=2_147_483_647)
    total_asset_count: int = Field(ge=1, le=_MAX_MANIFEST_ASSETS)
    batch_count: int = Field(ge=1, le=_MAX_BATCHES)
    batch_index: int = Field(ge=0, le=_MAX_BATCHES - 1)
    finalize: bool = False
    retention_policy_version: str = Field(
        min_length=3, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$"
    )
    retention_days: int = Field(ge=1, le=3_650)
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
            _BATCH_SIZE,
            self.total_asset_count - self.batch_index * _BATCH_SIZE,
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
        canonical = self.model_dump(
            mode="json",
            exclude={"assets", "batch_index", "finalize"},
        )
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
    manifest_identity: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")


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


class GalleryManifestRegistrationService:
    """Stage idempotent batches and finalize exactly one atomic gallery revision."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings,
        providers: MyPhotosProviderBundle,
    ) -> None:
        self._session = session
        self._settings = settings
        self._providers = providers

    async def manifest_status(
        self,
        *,
        actor: User,
        mfa_verified_at: datetime,
        locator: GalleryManifestLocator,
    ) -> GalleryManifestStatus:
        if self._session.in_transaction():
            raise RuntimeError("Manifest status requires a fresh database session")
        _require_operator(actor, locator.agency_id, mfa_verified_at)
        try:
            await self._load_scope(locator, lock=False)
            gallery = await self._locked_gallery(locator, lock=False)
            if gallery is None:
                raise EntityNotFoundError("My Photos gallery", locator.group_id)
            manifest = await self._locked_manifest(
                gallery.id,
                locator.manifest_identity,
                lock=False,
            )
            if manifest is None:
                raise EntityNotFoundError("My Photos manifest", locator.manifest_identity)
            return await self._status_snapshot(manifest)
        finally:
            await self._session.rollback()

    async def cancel_manifest(
        self,
        *,
        actor: User,
        mfa_verified_at: datetime,
        locator: GalleryManifestLocator,
    ) -> GalleryManifestStatus:
        """Request cancellation, then clean only this unpublished target revision.

        A running worker is first stopped through the durable job cancellation
        fence. Repeating the command resumes bounded provider-face cleanup and
        finally removes the local staging rows.
        """

        if self._session.in_transaction():
            raise RuntimeError("Manifest cancellation requires a fresh database session")
        _require_operator(actor, locator.agency_id, mfa_verified_at)
        provider_faces: tuple[tuple[uuid.UUID, str], ...] = ()
        provider_media_references: tuple[str, ...] = ()
        media_asset_ids: tuple[uuid.UUID, ...] = ()
        media_variant_ids: tuple[uuid.UUID, ...] = ()
        collection_reference: str | None = None
        async with self._session.begin():
            await self._load_scope(locator, lock=True)
            gallery = await self._locked_gallery(locator)
            if gallery is None:
                raise EntityNotFoundError("My Photos gallery", locator.group_id)
            manifest = await self._locked_manifest(gallery.id, locator.manifest_identity)
            if manifest is None:
                raise EntityNotFoundError("My Photos manifest", locator.manifest_identity)
            if manifest.status == "cancelled":
                pass
            elif (
                gallery.published_revision >= manifest.target_revision
                or manifest.status == "finalized"
            ):
                raise MyPhotosConflict(
                    "MY_PHOTOS_MANIFEST_ALREADY_PUBLISHED",
                    "A published gallery revision cannot be cancelled.",
                )
            else:
                job = await self._job_for_manifest(
                    gallery.id,
                    manifest.manifest_identity,
                    lock=True,
                )
                now = datetime.now(tz=UTC)
                manifest.cancellation_requested_at = manifest.cancellation_requested_at or now
                if job is not None and job.status == "succeeded":
                    raise MyPhotosConflict(
                        "MY_PHOTOS_MANIFEST_ALREADY_INDEXED",
                        "A completed gallery index cannot be cancelled.",
                    )
                if job is not None and job.status in {"queued", "running", "retrying"}:
                    first_request = job.cancellation_requested_at is None
                    job.cancellation_requested_at = job.cancellation_requested_at or now
                    if job.status in {"queued", "retrying"}:
                        job.status = "cancelled"
                        job.completed_at = now
                        job.lease_owner = None
                        job.lease_expires_at = None
                    if first_request:
                        await self._audit_cancellation_requested(
                            actor=actor,
                            gallery=gallery,
                            manifest=manifest,
                            job=job,
                        )
                elif job is not None and job.status == "failed":
                    job.cancellation_requested_at = job.cancellation_requested_at or now
                if job is None or job.status in {"failed", "cancelled"}:
                    face_rows = list(
                        (
                            await self._session.execute(
                                select(MyPhotoFaceOccurrenceModel)
                                .join(
                                    MyPhotoMediaAssetModel,
                                    MyPhotoMediaAssetModel.id
                                    == MyPhotoFaceOccurrenceModel.media_asset_id,
                                )
                                .where(
                                    MyPhotoMediaAssetModel.gallery_id == gallery.id,
                                    MyPhotoMediaAssetModel.agency_id == locator.agency_id,
                                    MyPhotoMediaAssetModel.group_id == locator.group_id,
                                    MyPhotoMediaAssetModel.published_revision
                                    == manifest.target_revision,
                                    MyPhotoFaceOccurrenceModel.active.is_(True),
                                )
                                .order_by(MyPhotoFaceOccurrenceModel.id)
                                .limit(self._settings.my_photos.provider_deletion_batch_size)
                                .with_for_update()
                            )
                        ).scalars()
                    )
                    if face_rows:
                        provider_faces = tuple(
                            (face.id, face.provider_face_reference) for face in face_rows
                        )
                        collection_reference = manifest.provider_collection_reference
                    else:
                        (
                            provider_media_references,
                            media_asset_ids,
                            media_variant_ids,
                        ) = await self._cancelled_media_batch(gallery=gallery, manifest=manifest)
                        if not provider_media_references:
                            await self._cleanup_cancelled_manifest(
                                actor=actor,
                                gallery=gallery,
                                manifest=manifest,
                            )

        if provider_faces:
            assert collection_reference is not None
            await self._delete_cancelled_provider_faces(
                locator=locator,
                collection_reference=collection_reference,
                provider_faces=provider_faces,
            )
            async with self._session.begin():
                gallery = await self._locked_gallery(locator)
                if gallery is None:
                    raise EntityNotFoundError("My Photos gallery", locator.group_id)
                manifest = await self._locked_manifest(gallery.id, locator.manifest_identity)
                if manifest is None:
                    raise EntityNotFoundError("My Photos manifest", locator.manifest_identity)
                job = await self._job_for_manifest(
                    gallery.id,
                    manifest.manifest_identity,
                    lock=True,
                )
                if job is not None and job.status not in {"failed", "cancelled"}:
                    raise MyPhotosConflict(
                        "MY_PHOTOS_MANIFEST_CANCELLATION_PENDING",
                        "The gallery index worker has not stopped yet.",
                    )
                face_ids = tuple(face_id for face_id, _reference in provider_faces)
                await self._session.execute(
                    update(MyPhotoFaceOccurrenceModel)
                    .where(
                        MyPhotoFaceOccurrenceModel.id.in_(face_ids),
                        MyPhotoFaceOccurrenceModel.agency_id == locator.agency_id,
                        MyPhotoFaceOccurrenceModel.group_id == locator.group_id,
                    )
                    .values(active=False, deleted_at=datetime.now(tz=UTC))
                )
                remaining = (
                    await self._session.execute(
                        select(MyPhotoFaceOccurrenceModel.id)
                        .join(
                            MyPhotoMediaAssetModel,
                            MyPhotoMediaAssetModel.id == MyPhotoFaceOccurrenceModel.media_asset_id,
                        )
                        .where(
                            MyPhotoMediaAssetModel.gallery_id == gallery.id,
                            MyPhotoMediaAssetModel.published_revision == manifest.target_revision,
                            MyPhotoFaceOccurrenceModel.active.is_(True),
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if remaining is None:
                    # Media deletion is a separate bounded checkpoint. A
                    # repeated cancel invocation resumes it without replaying
                    # completed face deletions.
                    pass
        elif provider_media_references:
            await self._delete_cancelled_media(
                locator=locator,
                references=provider_media_references,
            )
            async with self._session.begin():
                gallery = await self._locked_gallery(locator)
                if gallery is None:
                    raise EntityNotFoundError("My Photos gallery", locator.group_id)
                manifest = await self._locked_manifest(gallery.id, locator.manifest_identity)
                if manifest is None:
                    raise EntityNotFoundError("My Photos manifest", locator.manifest_identity)
                job = await self._job_for_manifest(
                    gallery.id,
                    manifest.manifest_identity,
                    lock=True,
                )
                if job is not None and job.status not in {"failed", "cancelled"}:
                    raise MyPhotosConflict(
                        "MY_PHOTOS_MANIFEST_CANCELLATION_PENDING",
                        "The gallery index worker has not stopped yet.",
                    )
                if media_asset_ids:
                    await self._session.execute(
                        update(MyPhotoMediaAssetModel)
                        .where(MyPhotoMediaAssetModel.id.in_(media_asset_ids))
                        .values(processing_state="removed", availability_state="removed")
                    )
                if media_variant_ids:
                    await self._session.execute(
                        update(MyPhotoAssetVariantModel)
                        .where(MyPhotoAssetVariantModel.id.in_(media_variant_ids))
                        .values(availability_state="removed")
                    )
                remaining_media = await self._has_cancelled_media(
                    gallery=gallery,
                    manifest=manifest,
                )
                if not remaining_media:
                    await self._cleanup_cancelled_manifest(
                        actor=actor,
                        gallery=gallery,
                        manifest=manifest,
                    )
        return await self.manifest_status(
            actor=actor,
            mfa_verified_at=mfa_verified_at,
            locator=locator,
        )

    async def register_batch(
        self,
        *,
        actor: User,
        mfa_verified_at: datetime,
        request: GalleryManifestRequest,
        dispatch: Callable[[uuid.UUID], None],
    ) -> GalleryManifestResult:
        if self._session.in_transaction():
            raise RuntimeError("Manifest registration requires a fresh database session")
        _require_operator(actor, request.agency_id, mfa_verified_at)
        header_fingerprint = request.header_fingerprint(
            provider_configuration_fingerprint=self._provider_configuration_fingerprint()
        )
        batch_fingerprint = request.batch_fingerprint()

        # Reject foreign/deleted/disabled scope before provider I/O. Always
        # close the implicit read transaction, including conflict paths.
        try:
            _group, access = await self._load_scope(request, lock=False)
            access_id = access.id
            existing = await self._existing_batch_result(
                request,
                header_fingerprint=header_fingerprint,
                batch_fingerprint=batch_fingerprint,
            )
        finally:
            await self._session.rollback()
        if existing is not None:
            if request.finalize:
                return await self.finalize_manifest(
                    actor=actor,
                    mfa_verified_at=mfa_verified_at,
                    request=request,
                    dispatch=dispatch,
                    batch_replay=True,
                )
            return existing

        collection_reference, provider_model_version = await self._ensure_collection(request)
        verified_assets = await self._verify_media(request)

        batch_replay = False
        async with self._session.begin():
            _locked_group, locked_access = await self._load_scope(request, lock=True)
            if locked_access.id != access_id:
                raise MyPhotosConflict(
                    "MY_PHOTOS_GALLERY_SCOPE_CHANGED",
                    "The gallery scope changed while media was being verified.",
                )
            gallery = await self._locked_gallery(request)
            if gallery is None:
                if request.target_revision != 1:
                    raise MyPhotosConflict(
                        "MY_PHOTOS_GALLERY_REVISION_CONFLICT",
                        "The first gallery manifest must target revision one.",
                    )
                gallery = MyPhotoGalleryModel(
                    id=uuid.uuid4(),
                    agency_id=request.agency_id,
                    group_id=request.group_id,
                    gc_group_access_id=locked_access.id,
                    feature_enabled=True,
                    status="processing",
                    media_version=0,
                    face_index_version=0,
                    published_revision=0,
                    total_asset_count=0,
                    indexed_asset_count=0,
                    failed_asset_count=0,
                    all_group_photos_enabled=False,
                    provider_collection_reference=None,
                    provider_name=None,
                    index_model_version=None,
                    match_config_version="unconfigured",
                    retention_policy_version="v1",
                    retention_days=None,
                    availability_starts_at=None,
                    availability_ends_at=None,
                )
                self._session.add(gallery)
                await self._session.flush()
            _require_gallery_scope(
                gallery,
                request=request,
                access_id=locked_access.id,
                collection_reference=collection_reference,
            )
            manifest = await self._locked_manifest(gallery.id, request.manifest_identity)
            if manifest is None:
                if gallery.published_revision + 1 != request.target_revision:
                    raise MyPhotosConflict(
                        "MY_PHOTOS_GALLERY_REVISION_CONFLICT",
                        "The gallery manifest revision is stale.",
                    )
                conflicting_manifest = (
                    await self._session.execute(
                        select(MyPhotoGalleryManifestModel.id).where(
                            MyPhotoGalleryManifestModel.gallery_id == gallery.id,
                            MyPhotoGalleryManifestModel.target_revision == request.target_revision,
                            MyPhotoGalleryManifestModel.status != "cancelled",
                        )
                    )
                ).scalar_one_or_none()
                if conflicting_manifest is not None:
                    raise MyPhotosConflict(
                        "MY_PHOTOS_GALLERY_REVISION_CONFLICT",
                        "A different manifest already owns this gallery revision.",
                    )
                manifest = MyPhotoGalleryManifestModel(
                    id=uuid.uuid4(),
                    gallery_id=gallery.id,
                    agency_id=request.agency_id,
                    group_id=request.group_id,
                    manifest_identity=request.manifest_identity,
                    target_revision=request.target_revision,
                    header_fingerprint=header_fingerprint,
                    content_fingerprint=None,
                    total_asset_count=request.total_asset_count,
                    batch_count=request.batch_count,
                    received_asset_count=0,
                    status="receiving",
                    all_group_photos_enabled=request.all_group_photos_enabled,
                    retention_policy_version=request.retention_policy_version,
                    retention_days=request.retention_days,
                    availability_starts_at=request.availability_starts_at,
                    availability_ends_at=request.availability_ends_at,
                    provider_collection_reference=collection_reference,
                    provider_model_version=provider_model_version,
                    match_config_version=self._settings.my_photos.match_config_version,
                    created_by_user_id=actor.id,
                )
                self._session.add(manifest)
                await self._session.flush()
            else:
                _require_manifest_header(manifest, request, header_fingerprint)
                if manifest.cancellation_requested_at is not None:
                    raise MyPhotosConflict(
                        "MY_PHOTOS_MANIFEST_CANCELLATION_PENDING",
                        "This gallery manifest is being cancelled.",
                    )
                if (
                    manifest.provider_collection_reference != collection_reference
                    or manifest.provider_model_version != provider_model_version
                ):
                    raise MyPhotosConflict(
                        "MY_PHOTOS_MANIFEST_PROVIDER_CONFLICT",
                        "The manifest provider version changed between batches.",
                    )
                if manifest.status != "receiving":
                    raise MyPhotosConflict(
                        "MY_PHOTOS_MANIFEST_FINALIZED",
                        "This gallery manifest no longer accepts batches.",
                    )

            batch = await self._locked_batch(manifest.id, request.batch_index)
            if batch is not None:
                if batch.batch_fingerprint != batch_fingerprint:
                    raise MyPhotosConflict(
                        "MY_PHOTOS_MANIFEST_BATCH_CONFLICT",
                        "The manifest batch index was already used for different input.",
                    )
                batch_replay = True
            else:
                await self._persist_batch_assets(
                    request=request,
                    gallery=gallery,
                    manifest=manifest,
                    verified_assets=verified_assets,
                    batch_fingerprint=batch_fingerprint,
                    actor=actor,
                )
            result = await self._result_for_manifest(
                manifest,
                batch_replay=batch_replay,
                manifest_replay=False,
            )

        if request.finalize:
            return await self.finalize_manifest(
                actor=actor,
                mfa_verified_at=mfa_verified_at,
                request=request,
                dispatch=dispatch,
                batch_replay=batch_replay,
            )
        return result

    async def finalize_manifest(
        self,
        *,
        actor: User,
        mfa_verified_at: datetime,
        request: GalleryManifestRequest,
        dispatch: Callable[[uuid.UUID], None],
        batch_replay: bool = False,
    ) -> GalleryManifestResult:
        if self._session.in_transaction():
            raise RuntimeError("Manifest finalization requires a fresh database session")
        _require_operator(actor, request.agency_id, mfa_verified_at)
        header_fingerprint = request.header_fingerprint(
            provider_configuration_fingerprint=self._provider_configuration_fingerprint()
        )
        should_dispatch = False
        async with self._session.begin():
            await self._load_scope(request, lock=True)
            gallery = await self._locked_gallery(request)
            if gallery is None:
                raise EntityNotFoundError("My Photos gallery", request.group_id)
            manifest = await self._locked_manifest(gallery.id, request.manifest_identity)
            if manifest is None:
                raise EntityNotFoundError("My Photos manifest", request.manifest_identity)
            _require_manifest_header(manifest, request, header_fingerprint)
            if manifest.cancellation_requested_at is not None:
                raise MyPhotosConflict(
                    "MY_PHOTOS_MANIFEST_CANCELLATION_PENDING",
                    "This gallery manifest is being cancelled.",
                )

            existing_job = await self._job_for_manifest(gallery.id, manifest.manifest_identity)
            if existing_job is not None:
                if (
                    existing_job.target_revision != manifest.target_revision
                    or existing_job.request_fingerprint != manifest.content_fingerprint
                ):
                    raise MyPhotosConflict(
                        "MY_PHOTOS_MANIFEST_JOB_CONFLICT",
                        "The gallery manifest index job is invalid.",
                    )
                result = _result_with_job(
                    manifest,
                    existing_job,
                    batch_replay=batch_replay,
                    manifest_replay=True,
                )
                should_dispatch = existing_job.status in {"queued", "retrying"}
            else:
                if manifest.status != "receiving":
                    raise MyPhotosConflict(
                        "MY_PHOTOS_MANIFEST_FINALIZED",
                        "The gallery manifest cannot be finalized again.",
                    )
                batches = list(
                    (
                        await self._session.execute(
                            select(MyPhotoGalleryManifestBatchModel)
                            .where(
                                MyPhotoGalleryManifestBatchModel.manifest_id == manifest.id,
                                MyPhotoGalleryManifestBatchModel.agency_id == request.agency_id,
                                MyPhotoGalleryManifestBatchModel.group_id == request.group_id,
                            )
                            .order_by(MyPhotoGalleryManifestBatchModel.batch_index)
                            .with_for_update()
                        )
                    ).scalars()
                )
                if (
                    len(batches) != manifest.batch_count
                    or [batch.batch_index for batch in batches] != list(range(manifest.batch_count))
                    or sum(batch.asset_count for batch in batches) != manifest.total_asset_count
                    or manifest.received_asset_count != manifest.total_asset_count
                ):
                    raise MyPhotosConflict(
                        "MY_PHOTOS_MANIFEST_INCOMPLETE",
                        "Every manifest batch must be registered before finalization.",
                    )
                content_fingerprint = _content_fingerprint(
                    manifest.header_fingerprint,
                    [batch.batch_fingerprint for batch in batches],
                )
                active_job = (
                    await self._session.execute(
                        select(MyPhotoJobModel.id)
                        .where(
                            MyPhotoJobModel.gallery_id == gallery.id,
                            MyPhotoJobModel.job_type == "index_gallery",
                            MyPhotoJobModel.status.in_(("queued", "running", "retrying")),
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if active_job is not None:
                    raise MyPhotosConflict(
                        "MY_PHOTOS_GALLERY_INDEX_BUSY",
                        "Another gallery revision is still indexing.",
                    )
                index_job = MyPhotoJobModel(
                    id=uuid.uuid4(),
                    gallery_id=gallery.id,
                    agency_id=request.agency_id,
                    group_id=request.group_id,
                    job_type="index_gallery",
                    status="queued",
                    idempotency_key=manifest.manifest_identity,
                    request_fingerprint=content_fingerprint,
                    target_revision=manifest.target_revision,
                    max_attempts=self._settings.my_photos.job_max_attempts,
                    total_count=manifest.total_asset_count,
                    correlation_id=uuid.uuid4().hex,
                )
                self._session.add(index_job)
                manifest.content_fingerprint = content_fingerprint
                manifest.status = "indexing"
                manifest.finalized_at = datetime.now(tz=UTC)
                # Keep a previously published revision readable while its
                # successor indexes; an initial gallery has nothing to serve.
                if gallery.published_revision == 0:
                    gallery.status = "indexing"
                await self._session.flush()
                await AuditLogRepository(self._session).record(
                    action="my_photos_gallery_manifest_finalized",
                    entity_type="my_photos_gallery",
                    agency_id=request.agency_id,
                    user_id=actor.id,
                    actor_email=actor.email,
                    entity_id=str(gallery.id),
                    metadata={
                        "group_id": str(request.group_id),
                        "target_revision": manifest.target_revision,
                        "asset_count": manifest.total_asset_count,
                        "batch_count": manifest.batch_count,
                        "retention_policy_version": manifest.retention_policy_version,
                    },
                )
                result = _result_with_job(
                    manifest,
                    index_job,
                    batch_replay=batch_replay,
                    manifest_replay=False,
                )
                should_dispatch = True

        if not should_dispatch or result.index_job_id is None:
            return result
        return _dispatch_result(result, dispatch=dispatch)

    async def _ensure_collection(self, request: GalleryManifestRequest) -> tuple[str, str]:
        if (
            self._providers.provider_name != "aws"
            or not self._providers.face_search.ready
            or not self._providers.media.ready
        ):
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_NOT_CONFIGURED",
                "Production My Photos providers are not configured.",
            )
        collection_reference = self._providers.face_search.collection_reference(
            tenant_scope=str(request.agency_id),
            group_scope=str(request.group_id),
        )
        try:
            async with asyncio.timeout(
                self._settings.my_photos.face_search_provider_timeout_seconds
            ):
                collection = await self._providers.face_search.ensure_collection(
                    FaceCollectionRequest(
                        tenant_scope=str(request.agency_id),
                        group_scope=str(request.group_id),
                        collection_reference=collection_reference,
                    )
                )
        except MyPhotosUnavailable:
            raise
        except Exception as exc:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_UNAVAILABLE",
                "Photo collection verification is temporarily unavailable.",
            ) from exc
        if collection.collection_reference != collection_reference or not _valid_stable(
            collection.provider_model_version, maximum=64
        ):
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_RESULT_INVALID",
                "Photo collection verification returned an invalid result.",
            )
        return collection_reference, collection.provider_model_version

    def _provider_configuration_fingerprint(self) -> str:
        config = self._settings.my_photos
        scope_secret = config.aws_scope_hmac_secret
        scope_secret_fingerprint = (
            hashlib.sha256(scope_secret.get_secret_value().encode("utf-8")).hexdigest()
            if scope_secret is not None
            else None
        )
        return _json_fingerprint(
            {
                "provider_bundle": self._providers.provider_name,
                "liveness_provider": config.liveness_provider,
                "face_search_provider": config.face_search_provider,
                "media_provider": config.media_provider,
                "match_config_version": config.match_config_version,
                "best_match_threshold": config.best_match_threshold,
                "possible_match_threshold": config.possible_match_threshold,
                "maximum_search_results": config.maximum_search_results,
                "aws_region": config.aws_region,
                "aws_media_bucket": config.aws_media_bucket,
                "aws_media_kms_key_id": config.aws_media_kms_key_id,
                "aws_media_key_prefix": config.aws_media_key_prefix,
                "aws_s3_endpoint_url": config.aws_s3_endpoint_url,
                "aws_s3_addressing_style": config.aws_s3_addressing_style,
                "aws_expected_bucket_owner": config.aws_expected_bucket_owner,
                "aws_collection_prefix": config.aws_collection_prefix,
                "aws_scope_hmac_secret_fingerprint": scope_secret_fingerprint,
                "aws_provider_hmac_key_id": config.aws_provider_hmac_key_id,
                "aws_provider_hmac_previous_key_ids": sorted(
                    config.aws_provider_hmac_previous_keys
                ),
                "aws_index_quality_filter": config.aws_index_quality_filter,
                "aws_index_max_faces_per_asset": config.aws_index_max_faces_per_asset,
                "aws_search_quality_filter": config.aws_search_quality_filter,
            }
        )

    async def _status_snapshot(
        self,
        manifest: MyPhotoGalleryManifestModel,
    ) -> GalleryManifestStatus:
        batches = tuple(
            (
                await self._session.execute(
                    select(MyPhotoGalleryManifestBatchModel.batch_index)
                    .where(MyPhotoGalleryManifestBatchModel.manifest_id == manifest.id)
                    .order_by(MyPhotoGalleryManifestBatchModel.batch_index)
                )
            ).scalars()
        )
        job = await self._job_for_manifest(manifest.gallery_id, manifest.manifest_identity)
        cancellation_requested = bool(
            manifest.cancellation_requested_at is not None
            or (job is not None and job.cancellation_requested_at is not None)
        )
        state = (
            "cancellation_pending"
            if cancellation_requested and manifest.status != "cancelled"
            else (job.status if job is not None else manifest.status)
        )
        received = set(batches)
        return GalleryManifestStatus(
            manifest_id=manifest.id,
            gallery_id=manifest.gallery_id,
            index_job_id=job.id if job is not None else None,
            target_revision=manifest.target_revision,
            received_asset_count=manifest.received_asset_count,
            total_asset_count=manifest.total_asset_count,
            batch_count=manifest.batch_count,
            received_batch_indices=batches,
            missing_batch_indices=tuple(
                index for index in range(manifest.batch_count) if index not in received
            ),
            state=state,
            cancellation_requested=cancellation_requested,
            content_fingerprint=manifest.content_fingerprint,
            updated_at=_as_utc(manifest.updated_at),
        )

    async def _audit_cancellation_requested(
        self,
        *,
        actor: User,
        gallery: MyPhotoGalleryModel,
        manifest: MyPhotoGalleryManifestModel,
        job: MyPhotoJobModel,
    ) -> None:
        await AuditLogRepository(self._session).record(
            action="my_photos_gallery_manifest_cancellation_requested",
            entity_type="my_photos_gallery",
            agency_id=manifest.agency_id,
            user_id=actor.id,
            actor_email=actor.email,
            entity_id=str(gallery.id),
            metadata={
                "group_id": str(manifest.group_id),
                "manifest_identity": manifest.manifest_identity,
                "target_revision": manifest.target_revision,
                "index_job_id": str(job.id),
            },
        )

    async def _delete_cancelled_provider_faces(
        self,
        *,
        locator: GalleryManifestLocator,
        collection_reference: str,
        provider_faces: tuple[tuple[uuid.UUID, str], ...],
    ) -> None:
        if self._providers.provider_name != "aws" or not self._providers.face_search.ready:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_NOT_CONFIGURED",
                "Production My Photos providers are not configured.",
            )
        requested = tuple(reference for _face_id, reference in provider_faces)
        try:
            async with asyncio.timeout(
                self._settings.my_photos.face_search_provider_timeout_seconds
            ):
                result = await self._providers.face_search.delete_faces(
                    FaceDeletionRequest(
                        tenant_scope=str(locator.agency_id),
                        group_scope=str(locator.group_id),
                        collection_reference=collection_reference,
                        provider_face_references=requested,
                    )
                )
        except MyPhotosUnavailable:
            raise
        except Exception as exc:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_UNAVAILABLE",
                "Photo index cleanup is temporarily unavailable.",
            ) from exc
        outcomes = result.deleted_face_references + result.not_found_face_references
        if len(outcomes) != len(set(outcomes)) or set(outcomes) != set(requested):
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_RESULT_INVALID",
                "Photo index cleanup returned an invalid result.",
            )

    async def _cancelled_media_batch(
        self,
        *,
        gallery: MyPhotoGalleryModel,
        manifest: MyPhotoGalleryManifestModel,
    ) -> tuple[tuple[str, ...], tuple[uuid.UUID, ...], tuple[uuid.UUID, ...]]:
        limit = self._settings.my_photos.provider_deletion_batch_size
        assets = list(
            (
                await self._session.execute(
                    select(MyPhotoMediaAssetModel)
                    .where(
                        MyPhotoMediaAssetModel.gallery_id == gallery.id,
                        MyPhotoMediaAssetModel.published_revision == manifest.target_revision,
                        MyPhotoMediaAssetModel.availability_state != "removed",
                    )
                    .order_by(MyPhotoMediaAssetModel.id)
                    .limit(limit)
                    .with_for_update()
                )
            ).scalars()
        )
        references: list[str] = []
        asset_ids: list[uuid.UUID] = []
        for asset in assets:
            exact = tuple(
                dict.fromkeys(
                    reference
                    for reference in (asset.archive_reference, asset.storage_reference)
                    if reference is not None
                )
            )
            if len(exact) != 1:
                raise MyPhotosConflict(
                    "MY_PHOTOS_MANIFEST_MEDIA_REFERENCE_INVALID",
                    "Cancelled media does not have one exact versioned reference.",
                )
            if len(references) == limit:
                break
            references.extend(exact)
            asset_ids.append(asset.id)

        remaining = limit - len(references)
        variant_ids: list[uuid.UUID] = []
        if remaining > 0:
            variants = list(
                (
                    await self._session.execute(
                        select(MyPhotoAssetVariantModel)
                        .join(
                            MyPhotoMediaAssetModel,
                            MyPhotoMediaAssetModel.id == MyPhotoAssetVariantModel.media_asset_id,
                        )
                        .where(
                            MyPhotoMediaAssetModel.gallery_id == gallery.id,
                            MyPhotoMediaAssetModel.published_revision == manifest.target_revision,
                            MyPhotoAssetVariantModel.availability_state != "removed",
                        )
                        .order_by(MyPhotoAssetVariantModel.id)
                        .limit(remaining)
                        .with_for_update()
                    )
                ).scalars()
            )
            for variant in variants:
                if variant.storage_reference is None:
                    raise MyPhotosConflict(
                        "MY_PHOTOS_MANIFEST_MEDIA_REFERENCE_INVALID",
                        "Cancelled media is missing its exact versioned reference.",
                    )
                references.append(variant.storage_reference)
                variant_ids.append(variant.id)
        if len(references) != len(set(references)):
            raise MyPhotosConflict(
                "MY_PHOTOS_MANIFEST_MEDIA_REFERENCE_INVALID",
                "Cancelled media contains duplicate versioned references.",
            )
        return tuple(references), tuple(asset_ids), tuple(variant_ids)

    async def _delete_cancelled_media(
        self,
        *,
        locator: GalleryManifestLocator,
        references: tuple[str, ...],
    ) -> None:
        if self._providers.provider_name != "aws" or not self._providers.media.ready:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_NOT_CONFIGURED",
                "Production My Photos providers are not configured.",
            )
        try:
            async with asyncio.timeout(self._settings.my_photos.media_provider_timeout_seconds):
                result = await self._providers.media.delete(
                    MediaDeletionRequest(
                        tenant_scope=str(locator.agency_id),
                        group_scope=str(locator.group_id),
                        media_references=references,
                    )
                )
        except MyPhotosUnavailable:
            raise
        except Exception as exc:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_UNAVAILABLE",
                "Photo storage cleanup is temporarily unavailable.",
            ) from exc
        outcomes = result.deleted_references + result.not_found_references
        if len(outcomes) != len(set(outcomes)) or set(outcomes) != set(references):
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_RESULT_INVALID",
                "Photo storage cleanup returned an invalid result.",
            )

    async def _has_cancelled_media(
        self,
        *,
        gallery: MyPhotoGalleryModel,
        manifest: MyPhotoGalleryManifestModel,
    ) -> bool:
        asset = (
            await self._session.execute(
                select(MyPhotoMediaAssetModel.id)
                .where(
                    MyPhotoMediaAssetModel.gallery_id == gallery.id,
                    MyPhotoMediaAssetModel.published_revision == manifest.target_revision,
                    MyPhotoMediaAssetModel.availability_state != "removed",
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if asset is not None:
            return True
        variant = (
            await self._session.execute(
                select(MyPhotoAssetVariantModel.id)
                .join(
                    MyPhotoMediaAssetModel,
                    MyPhotoMediaAssetModel.id == MyPhotoAssetVariantModel.media_asset_id,
                )
                .where(
                    MyPhotoMediaAssetModel.gallery_id == gallery.id,
                    MyPhotoMediaAssetModel.published_revision == manifest.target_revision,
                    MyPhotoAssetVariantModel.availability_state != "removed",
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        return variant is not None

    async def _cleanup_cancelled_manifest(
        self,
        *,
        actor: User,
        gallery: MyPhotoGalleryModel,
        manifest: MyPhotoGalleryManifestModel,
    ) -> None:
        active_face = (
            await self._session.execute(
                select(MyPhotoFaceOccurrenceModel.id)
                .join(
                    MyPhotoMediaAssetModel,
                    MyPhotoMediaAssetModel.id == MyPhotoFaceOccurrenceModel.media_asset_id,
                )
                .where(
                    MyPhotoMediaAssetModel.gallery_id == gallery.id,
                    MyPhotoMediaAssetModel.published_revision == manifest.target_revision,
                    MyPhotoFaceOccurrenceModel.active.is_(True),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if active_face is not None:
            raise MyPhotosConflict(
                "MY_PHOTOS_MANIFEST_CLEANUP_PENDING",
                "The cancelled provider index still requires bounded cleanup.",
            )
        if await self._has_cancelled_media(gallery=gallery, manifest=manifest):
            raise MyPhotosConflict(
                "MY_PHOTOS_MANIFEST_MEDIA_CLEANUP_PENDING",
                "The cancelled media versions still require bounded cleanup.",
            )
        asset_ids = tuple(
            (
                await self._session.execute(
                    select(MyPhotoMediaAssetModel.id).where(
                        MyPhotoMediaAssetModel.gallery_id == gallery.id,
                        MyPhotoMediaAssetModel.agency_id == manifest.agency_id,
                        MyPhotoMediaAssetModel.group_id == manifest.group_id,
                        MyPhotoMediaAssetModel.published_revision == manifest.target_revision,
                    )
                )
            ).scalars()
        )
        if asset_ids:
            await self._session.execute(
                delete(MyPhotoFaceOccurrenceModel).where(
                    MyPhotoFaceOccurrenceModel.media_asset_id.in_(asset_ids)
                )
            )
            await self._session.execute(
                delete(MyPhotoAssetVariantModel).where(
                    MyPhotoAssetVariantModel.media_asset_id.in_(asset_ids)
                )
            )
            await self._session.execute(
                delete(MyPhotoMediaAssetModel).where(MyPhotoMediaAssetModel.id.in_(asset_ids))
            )
        await self._session.execute(
            delete(MyPhotoGalleryManifestBatchModel).where(
                MyPhotoGalleryManifestBatchModel.manifest_id == manifest.id
            )
        )
        manifest.received_asset_count = 0
        manifest.status = "cancelled"
        if gallery.published_revision == 0:
            gallery.status = "not_uploaded"
        await AuditLogRepository(self._session).record(
            action="my_photos_gallery_manifest_cancelled",
            entity_type="my_photos_gallery",
            agency_id=manifest.agency_id,
            user_id=actor.id,
            actor_email=actor.email,
            entity_id=str(gallery.id),
            metadata={
                "group_id": str(manifest.group_id),
                "manifest_identity": manifest.manifest_identity,
                "target_revision": manifest.target_revision,
                "removed_asset_count": len(asset_ids),
            },
        )

    async def _verify_media(self, request: GalleryManifestRequest) -> tuple[_VerifiedAsset, ...]:
        semaphore = asyncio.Semaphore(_PROVIDER_CONCURRENCY)

        async def call_provider(
            awaitable_factory: Callable[[], Awaitable[_ProviderResultT]],
        ) -> _ProviderResultT:
            async with semaphore:
                async with asyncio.timeout(self._settings.my_photos.media_provider_timeout_seconds):
                    return await awaitable_factory()

        async def verify_asset(asset: GalleryManifestAsset) -> _VerifiedAsset:
            try:
                registered = await call_provider(
                    lambda: self._providers.media.register(
                        MediaRegistrationRequest(
                            tenant_scope=str(request.agency_id),
                            group_scope=str(request.group_id),
                            asset_identity=asset.immutable_asset_key,
                            archive_reference=asset.archive_reference,
                            mime_type=asset.mime_type,
                            byte_size=asset.byte_size,
                            checksum_sha256=asset.checksum_sha256,
                            width=asset.width,
                            height=asset.height,
                            idempotency_identity=(
                                f"manifest:{request.manifest_identity}:"
                                f"{request.batch_index}:{asset.immutable_asset_key}"
                            ),
                        )
                    )
                )
                if (
                    registered.storage_reference is None
                    or registered.source_object_reference != asset.archive_reference
                    or registered.availability_state != "original_available_online"
                ):
                    raise ValueError("Original media registration result is invalid")
                results: dict[str, MediaAvailabilityResult] = {}
                for variant in asset.variants:
                    availability_request = MediaAvailabilityRequest(
                        tenant_scope=str(request.agency_id),
                        group_scope=str(request.group_id),
                        asset_identity=asset.immutable_asset_key,
                        variant=variant.kind,
                    )

                    async def get_availability() -> MediaAvailabilityResult:
                        return await self._providers.media.availability(availability_request)

                    provider_result = await call_provider(get_availability)
                    _require_variant_match(variant, provider_result)
                    results[variant.kind] = provider_result
                return _VerifiedAsset(
                    asset=asset,
                    original_storage_reference=registered.storage_reference,
                    variants=results,
                )
            except MyPhotosUnavailable:
                raise
            except (TypeError, ValueError) as exc:
                raise MyPhotosUnavailable(
                    "MY_PHOTOS_MEDIA_INTEGRITY_CHANGED",
                    "Photo storage integrity check failed.",
                ) from exc
            except Exception as exc:
                raise MyPhotosUnavailable(
                    "MY_PHOTOS_PROVIDER_UNAVAILABLE",
                    "Photo storage verification is temporarily unavailable.",
                ) from exc

        return tuple(await asyncio.gather(*(verify_asset(asset) for asset in request.assets)))

    async def _persist_batch_assets(
        self,
        *,
        request: GalleryManifestRequest,
        gallery: MyPhotoGalleryModel,
        manifest: MyPhotoGalleryManifestModel,
        verified_assets: tuple[_VerifiedAsset, ...],
        batch_fingerprint: str,
        actor: User,
    ) -> None:
        requested_keys = tuple(item.asset.immutable_asset_key for item in verified_assets)
        requested_ranks = tuple(item.asset.sort_rank for item in verified_assets)
        identity_conflict = (
            await self._session.execute(
                select(MyPhotoMediaAssetModel.id)
                .where(
                    MyPhotoMediaAssetModel.gallery_id == gallery.id,
                    MyPhotoMediaAssetModel.immutable_asset_key.in_(requested_keys),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        rank_conflict = (
            await self._session.execute(
                select(MyPhotoMediaAssetModel.id)
                .where(
                    MyPhotoMediaAssetModel.gallery_id == gallery.id,
                    MyPhotoMediaAssetModel.published_revision == manifest.target_revision,
                    MyPhotoMediaAssetModel.sort_rank.in_(requested_ranks),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if identity_conflict is not None or rank_conflict is not None:
            raise MyPhotosConflict(
                "MY_PHOTOS_ASSET_IDENTITY_CONFLICT",
                "A manifest asset identity or sort rank already exists.",
            )

        for verified in verified_assets:
            item = verified.asset
            asset_id = uuid.uuid4()
            self._session.add(
                MyPhotoMediaAssetModel(
                    id=asset_id,
                    gallery_id=gallery.id,
                    agency_id=request.agency_id,
                    group_id=request.group_id,
                    immutable_asset_key=item.immutable_asset_key,
                    media_type="photo",
                    archive_reference=verified.original_storage_reference,
                    storage_reference=verified.original_storage_reference,
                    original_filename=item.original_filename,
                    mime_type=item.mime_type,
                    width=item.width,
                    height=item.height,
                    aspect_ratio=item.width / item.height,
                    byte_size=item.byte_size,
                    checksum_sha256=item.checksum_sha256,
                    captured_at=item.captured_at,
                    orientation=item.orientation,
                    processing_state="registered",
                    availability_state="original_available_online",
                    published_revision=manifest.target_revision,
                    sort_rank=item.sort_rank,
                )
            )
            for declared in item.variants:
                provider = verified.variants[declared.kind]
                self._session.add(
                    MyPhotoAssetVariantModel(
                        id=uuid.uuid4(),
                        media_asset_id=asset_id,
                        agency_id=request.agency_id,
                        group_id=request.group_id,
                        variant_kind=declared.kind,
                        storage_reference=provider.storage_reference,
                        mime_type=cast(str, provider.content_type),
                        width=cast(int, provider.width),
                        height=cast(int, provider.height),
                        byte_size=cast(int, provider.byte_size),
                        checksum_sha256=cast(str, provider.checksum_sha256),
                        availability_state=provider.state,
                        delivery_version=provider.delivery_version,
                        expires_at=manifest.availability_ends_at,
                    )
                )
        self._session.add(
            MyPhotoGalleryManifestBatchModel(
                id=uuid.uuid4(),
                manifest_id=manifest.id,
                agency_id=request.agency_id,
                group_id=request.group_id,
                batch_index=request.batch_index,
                batch_fingerprint=batch_fingerprint,
                asset_count=len(verified_assets),
            )
        )
        manifest.received_asset_count += len(verified_assets)
        await self._session.flush()
        await AuditLogRepository(self._session).record(
            action="my_photos_gallery_manifest_batch_registered",
            entity_type="my_photos_gallery",
            agency_id=request.agency_id,
            user_id=actor.id,
            actor_email=actor.email,
            entity_id=str(gallery.id),
            metadata={
                "group_id": str(request.group_id),
                "target_revision": manifest.target_revision,
                "batch_index": request.batch_index,
                "batch_count": manifest.batch_count,
                "asset_count": len(verified_assets),
            },
        )

    async def _load_scope(
        self,
        request: GalleryManifestRequest | GalleryManifestLocator,
        *,
        lock: bool,
    ) -> tuple[ClientGroupModel, GCGroupAccessModel]:
        statement = (
            select(ClientGroupModel, GCGroupAccessModel)
            .join(
                GCGroupAccessModel,
                and_(
                    GCGroupAccessModel.group_id == ClientGroupModel.id,
                    GCGroupAccessModel.agency_id == ClientGroupModel.agency_id,
                ),
            )
            .where(
                ClientGroupModel.id == request.group_id,
                ClientGroupModel.agency_id == request.agency_id,
                ClientGroupModel.status.in_(("active", "closed")),
                GCGroupAccessModel.is_enabled.is_(True),
                GCGroupAccessModel.passenger_access_enabled.is_(True),
                GCGroupAccessModel.revoked_at.is_(None),
            )
        )
        if lock:
            statement = statement.with_for_update()
        row = (await self._session.execute(statement)).first()
        if row is None:
            raise EntityNotFoundError("My Photos trip", request.group_id)
        return row[0], row[1]

    async def _locked_gallery(
        self,
        request: GalleryManifestRequest | GalleryManifestLocator,
        *,
        lock: bool = True,
    ) -> MyPhotoGalleryModel | None:
        statement = select(MyPhotoGalleryModel).where(
            MyPhotoGalleryModel.agency_id == request.agency_id,
            MyPhotoGalleryModel.group_id == request.group_id,
        )
        if lock:
            statement = statement.with_for_update()
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def _locked_manifest(
        self,
        gallery_id: uuid.UUID,
        manifest_identity: str,
        *,
        lock: bool = True,
    ) -> MyPhotoGalleryManifestModel | None:
        statement = select(MyPhotoGalleryManifestModel).where(
            MyPhotoGalleryManifestModel.gallery_id == gallery_id,
            MyPhotoGalleryManifestModel.manifest_identity == manifest_identity,
        )
        if lock:
            statement = statement.with_for_update()
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def _locked_batch(
        self, manifest_id: uuid.UUID, batch_index: int
    ) -> MyPhotoGalleryManifestBatchModel | None:
        return (
            await self._session.execute(
                select(MyPhotoGalleryManifestBatchModel)
                .where(
                    MyPhotoGalleryManifestBatchModel.manifest_id == manifest_id,
                    MyPhotoGalleryManifestBatchModel.batch_index == batch_index,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()

    async def _existing_batch_result(
        self,
        request: GalleryManifestRequest,
        *,
        header_fingerprint: str,
        batch_fingerprint: str,
    ) -> GalleryManifestResult | None:
        gallery = await self._locked_gallery(request)
        if gallery is None:
            return None
        manifest = await self._locked_manifest(gallery.id, request.manifest_identity)
        if manifest is None:
            return None
        _require_manifest_header(manifest, request, header_fingerprint)
        if manifest.cancellation_requested_at is not None:
            raise MyPhotosConflict(
                "MY_PHOTOS_MANIFEST_CANCELLATION_PENDING",
                "This gallery manifest is being cancelled.",
            )
        batch = await self._locked_batch(manifest.id, request.batch_index)
        if batch is None:
            if manifest.status != "receiving":
                raise MyPhotosConflict(
                    "MY_PHOTOS_MANIFEST_FINALIZED",
                    "This gallery manifest no longer accepts batches.",
                )
            return None
        if batch.batch_fingerprint != batch_fingerprint:
            raise MyPhotosConflict(
                "MY_PHOTOS_MANIFEST_BATCH_CONFLICT",
                "The manifest batch index was already used for different input.",
            )
        return await self._result_for_manifest(
            manifest,
            batch_replay=True,
            manifest_replay=manifest.status != "receiving",
        )

    async def _job_for_manifest(
        self,
        gallery_id: uuid.UUID,
        manifest_identity: str,
        *,
        lock: bool = False,
    ) -> MyPhotoJobModel | None:
        statement = select(MyPhotoJobModel).where(
            MyPhotoJobModel.gallery_id == gallery_id,
            MyPhotoJobModel.job_type == "index_gallery",
            MyPhotoJobModel.idempotency_key == manifest_identity,
        )
        if lock:
            statement = statement.with_for_update()
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def _result_for_manifest(
        self,
        manifest: MyPhotoGalleryManifestModel,
        *,
        batch_replay: bool,
        manifest_replay: bool,
    ) -> GalleryManifestResult:
        job = await self._job_for_manifest(manifest.gallery_id, manifest.manifest_identity)
        if job is not None:
            return _result_with_job(
                manifest,
                job,
                batch_replay=batch_replay,
                manifest_replay=manifest_replay,
            )
        return GalleryManifestResult(
            manifest_id=manifest.id,
            gallery_id=manifest.gallery_id,
            index_job_id=None,
            target_revision=manifest.target_revision,
            received_asset_count=manifest.received_asset_count,
            total_asset_count=manifest.total_asset_count,
            batch_count=manifest.batch_count,
            state="receiving",
            batch_replay=batch_replay,
            manifest_replay=manifest_replay,
            content_fingerprint=manifest.content_fingerprint,
            dispatch_state="not_required",
        )


def _require_operator(actor: User, agency_id: uuid.UUID, mfa_verified_at: datetime) -> None:
    if (
        not actor.is_active
        or actor.credential_state != "active"
        or actor.role not in {UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN}
        or not actor.can_manage_agency(agency_id)
    ):
        raise AuthorizationError()
    now = datetime.now(tz=UTC)
    verified = _as_utc(mfa_verified_at)
    if not actor.mfa_enabled or verified > now or now - verified > _ADMIN_MFA_MAX_AGE:
        raise StepUpRequiredError()


def _require_gallery_scope(
    gallery: MyPhotoGalleryModel,
    *,
    request: GalleryManifestRequest,
    access_id: uuid.UUID,
    collection_reference: str,
) -> None:
    if (
        gallery.gc_group_access_id != access_id
        or gallery.agency_id != request.agency_id
        or gallery.group_id != request.group_id
    ):
        raise MyPhotosConflict(
            "MY_PHOTOS_GALLERY_SCOPE_CHANGED", "The gallery access scope changed."
        )
    if gallery.provider_name not in {None, "aws"} or (
        gallery.provider_collection_reference is not None
        and gallery.provider_collection_reference != collection_reference
    ):
        raise MyPhotosConflict(
            "MY_PHOTOS_GALLERY_PROVIDER_CONFLICT",
            "The gallery provider scope does not match this manifest.",
        )


def _require_manifest_header(
    manifest: MyPhotoGalleryManifestModel,
    request: GalleryManifestRequest,
    header_fingerprint: str,
) -> None:
    if (
        manifest.header_fingerprint != header_fingerprint
        or manifest.target_revision != request.target_revision
        or manifest.total_asset_count != request.total_asset_count
        or manifest.batch_count != request.batch_count
    ):
        raise MyPhotosConflict(
            "MY_PHOTOS_MANIFEST_IDENTITY_CONFLICT",
            "The manifest identity was already used for different input.",
        )


def _require_variant_match(
    manifest: GalleryManifestVariant, provider: MediaAvailabilityResult
) -> None:
    if (
        provider.state not in MEDIA_DELIVERY_READY_STATES
        or provider.storage_reference is None
        or provider.source_object_reference != manifest.storage_reference
        or provider.byte_size != manifest.byte_size
        or provider.checksum_sha256 != manifest.checksum_sha256
        or provider.delivery_version != manifest.delivery_version
        or provider.content_type != manifest.mime_type
        or provider.width != manifest.width
        or provider.height != manifest.height
    ):
        raise ValueError("Variant media registration result is invalid")


def _result_with_job(
    manifest: MyPhotoGalleryManifestModel,
    job: MyPhotoJobModel,
    *,
    batch_replay: bool,
    manifest_replay: bool,
) -> GalleryManifestResult:
    state: ManifestState = cast(ManifestState, job.status)
    return GalleryManifestResult(
        manifest_id=manifest.id,
        gallery_id=manifest.gallery_id,
        index_job_id=job.id,
        target_revision=manifest.target_revision,
        received_asset_count=manifest.received_asset_count,
        total_asset_count=manifest.total_asset_count,
        batch_count=manifest.batch_count,
        state=state,
        batch_replay=batch_replay,
        manifest_replay=manifest_replay,
        content_fingerprint=manifest.content_fingerprint,
        dispatch_state="not_required",
    )


def _dispatch_result(
    result: GalleryManifestResult, *, dispatch: Callable[[uuid.UUID], None]
) -> GalleryManifestResult:
    if result.index_job_id is None:
        return result
    try:
        dispatch(result.index_job_id)
        state: ManifestDispatchState = "dispatched"
    except Exception:
        state = "deferred"
    return GalleryManifestResult(
        manifest_id=result.manifest_id,
        gallery_id=result.gallery_id,
        index_job_id=result.index_job_id,
        target_revision=result.target_revision,
        received_asset_count=result.received_asset_count,
        total_asset_count=result.total_asset_count,
        batch_count=result.batch_count,
        state=result.state,
        batch_replay=result.batch_replay,
        manifest_replay=result.manifest_replay,
        content_fingerprint=result.content_fingerprint,
        dispatch_state=state,
    )


def _content_fingerprint(header_fingerprint: str, batch_fingerprints: list[str]) -> str:
    return _json_fingerprint(
        {"header_fingerprint": header_fingerprint, "batches": batch_fingerprints}
    )


def _json_fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _valid_stable(value: str, *, maximum: int) -> bool:
    return 1 <= len(value) <= maximum and _STABLE_ID.fullmatch(value) is not None


def _as_utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.utcoffset() is not None else value.replace(tzinfo=UTC)


__all__ = [
    "GalleryManifestAsset",
    "GalleryManifestLocator",
    "GalleryManifestRegistrationService",
    "GalleryManifestRequest",
    "GalleryManifestResult",
    "GalleryManifestStatus",
    "GalleryManifestVariant",
]
