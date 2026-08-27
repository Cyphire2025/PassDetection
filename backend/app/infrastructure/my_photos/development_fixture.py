"""Explicit, resumable local bootstrap for the synthetic 5,000-asset gallery."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.my_photos.errors import MyPhotosConflict
from app.infrastructure.database.gc_mobile_models import GCGroupAccessModel
from app.infrastructure.database.my_photos_models import (
    MyPhotoAssetVariantModel,
    MyPhotoFaceOccurrenceModel,
    MyPhotoGalleryModel,
    MyPhotoJobModel,
    MyPhotoMediaAssetModel,
)
from app.infrastructure.my_photos.synthetic_media import synthetic_media_checksum

if TYPE_CHECKING:
    from app.application.security.mobile_access_policy import AuthorizedMobileTrip
    from app.core.config.settings import Settings

_FIXTURE_NAMESPACE = uuid.UUID("a8ac7b66-987f-4c5f-92e6-3eddfcd37cb7")
_FIXTURE_TIME = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)
_BATCH_SIZE = 250


def synthetic_asset_id(group_id: uuid.UUID, index: int) -> uuid.UUID:
    return uuid.uuid5(_FIXTURE_NAMESPACE, f"{group_id}:asset:{index}")


def synthetic_face_id(group_id: uuid.UUID, index: int, occurrence: int) -> uuid.UUID:
    return uuid.uuid5(_FIXTURE_NAMESPACE, f"{group_id}:face:{index}:{occurrence}")


async def bootstrap_development_gallery(
    session: AsyncSession,
    *,
    trip: AuthorizedMobileTrip,
    settings: Settings,
    maximum_batches: int | None = None,
) -> MyPhotoGalleryModel:
    """Seed in durable batches; never called by a passenger request.

    The access-row lock serializes the initial claim. A durable job row and
    checkpoint make a process interruption resumable without duplicate assets
    or face occurrences. Commits are intentional because this is an explicit
    development bootstrap command, not an application request service.
    """

    config = settings.my_photos
    if (
        settings.app_env != "development"
        or not config.development_fixtures_enabled
        or {
            config.liveness_provider,
            config.face_search_provider,
            config.media_provider,
        }
        != {"development"}
    ):
        raise RuntimeError("Synthetic My Photos bootstrap is disabled")
    if maximum_batches is not None and maximum_batches < 1:
        raise ValueError("maximum_batches must be positive")

    await session.execute(
        select(GCGroupAccessModel.id)
        .where(
            GCGroupAccessModel.id == trip.access.id,
            GCGroupAccessModel.agency_id == trip.access.agency_id,
            GCGroupAccessModel.group_id == trip.group.id,
        )
        .with_for_update()
    )
    gallery = (
        await session.execute(
            select(MyPhotoGalleryModel).where(
                MyPhotoGalleryModel.agency_id == trip.access.agency_id,
                MyPhotoGalleryModel.group_id == trip.group.id,
            )
        )
    ).scalar_one_or_none()
    if gallery is not None and gallery.status == "ready":
        return gallery
    if gallery is None:
        gallery = MyPhotoGalleryModel(
            agency_id=trip.access.agency_id,
            group_id=trip.group.id,
            gc_group_access_id=trip.access.id,
            feature_enabled=True,
            status="processing",
            media_version=1,
            face_index_version=1,
            published_revision=0,
            total_asset_count=config.development_fixture_asset_count,
            indexed_asset_count=0,
            failed_asset_count=0,
            all_group_photos_enabled=True,
            provider_collection_reference=f"dev-collection:{trip.group.id.hex}",
            provider_name="development",
            index_model_version="development-metadata-v1",
            match_config_version=config.match_config_version,
            retention_policy_version="development-v1",
            retention_days=30,
            created_at=_FIXTURE_TIME,
            updated_at=_FIXTURE_TIME,
        )
        session.add(gallery)
        await session.flush()
        session.add(
            MyPhotoJobModel(
                gallery_id=gallery.id,
                agency_id=gallery.agency_id,
                group_id=gallery.group_id,
                job_type="index_gallery",
                status="queued",
                idempotency_key="development-fixture-v1",
                target_revision=1,
                max_attempts=config.job_max_attempts,
                total_count=config.development_fixture_asset_count,
                correlation_id=uuid.uuid5(_FIXTURE_NAMESPACE, f"{trip.group.id}:bootstrap").hex,
                created_at=_FIXTURE_TIME,
                updated_at=_FIXTURE_TIME,
            )
        )
        await session.commit()

    job = (
        await session.execute(
            select(MyPhotoJobModel)
            .where(
                MyPhotoJobModel.gallery_id == gallery.id,
                MyPhotoJobModel.job_type == "index_gallery",
                MyPhotoJobModel.idempotency_key == "development-fixture-v1",
            )
            .with_for_update()
        )
    ).scalar_one()
    claim_time = datetime.now(tz=UTC)
    if (
        job.status == "running"
        and job.lease_expires_at is not None
        and _as_utc(job.lease_expires_at) > claim_time
    ):
        await session.rollback()
        raise MyPhotosConflict(
            "MY_PHOTOS_FIXTURE_BUSY", "The development gallery bootstrap is already running."
        )
    if job.status == "succeeded":
        await session.rollback()
        return gallery
    job.status = "running"
    job.attempt_count += 1
    job.lease_owner = f"bootstrap:{uuid.uuid4().hex}"
    job.heartbeat_at = claim_time
    job.lease_expires_at = claim_time + timedelta(seconds=config.job_lease_seconds)
    job.started_at = job.started_at or claim_time
    await session.commit()

    start_index = int(job.checkpoint_cursor or "0")
    completed_batches = 0
    for start in range(start_index, config.development_fixture_asset_count, _BATCH_SIZE):
        stop = min(start + _BATCH_SIZE, config.development_fixture_asset_count)
        asset_rows, variant_rows, face_rows = _fixture_batch(
            trip=trip,
            gallery=gallery,
            start=start,
            stop=stop,
        )
        await session.execute(insert(MyPhotoMediaAssetModel), asset_rows)
        await session.execute(insert(MyPhotoAssetVariantModel), variant_rows)
        await session.execute(insert(MyPhotoFaceOccurrenceModel), face_rows)
        locked_job = (
            await session.execute(
                select(MyPhotoJobModel).where(MyPhotoJobModel.id == job.id).with_for_update()
            )
        ).scalar_one()
        locked_gallery = (
            await session.execute(
                select(MyPhotoGalleryModel)
                .where(MyPhotoGalleryModel.id == gallery.id)
                .with_for_update()
            )
        ).scalar_one()
        heartbeat = datetime.now(tz=UTC)
        locked_job.checkpoint_cursor = str(stop)
        locked_job.processed_count = stop
        locked_job.succeeded_count = stop
        locked_job.heartbeat_at = heartbeat
        locked_job.lease_expires_at = heartbeat + timedelta(seconds=config.job_lease_seconds)
        locked_gallery.indexed_asset_count = stop
        locked_gallery.updated_at = _FIXTURE_TIME
        await session.commit()
        completed_batches += 1
        if maximum_batches is not None and completed_batches >= maximum_batches:
            locked_job.status = "retrying"
            locked_job.lease_owner = None
            locked_job.lease_expires_at = None
            await session.commit()
            return locked_gallery

    gallery = (
        await session.execute(
            select(MyPhotoGalleryModel)
            .where(MyPhotoGalleryModel.id == gallery.id)
            .with_for_update()
        )
    ).scalar_one()
    job = (
        await session.execute(
            select(MyPhotoJobModel).where(MyPhotoJobModel.id == job.id).with_for_update()
        )
    ).scalar_one()
    gallery.status = "ready"
    gallery.published_revision = 1
    gallery.published_at = _FIXTURE_TIME
    gallery.indexed_asset_count = config.development_fixture_asset_count
    gallery.updated_at = _FIXTURE_TIME
    job.status = "succeeded"
    job.processed_count = job.total_count
    job.succeeded_count = job.total_count
    job.checkpoint_cursor = str(job.total_count)
    job.completed_at = datetime.now(tz=UTC)
    job.lease_owner = None
    job.lease_expires_at = None
    await session.commit()
    return gallery


def _fixture_batch(
    *,
    trip: AuthorizedMobileTrip,
    gallery: MyPhotoGalleryModel,
    start: int,
    stop: int,
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    asset_rows: list[dict[str, object]] = []
    variant_rows: list[dict[str, object]] = []
    face_rows: list[dict[str, object]] = []
    for index in range(start, stop):
        asset_id = synthetic_asset_id(trip.group.id, index)
        asset_key = f"dev-asset-{index:05d}"
        if index % 3 == 0:
            width, height = 6_000, 4_000
        elif index % 3 == 1:
            width, height = 4_000, 6_000
        else:
            width, height = 4_500, 4_500
        availability = "original_available_online"
        storage_reference: str | None = f"development/{trip.group.id}/{asset_key}"
        if index != 0 and index % 17 == 0:
            availability = "archived_offline"
            storage_reference = None
        elif index != 0 and index % 29 == 0:
            availability = "preparing_delivery"
            storage_reference = None
        original_size, checksum = synthetic_media_checksum(asset_key, "original")
        asset_rows.append(
            {
                "id": asset_id,
                "gallery_id": gallery.id,
                "agency_id": trip.access.agency_id,
                "group_id": trip.group.id,
                "immutable_asset_key": asset_key,
                "media_type": "photo",
                "archive_reference": f"development-archive/{trip.group.id}/{asset_key}",
                "storage_reference": storage_reference,
                "original_filename": f"synthetic-event-photo-{index + 1:05d}.jpg",
                "mime_type": "image/jpeg",
                "width": width,
                "height": height,
                "aspect_ratio": width / height,
                "byte_size": original_size,
                "checksum_sha256": checksum,
                "captured_at": _FIXTURE_TIME - timedelta(days=2) + timedelta(seconds=index * 11),
                "orientation": 1,
                "processing_state": "indexed",
                "availability_state": availability,
                "published_revision": 1,
                "sort_rank": index,
                "created_at": _FIXTURE_TIME,
                "updated_at": _FIXTURE_TIME,
            }
        )
        optimized_size, optimized_checksum = synthetic_media_checksum(asset_key, "optimized")
        variant_rows.append(
            {
                "id": uuid.uuid5(_FIXTURE_NAMESPACE, f"{trip.group.id}:variant:{index}:optimized"),
                "media_asset_id": asset_id,
                "agency_id": trip.access.agency_id,
                "group_id": trip.group.id,
                "variant_kind": "optimized",
                "storage_reference": (f"development/{trip.group.id}/{asset_key}/optimized"),
                "mime_type": "image/png",
                "width": min(width, 1_920),
                "height": max(1, round(height * min(width, 1_920) / width)),
                "byte_size": optimized_size,
                "checksum_sha256": optimized_checksum,
                "availability_state": "delivery_available",
                "delivery_version": 1,
                "created_at": _FIXTURE_TIME,
                "updated_at": _FIXTURE_TIME,
            }
        )
        occurrence_count = 2 if index % 5 == 0 else 1
        for occurrence in range(occurrence_count):
            suffix = "primary" if occurrence == 0 else "secondary"
            face_rows.append(
                {
                    "id": synthetic_face_id(trip.group.id, index, occurrence),
                    "media_asset_id": asset_id,
                    "agency_id": trip.access.agency_id,
                    "group_id": trip.group.id,
                    "provider_name": "development",
                    "provider_face_reference": f"dev-face-{index:05d}-{suffix}",
                    "idempotency_identity": f"fixture-v1:{index}:{occurrence}",
                    "bounding_left": 0.10 + (occurrence * 0.35),
                    "bounding_top": 0.15,
                    "bounding_width": 0.20,
                    "bounding_height": 0.30,
                    "quality_score": 95.0 - (index % 20),
                    "quality_class": "synthetic",
                    "provider_model_version": "development-metadata-v1",
                    "index_version": 1,
                    "active": True,
                    "created_at": _FIXTURE_TIME,
                }
            )
    return asset_rows, variant_rows, face_rows


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
