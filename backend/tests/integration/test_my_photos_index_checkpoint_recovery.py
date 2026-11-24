"""Recover persisted index checkpoints without publishing incomplete work or duplicate faces."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.infrastructure.database.my_photos_models import (
    MyPhotoFaceOccurrenceModel,
    MyPhotoGalleryModel,
    MyPhotoJobModel,
    MyPhotoMediaAssetModel,
)
from app.infrastructure.my_photos import operational_runtime
from tests.integration.my_photos_operational_fixtures import operational_index_scope
from tests.integration.test_my_photos_index_lifecycle import _result


@pytest.mark.parametrize("checkpoint", ["incomplete", "no_success", "complete"])
async def test_end_of_input_checkpoint_requires_complete_successful_counters(
    db_session, monkeypatch, checkpoint
):
    scope = await operational_index_scope(db_session, monkeypatch)
    # A durable checkpoint can be retained across worker/release recovery. No
    # provider request should start after the recorded cursor reaches input EOF.
    async with scope.sessions() as session, session.begin():
        job = await session.get(MyPhotoJobModel, scope.job_id)
        job.checkpoint_cursor = "999"
        if checkpoint != "incomplete":
            job.processed_count = 1
            job.succeeded_count = int(checkpoint == "complete")
            job.failed_count = int(checkpoint == "no_success")
            asset = await session.scalar(
                select(MyPhotoMediaAssetModel).where(
                    MyPhotoMediaAssetModel.gallery_id == scope.gallery_id
                )
            )
            asset.processing_state = "indexed" if checkpoint == "complete" else "failed"

    class FaceSearch:
        async def index_faces(self, _request):
            raise AssertionError("EOF recovery must not repeat a provider batch")

    result = await operational_runtime.execute_operational_job(
        scope.job_id,
        settings=scope.settings,
        providers=SimpleNamespace(provider_name="aws", face_search=FaceSearch()),
        lease_owner="synthetic-recovery-worker",
    )
    async with scope.sessions() as session:
        gallery = await session.get(MyPhotoGalleryModel, scope.gallery_id)
        job = await session.get(MyPhotoJobModel, scope.job_id)
        if checkpoint == "complete":
            assert result.state == job.status == "succeeded"
            assert gallery.published_revision == 1
        else:
            assert result.state == job.status == "failed"
            assert gallery.published_revision == 0
            assert job.stable_error_code == (
                "INDEX_ASSET_COUNT_MISMATCH"
                if checkpoint == "incomplete"
                else "INDEX_COMPLETENESS_FAILED"
            )


async def test_replayed_face_reference_does_not_create_a_duplicate_occurrence(
    db_session, monkeypatch
):
    scope = await operational_index_scope(db_session, monkeypatch)

    class FaceSearch:
        async def index_faces(self, request):
            result = _result(request)
            occurrence = result.occurrences[0]
            async with scope.sessions() as session, session.begin():
                asset = await session.scalar(
                    select(MyPhotoMediaAssetModel).where(
                        MyPhotoMediaAssetModel.gallery_id == scope.gallery_id
                    )
                )
                session.add(
                    MyPhotoFaceOccurrenceModel(
                        media_asset_id=asset.id,
                        agency_id=asset.agency_id,
                        group_id=asset.group_id,
                        provider_name="synthetic-provider",
                        provider_face_reference=occurrence.provider_face_reference,
                        idempotency_identity=occurrence.idempotency_identity,
                        bounding_left=0.1,
                        bounding_top=0.1,
                        bounding_width=0.3,
                        bounding_height=0.3,
                        provider_model_version="7.0",
                        index_version=1,
                        active=True,
                    )
                )
            return result

    result = await operational_runtime.execute_operational_job(
        scope.job_id,
        settings=scope.settings,
        providers=SimpleNamespace(provider_name="aws", face_search=FaceSearch()),
        lease_owner="synthetic-index-worker",
    )
    assert result.state == "succeeded"
    async with scope.sessions() as session:
        assert len(tuple(await session.scalars(select(MyPhotoFaceOccurrenceModel)))) == 1
