"""Late media preparation cannot publish through stale gallery or lease authority."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.my_photos.providers import MediaAvailabilityResult
from app.core.config.settings import MyPhotosSettings
from app.infrastructure.database.my_photos_models import (
    MyPhotoAssetVariantModel,
    MyPhotoGalleryModel,
    MyPhotoJobModel,
    MyPhotoMediaAssetModel,
)
from app.infrastructure.my_photos import operational_runtime
from tests.unit.infrastructure.test_my_photos_gallery_ingestion import (
    _asset,
    _request,
    _scope,
    _service,
)


@pytest.mark.parametrize("change", [None, "cancelled", "expired", "disabled", "removed"])
async def test_media_execution_rechecks_current_authority_after_provider(
    db_session, monkeypatch, change
):
    agency_id, group_id, actor = await _scope(db_session)
    assets = (_asset(0),)
    registered = await _service(db_session, assets).register_batch(
        actor=actor,
        mfa_verified_at=datetime.now(UTC),
        request=_request(
            agency_id=agency_id,
            group_id=group_id,
            manifest_identity="synthetic-media-job",
            target_revision=1,
            assets=assets,
            total_asset_count=1,
            batch_index=0,
        ),
        dispatch=lambda _job_id: None,
    )
    asset_id = await db_session.scalar(
        select(MyPhotoMediaAssetModel.id).where(
            MyPhotoMediaAssetModel.gallery_id == registered.gallery_id,
        )
    )
    job_id = uuid.uuid4()
    db_session.add(
        MyPhotoJobModel(
            id=job_id,
            gallery_id=registered.gallery_id,
            agency_id=agency_id,
            group_id=group_id,
            media_asset_id=asset_id,
            job_type="generate_variants",
            status="queued",
            idempotency_key="synthetic-media-generation",
            target_revision=None,
            total_count=1,
            correlation_id=uuid.uuid4().hex,
        )
    )
    await db_session.commit()
    provider_called = False
    lock_statements = []

    class RecordingSession(AsyncSession):
        async def execute(self, statement, *args, **kwargs):
            if provider_called and getattr(statement, "_for_update_arg", None) is not None:
                model = statement.column_descriptions[0]["entity"]
                lock_statements.append(
                    (
                        model.__tablename__,
                        str(statement.compile(dialect=postgresql.dialect())),
                    )
                )
            return await super().execute(statement, *args, **kwargs)

    sessions = async_sessionmaker(
        db_session.bind,
        class_=RecordingSession,
        expire_on_commit=False,
    )
    monkeypatch.setattr(operational_runtime, "AsyncSessionFactory", sessions)
    mutated = False

    class Media:
        async def prepare(self, request):
            nonlocal mutated, provider_called
            provider_called = True
            if change is not None and not mutated:
                mutated = True
                async with sessions() as session, session.begin():
                    if change == "disabled":
                        await session.execute(
                            update(MyPhotoGalleryModel)
                            .where(
                                MyPhotoGalleryModel.id == registered.gallery_id,
                            )
                            .values(feature_enabled=False)
                        )
                    elif change == "removed":
                        await session.execute(
                            update(MyPhotoMediaAssetModel)
                            .where(
                                MyPhotoMediaAssetModel.id == asset_id,
                            )
                            .values(processing_state="removed", availability_state="removed")
                        )
                    else:
                        values = (
                            {"cancellation_requested_at": datetime.now(UTC)}
                            if change == "cancelled"
                            else {"lease_expires_at": datetime.now(UTC) - timedelta(seconds=1)}
                        )
                        await session.execute(
                            update(MyPhotoJobModel)
                            .where(
                                MyPhotoJobModel.id == job_id,
                            )
                            .values(**values)
                        )
            return MediaAvailabilityResult(
                state="delivery_available",
                byte_size=1234,
                checksum_sha256="a" * 64,
                delivery_version=2,
                storage_reference=f"synthetic-new-{request.variant}",
                content_type="image/jpeg",
                width=640,
                height=480,
            )

    result = await operational_runtime.execute_operational_job(
        job_id,
        settings=SimpleNamespace(my_photos=MyPhotosSettings(_env_file=None)),
        providers=SimpleNamespace(media=Media()),
        lease_owner="synthetic-media-worker",
    )
    async with sessions() as session:
        variants = tuple(
            await session.scalars(
                select(MyPhotoAssetVariantModel).where(
                    MyPhotoAssetVariantModel.media_asset_id == asset_id,
                    MyPhotoAssetVariantModel.delivery_version == 2,
                )
            )
        )
        current_asset = await session.get(MyPhotoMediaAssetModel, asset_id)
        if change is not None:
            assert result.state in {"lease_lost", "failed", "cancelled"}
            assert variants == ()
            if change == "removed":
                assert current_asset.processing_state == "removed"
        else:
            assert result.state == "succeeded"
            assert len(variants) == 3
            assert [name for name, _sql in lock_statements[:3]] == [
                "my_photo_galleries",
                "my_photo_jobs",
                "my_photo_media_assets",
            ]
            assert all("FOR UPDATE" in sql for _name, sql in lock_statements[:3])
