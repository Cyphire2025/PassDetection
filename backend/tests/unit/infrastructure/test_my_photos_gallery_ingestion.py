from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.my_photos.errors import MyPhotosConflict
from app.application.my_photos.limits import MAX_MY_PHOTOS_MEDIA_BYTES
from app.application.my_photos.providers import (
    FaceCollectionResult,
    FaceDeletionResult,
    MediaAvailabilityResult,
    MediaDeletionResult,
    MediaRegistrationResult,
)
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.gc_mobile_models import GCGroupAccessModel
from app.infrastructure.database.models import AgencyModel, ClientGroupModel, UserModel
from app.infrastructure.database.my_photos_models import (
    MyPhotoAssetVariantModel,
    MyPhotoGalleryManifestBatchModel,
    MyPhotoGalleryModel,
    MyPhotoJobModel,
    MyPhotoMediaAssetModel,
)
from app.infrastructure.my_photos.gallery_ingestion import (
    GalleryManifestAsset,
    GalleryManifestLocator,
    GalleryManifestRegistrationService,
    GalleryManifestRequest,
    GalleryManifestVariant,
)

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


class _FakeFaceProvider:
    ready = True

    def collection_reference(self, *, tenant_scope: str, group_scope: str) -> str:
        return f"collection-{tenant_scope[:8]}-{group_scope[:8]}"

    async def ensure_collection(self, request):  # type: ignore[no-untyped-def]
        return FaceCollectionResult(request.collection_reference, "7.0")

    async def delete_faces(self, request):  # type: ignore[no-untyped-def]
        return FaceDeletionResult(request.provider_face_references, ())


class _FakeMediaProvider:
    ready = True

    def __init__(self, assets: dict[str, GalleryManifestAsset]) -> None:
        self._assets = assets
        self.deleted_references: list[tuple[str, ...]] = []

    async def register(self, request):  # type: ignore[no-untyped-def]
        return MediaRegistrationResult(
            storage_reference=f"versioned:{request.archive_reference}",
            availability_state="original_available_online",
            source_object_reference=request.archive_reference,
        )

    async def availability(self, request):  # type: ignore[no-untyped-def]
        declared = next(
            variant
            for variant in self._assets[request.asset_identity].variants
            if variant.kind == request.variant
        )
        return MediaAvailabilityResult(
            state="delivery_available",
            byte_size=declared.byte_size,
            checksum_sha256=declared.checksum_sha256,
            delivery_version=declared.delivery_version,
            storage_reference=f"versioned:{declared.storage_reference}",
            content_type=declared.mime_type,
            width=declared.width,
            height=declared.height,
            source_object_reference=declared.storage_reference,
        )

    async def delete(self, request):  # type: ignore[no-untyped-def]
        self.deleted_references.append(request.media_references)
        return MediaDeletionResult(request.media_references, ())


def _settings(match_config_version: str = "aws-calibrated-v1") -> SimpleNamespace:
    return SimpleNamespace(
        my_photos=SimpleNamespace(
            provider_deletion_batch_size=25,
            face_search_provider_timeout_seconds=20,
            media_provider_timeout_seconds=20,
            job_max_attempts=5,
            liveness_provider="aws_rekognition",
            face_search_provider="aws_rekognition",
            media_provider="s3",
            match_config_version=match_config_version,
            best_match_threshold=92.0,
            possible_match_threshold=80.0,
            maximum_search_results=5_000,
            aws_region="ap-south-1",
            aws_media_bucket="passdetection-my-photos-media",
            aws_media_kms_key_id=(
                "arn:aws:kms:ap-south-1:123456789012:key/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
            ),
            aws_media_key_prefix="my-photos/media",
            aws_s3_endpoint_url=None,
            aws_s3_addressing_style="auto",
            aws_expected_bucket_owner="123456789012",
            aws_collection_prefix="pd-my-photos",
            aws_scope_hmac_secret=SecretStr("s" * 48),
            aws_provider_hmac_key_id="reference-v2",
            aws_provider_hmac_previous_keys={},
            aws_index_quality_filter="AUTO",
            aws_index_max_faces_per_asset=100,
            aws_search_quality_filter="AUTO",
        )
    )


