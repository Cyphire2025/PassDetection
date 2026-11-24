"""Synthetic provider execution must preserve revision and publication fences."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.my_photos.providers import (
    CanonicalFaceBox,
    FaceIndexBatchResult,
    IndexedFaceOccurrence,
)
from app.core.config.settings import MyPhotosSettings
from app.infrastructure.database.gc_mobile_models import GCGroupAccessModel
from app.infrastructure.database.my_photos_models import (
    MyPhotoFaceOccurrenceModel,
    MyPhotoGalleryModel,
    MyPhotoJobModel,
)
from app.infrastructure.my_photos import operational_runtime
from tests.unit.infrastructure.test_my_photos_gallery_ingestion import (
    _asset,
    _FakeFaceProvider,
    _request,
    _scope,
    _service,
)


@pytest.mark.parametrize("prior_revision", [0, 1])
@pytest.mark.parametrize("change", [None, "cancelled", "expired", "disabled"])
async def test_index_execution_uses_target_revision_and_current_publication_authority(
    db_session,
    monkeypatch,
    prior_revision,
    change,
):
    agency_id, group_id, actor = await _scope(db_session)
    if prior_revision:
        access_id = await db_session.scalar(
            select(GCGroupAccessModel.id).where(
                GCGroupAccessModel.group_id == group_id,
            )
        )
        db_session.add(
            MyPhotoGalleryModel(
                agency_id=agency_id,
                group_id=group_id,
                gc_group_access_id=access_id,
                feature_enabled=True,
                status="ready",
                published_revision=prior_revision,
                face_index_version=prior_revision,
                media_version=prior_revision,
                published_at=datetime.now(UTC),
                provider_collection_reference=(
                    f"collection-{str(agency_id)[:8]}-{str(group_id)[:8]}"
                ),
            )
        )
        await db_session.commit()
    assets = (_asset(0),)
    service = _service(db_session, assets)
    registered = await service.register_batch(
        actor=actor,
        mfa_verified_at=datetime.now(UTC),
        request=_request(
            agency_id=agency_id,
            group_id=group_id,
            manifest_identity="synthetic-operational-index",
            target_revision=prior_revision + 1,
            assets=assets,
            total_asset_count=1,
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

    class Provider(_FakeFaceProvider):
        async def index_faces(self, request):
            if change is not None:
                async with sessions() as session, session.begin():
                    if change == "disabled":
                        await session.execute(
                            update(MyPhotoGalleryModel)
                            .where(
                                MyPhotoGalleryModel.id == registered.gallery_id,
                            )
                            .values(feature_enabled=False)
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
                                MyPhotoJobModel.id == registered.index_job_id,
                            )
                            .values(**values)
                        )
            return FaceIndexBatchResult(
                occurrences=tuple(
                    IndexedFaceOccurrence(
                        asset_identity=asset.asset_identity,
                        provider_face_reference=f"synthetic-face-{asset.asset_identity}",
                        bounding_box=CanonicalFaceBox(0.1, 0.1, 0.3, 0.3),
                        quality_score=90,
                        provider_model_version="7.0",
                        idempotency_identity=asset.idempotency_identity,
                    )
                    for asset in request.assets
                ),
                failures=(),
            )

    result = await operational_runtime.execute_operational_job(
        registered.index_job_id,
        settings=SimpleNamespace(my_photos=MyPhotosSettings(_env_file=None)),
        providers=SimpleNamespace(provider_name="aws", face_search=Provider()),
        lease_owner="synthetic-index-worker",
    )
    async with sessions() as session:
        gallery = await session.get(MyPhotoGalleryModel, registered.gallery_id)
        occurrences = list(
            (
                await session.scalars(
                    select(MyPhotoFaceOccurrenceModel).where(
                        MyPhotoFaceOccurrenceModel.group_id == group_id,
                    )
                )
            ).all()
        )
        if change is not None:
            assert result.state in {"lease_lost", "failed", "cancelled"}
            assert gallery.published_revision == prior_revision
            assert occurrences == []
        else:
            assert result.state == "succeeded"
            assert gallery.published_revision == prior_revision + 1
            assert len(occurrences) == 1
            assert occurrences[0].index_version == gallery.face_index_version == prior_revision + 1
