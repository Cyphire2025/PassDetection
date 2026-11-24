"""Synthetic persisted photo operations, shared by worker boundary regressions."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config.settings import MyPhotosSettings
from app.infrastructure.database.my_photos_models import MyPhotoJobModel, MyPhotoMediaAssetModel
from app.infrastructure.my_photos import operational_runtime
from tests.unit.infrastructure.test_my_photos_gallery_ingestion import (
    _asset,
    _request,
    _scope,
    _service,
)


async def operational_media_scope(db_session, monkeypatch, *, job_type="prepare_media"):
    agency_id, group_id, actor = await _scope(db_session)
    assets = (_asset(0),)
    registered = await _service(db_session, assets).register_batch(
        actor=actor,
        mfa_verified_at=datetime.now(UTC),
        request=_request(
            agency_id=agency_id,
            group_id=group_id,
            manifest_identity="synthetic-worker-lifecycle",
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
            job_type=job_type,
            status="queued",
            idempotency_key="synthetic-worker-lifecycle",
            checkpoint_cursor="preview" if job_type == "prepare_media" else None,
            total_count=1,
            correlation_id=uuid.uuid4().hex,
        )
    )
    await db_session.commit()
    sessions = async_sessionmaker(db_session.bind, expire_on_commit=False)
    monkeypatch.setattr(operational_runtime, "AsyncSessionFactory", sessions)
    return SimpleNamespace(
        job_id=job_id,
        gallery_id=registered.gallery_id,
        asset_id=asset_id,
        sessions=sessions,
        settings=SimpleNamespace(my_photos=MyPhotosSettings(_env_file=None)),
    )


async def operational_index_scope(db_session, monkeypatch, *, asset_count=1, batch_size=50):
    agency_id, group_id, actor = await _scope(db_session)
    assets = tuple(_asset(index) for index in range(asset_count))
    registered = await _service(db_session, assets).register_batch(
        actor=actor,
        mfa_verified_at=datetime.now(UTC),
        request=_request(
            agency_id=agency_id,
            group_id=group_id,
            manifest_identity="synthetic-index-lifecycle",
            target_revision=1,
            assets=assets,
            total_asset_count=asset_count,
            batch_index=0,
            finalize=True,
        ).model_copy(
            update={
                "availability_starts_at": datetime.now(UTC) - timedelta(days=1),
                "availability_ends_at": datetime.now(UTC) + timedelta(days=30),
            }
        ),
        dispatch=lambda _job_id: None,
    )
    sessions = async_sessionmaker(db_session.bind, expire_on_commit=False)
    monkeypatch.setattr(operational_runtime, "AsyncSessionFactory", sessions)
    return SimpleNamespace(
        job_id=registered.index_job_id,
        gallery_id=registered.gallery_id,
        sessions=sessions,
        settings=SimpleNamespace(
            my_photos=MyPhotosSettings(_env_file=None, job_batch_size=batch_size)
        ),
    )