def _asset(index: int) -> GalleryManifestAsset:
    identity = f"asset-{index:05d}"
    variants = tuple(
        GalleryManifestVariant(
            kind=kind,
            storage_reference=f"my-photos/media/{identity}/{kind}",
            mime_type="image/jpeg",
            width=640,
            height=480,
            byte_size=10_000 + index,
            checksum_sha256=f"{index + offset:064x}",
            delivery_version=1,
        )
        for offset, kind in enumerate(("thumbnail", "preview", "analysis"), start=1)
    )
    return GalleryManifestAsset(
        immutable_asset_key=identity,
        archive_reference=f"my-photos/media/{identity}/original",
        original_filename=f"{identity}.jpg",
        mime_type="image/jpeg",
        width=1920,
        height=1080,
        byte_size=100_000 + index,
        checksum_sha256=f"{index + 100:064x}",
        captured_at=NOW,
        sort_rank=index,
        variants=variants,
    )


def test_manifest_original_and_variant_sizes_share_mobile_delivery_ceiling() -> None:
    asset_values = _asset(0).model_dump()
    asset_values["byte_size"] = MAX_MY_PHOTOS_MEDIA_BYTES
    assert GalleryManifestAsset.model_validate(asset_values).byte_size == MAX_MY_PHOTOS_MEDIA_BYTES
    asset_values["byte_size"] = MAX_MY_PHOTOS_MEDIA_BYTES + 1
    with pytest.raises(ValidationError):
        GalleryManifestAsset.model_validate(asset_values)

    variant_values = _asset(0).variants[0].model_dump()
    variant_values["byte_size"] = MAX_MY_PHOTOS_MEDIA_BYTES
    assert (
        GalleryManifestVariant.model_validate(variant_values).byte_size == MAX_MY_PHOTOS_MEDIA_BYTES
    )
    variant_values["byte_size"] = MAX_MY_PHOTOS_MEDIA_BYTES + 1
    with pytest.raises(ValidationError):
        GalleryManifestVariant.model_validate(variant_values)


def _request(
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    manifest_identity: str,
    target_revision: int,
    assets: tuple[GalleryManifestAsset, ...],
    total_asset_count: int,
    batch_index: int,
    finalize: bool = False,
) -> GalleryManifestRequest:
    return GalleryManifestRequest(
        agency_id=agency_id,
        group_id=group_id,
        manifest_identity=manifest_identity,
        target_revision=target_revision,
        total_asset_count=total_asset_count,
        batch_count=(total_asset_count + 99) // 100,
        batch_index=batch_index,
        finalize=finalize,
        retention_policy_version="trip-window-v1",
        retention_days=30,
        availability_starts_at=NOW - timedelta(days=1),
        availability_ends_at=NOW + timedelta(days=30),
        assets=assets,
    )


async def _scope(db_session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID, User]:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    db_session.add_all(
        [
            AgencyModel(
                id=agency_id,
                name="Gallery Test Agency",
                email=f"agency-{agency_id}@example.test",
            ),
            UserModel(
                id=actor_id,
                email=f"operator-{actor_id}@example.test",
                hashed_password="not-used",
                full_name="Gallery Operator",
                role="agency_admin",
                agency_id=agency_id,
            ),
            ClientGroupModel(
                id=group_id,
                name="Gallery Test Group",
                token=uuid.uuid4().hex,
                agency_id=agency_id,
                status="active",
            ),
            GCGroupAccessModel(
                id=uuid.uuid4(),
                agency_id=agency_id,
                group_id=group_id,
                is_enabled=True,
                passenger_access_enabled=True,
            ),
        ]
    )
    await db_session.commit()
    actor = User(
        id=actor_id,
        email=f"operator-{actor_id}@example.test",
        hashed_password="not-used",
        full_name="Gallery Operator",
        role=UserRole.AGENCY_ADMIN,
        agency_id=agency_id,
        mfa_enabled=True,
    )
    return agency_id, group_id, actor


def _service(
    db_session: AsyncSession,
    assets: tuple[GalleryManifestAsset, ...],
    *,
    match_config_version: str = "aws-calibrated-v1",
) -> GalleryManifestRegistrationService:
    providers = SimpleNamespace(
        provider_name="aws",
        face_search=_FakeFaceProvider(),
        media=_FakeMediaProvider({asset.immutable_asset_key: asset for asset in assets}),
    )
    return GalleryManifestRegistrationService(
        db_session,
        settings=_settings(match_config_version),  # type: ignore[arg-type]
        providers=providers,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_two_batch_manifest_is_idempotent_and_publishes_no_partial_revision(
    db_session: AsyncSession,
) -> None:
    agency_id, group_id, actor = await _scope(db_session)
    assets = tuple(_asset(index) for index in range(101))
    batch_zero = _request(
        agency_id=agency_id,
        group_id=group_id,
        manifest_identity="gallery-101-assets",
        target_revision=1,
        assets=assets[:100],
        total_asset_count=101,
        batch_index=0,
    )
    batch_one = _request(
        agency_id=agency_id,
        group_id=group_id,
        manifest_identity="gallery-101-assets",
        target_revision=1,
        assets=assets[100:],
        total_asset_count=101,
        batch_index=1,
    )
    service = _service(db_session, assets)

    first = await service.register_batch(
        actor=actor,
        mfa_verified_at=datetime.now(tz=UTC),
        request=batch_one,
        dispatch=lambda _job_id: None,
    )
    assert first.received_asset_count == 1
    assert first.index_job_id is None
    with pytest.raises(MyPhotosConflict) as incomplete:
        await service.finalize_manifest(
            actor=actor,
            mfa_verified_at=datetime.now(tz=UTC),
            request=batch_one,
            dispatch=lambda _job_id: None,
        )
    assert incomplete.value.code == "MY_PHOTOS_MANIFEST_INCOMPLETE"

    replay = await service.register_batch(
        actor=actor,
        mfa_verified_at=datetime.now(tz=UTC),
        request=batch_one,
        dispatch=lambda _job_id: None,
    )
    assert replay.batch_replay is True
    conflicting_asset = assets[100].model_copy(update={"checksum_sha256": "f" * 64})
    with pytest.raises(MyPhotosConflict) as conflict:
        await service.register_batch(
            actor=actor,
            mfa_verified_at=datetime.now(tz=UTC),
            request=batch_one.model_copy(update={"assets": (conflicting_asset,)}),
            dispatch=lambda _job_id: None,
        )
    assert conflict.value.code == "MY_PHOTOS_MANIFEST_BATCH_CONFLICT"

    await service.register_batch(
        actor=actor,
        mfa_verified_at=datetime.now(tz=UTC),
        request=batch_zero,
        dispatch=lambda _job_id: None,
    )
    gallery = (
        await db_session.execute(
            select(MyPhotoGalleryModel).where(MyPhotoGalleryModel.group_id == group_id)
        )
    ).scalar_one()
    assert gallery.published_revision == 0
    assert gallery.provider_name is None
    assert gallery.match_config_version == "unconfigured"
    await db_session.rollback()

    finalized = await service.finalize_manifest(
        actor=actor,
        mfa_verified_at=datetime.now(tz=UTC),
        request=batch_zero,
        dispatch=lambda _job_id: None,
    )
    assert finalized.state == "queued"
    assert finalized.index_job_id is not None
    assert (
        await db_session.scalar(
            select(func.count(MyPhotoJobModel.id)).where(
                MyPhotoJobModel.gallery_id == gallery.id,
                MyPhotoJobModel.job_type == "index_gallery",
            )
        )
        == 1
    )
    await db_session.refresh(gallery)
    assert gallery.published_revision == 0
    assert gallery.provider_name is None
    assert gallery.match_config_version == "unconfigured"


@pytest.mark.asyncio
async def test_manifest_rejects_midstream_match_configuration_change(
    db_session: AsyncSession,
) -> None:
    agency_id, group_id, actor = await _scope(db_session)
    assets = tuple(_asset(index) for index in range(101))
    batch_one = _request(
        agency_id=agency_id,
        group_id=group_id,
        manifest_identity="config-fenced-gallery",
        target_revision=1,
        assets=assets[100:],
        total_asset_count=101,
        batch_index=1,
    )
    await _service(db_session, assets).register_batch(
        actor=actor,
        mfa_verified_at=datetime.now(tz=UTC),
        request=batch_one,
        dispatch=lambda _job_id: None,
    )
    changed = _service(
        db_session,
        assets,
        match_config_version="aws-calibrated-v2",
    )
    with pytest.raises(MyPhotosConflict) as captured:
        await changed.register_batch(
            actor=actor,
            mfa_verified_at=datetime.now(tz=UTC),
            request=_request(
                agency_id=agency_id,
                group_id=group_id,
                manifest_identity="config-fenced-gallery",
                target_revision=1,
                assets=assets[:100],
                total_asset_count=101,
                batch_index=0,
            ),
            dispatch=lambda _job_id: None,
        )
    assert captured.value.code == "MY_PHOTOS_MANIFEST_IDENTITY_CONFLICT"


@pytest.mark.asyncio
async def test_partial_manifest_cancel_is_idempotent_and_releases_target_revision(
    db_session: AsyncSession,
) -> None:
    agency_id, group_id, actor = await _scope(db_session)
    asset = _asset(0)
    request = _request(
        agency_id=agency_id,
        group_id=group_id,
        manifest_identity="abandoned-gallery-v1",
        target_revision=1,
        assets=(asset,),
        total_asset_count=1,
        batch_index=0,
    )
    service = _service(db_session, (asset,))
    await service.register_batch(
        actor=actor,
        mfa_verified_at=datetime.now(tz=UTC),
        request=request,
        dispatch=lambda _job_id: None,
    )
    locator = GalleryManifestLocator(
        agency_id=agency_id,
        group_id=group_id,
        manifest_identity=request.manifest_identity,
    )
    before = await service.manifest_status(
        actor=actor,
        mfa_verified_at=datetime.now(tz=UTC),
        locator=locator,
    )
    assert before.received_batch_indices == (0,)
    assert before.missing_batch_indices == ()

    cancelled = await service.cancel_manifest(
        actor=actor,
        mfa_verified_at=datetime.now(tz=UTC),
        locator=locator,
    )
    assert cancelled.state == "cancelled"
    assert cancelled.received_asset_count == 0
    assert cancelled.received_batch_indices == ()
    again = await service.cancel_manifest(
        actor=actor,
        mfa_verified_at=datetime.now(tz=UTC),
        locator=locator,
    )
    assert again.state == "cancelled"
    assert await db_session.scalar(select(func.count(MyPhotoMediaAssetModel.id))) == 0
    assert await db_session.scalar(select(func.count(MyPhotoAssetVariantModel.id))) == 0
    assert await db_session.scalar(select(func.count(MyPhotoGalleryManifestBatchModel.id))) == 0
    media_provider = service._providers.media  # type: ignore[attr-defined]
    assert isinstance(media_provider, _FakeMediaProvider)
    assert len(media_provider.deleted_references) == 1
    assert len(media_provider.deleted_references[0]) == 4
    assert all(
        reference.startswith("versioned:") for reference in media_provider.deleted_references[0]
    )
    await db_session.rollback()

    replacement = request.model_copy(update={"manifest_identity": "replacement-gallery-v1"})
    accepted = await service.register_batch(
        actor=actor,
        mfa_verified_at=datetime.now(tz=UTC),
        request=replacement,
        dispatch=lambda _job_id: None,
    )
    assert accepted.target_revision == 1
    assert accepted.state == "receiving"


@pytest.mark.asyncio
async def test_running_manifest_cancel_waits_for_worker_then_resumes_cleanup(
    db_session: AsyncSession,
) -> None:
    agency_id, group_id, actor = await _scope(db_session)
    asset = _asset(0)
    request = _request(
        agency_id=agency_id,
        group_id=group_id,
        manifest_identity="running-gallery-v1",
        target_revision=1,
        assets=(asset,),
        total_asset_count=1,
        batch_index=0,
        finalize=True,
    )
    service = _service(db_session, (asset,))
    result = await service.register_batch(
        actor=actor,
        mfa_verified_at=datetime.now(tz=UTC),
        request=request,
        dispatch=lambda _job_id: None,
    )
    assert result.index_job_id is not None
    job = await db_session.get(MyPhotoJobModel, result.index_job_id)
    assert job is not None
    job.status = "running"
    job.lease_owner = "worker-one"
    job.lease_expires_at = datetime.now(tz=UTC) + timedelta(minutes=2)
    await db_session.commit()
    locator = GalleryManifestLocator(
        agency_id=agency_id,
        group_id=group_id,
        manifest_identity=request.manifest_identity,
    )

    pending = await service.cancel_manifest(
        actor=actor,
        mfa_verified_at=datetime.now(tz=UTC),
        locator=locator,
    )
    assert pending.state == "cancellation_pending"
    assert pending.cancellation_requested is True
    assert await db_session.scalar(select(func.count(MyPhotoMediaAssetModel.id))) == 1

    await db_session.refresh(job)
    job.status = "cancelled"
    job.completed_at = datetime.now(tz=UTC)
    job.lease_owner = None
    job.lease_expires_at = None
    await db_session.commit()
    completed = await service.cancel_manifest(
        actor=actor,
        mfa_verified_at=datetime.now(tz=UTC),
        locator=locator,
    )
    assert completed.state == "cancelled"
    assert await db_session.scalar(select(func.count(MyPhotoMediaAssetModel.id))) == 0
