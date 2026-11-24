"""Persisted index retries, partial batches and invalid output retain publication gates."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select, update

from app.application.my_photos.errors import MyPhotosUnavailable
from app.application.my_photos.providers import (
    CanonicalFaceBox,
    FaceIndexBatchResult,
    FaceIndexFailure,
    IndexedFaceOccurrence,
)
from app.infrastructure.database.my_photos_models import (
    MyPhotoAssetVariantModel,
    MyPhotoFaceOccurrenceModel,
    MyPhotoGalleryModel,
    MyPhotoJobModel,
    MyPhotoMediaAssetModel,
)
from app.infrastructure.my_photos import operational_runtime
from tests.integration.my_photos_operational_fixtures import operational_index_scope


def _result(request):
    return FaceIndexBatchResult(
        tuple(
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
        (),
    )


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        ("unavailable", "retrying"),
        ("unexpected", "retrying"),
        ("invalid", "failed"),
        ("no_faces", "failed"),
        ("stale_revision", "failed"),
        ("changed_asset", "failed"),
        ("missing_analysis", "retrying"),
        ("exhausted", "failed"),
    ],
)
async def test_index_failure_never_publishes_an_incomplete_revision(
    db_session, monkeypatch, failure, expected
):
    scope = await operational_index_scope(db_session, monkeypatch)
    if failure in {"missing_analysis", "exhausted"}:
        async with scope.sessions() as session, session.begin():
            if failure == "missing_analysis":
                await session.execute(
                    delete(MyPhotoAssetVariantModel).where(
                        MyPhotoAssetVariantModel.variant_kind == "analysis"
                    )
                )
            else:
                job = await session.get(MyPhotoJobModel, scope.job_id)
                job.max_attempts = 1
    calls = []

    class FaceSearch:
        async def index_faces(self, request):
            calls.append(request)
            if failure in {"unavailable", "exhausted"}:
                raise MyPhotosUnavailable("SYNTHETIC_UNAVAILABLE", "Synthetic failure.")
            if failure == "unexpected":
                raise RuntimeError("Synthetic private diagnostic must not be persisted")
            if failure == "invalid":
                raise ValueError("Synthetic malformed response")
            if failure == "no_faces":
                return FaceIndexBatchResult(
                    (), (FaceIndexFailure(request.assets[0].asset_identity, "NO_FACE"),)
                )
            if failure in {"stale_revision", "changed_asset"}:
                async with scope.sessions() as session, session.begin():
                    if failure == "stale_revision":
                        await session.execute(
                            update(MyPhotoGalleryModel)
                            .where(MyPhotoGalleryModel.id == scope.gallery_id)
                            .values(published_revision=1, face_index_version=1, media_version=1)
                        )
                    else:
                        await session.execute(
                            update(MyPhotoMediaAssetModel)
                            .where(MyPhotoMediaAssetModel.gallery_id == scope.gallery_id)
                            .values(published_revision=2)
                        )
            return _result(request)

    result = await operational_runtime.execute_operational_job(
        scope.job_id,
        settings=scope.settings,
        providers=SimpleNamespace(provider_name="aws", face_search=FaceSearch()),
        lease_owner="synthetic-index-worker",
    )
    assert result.state == expected
    assert len(calls) == (0 if failure == "missing_analysis" else 1)
    async with scope.sessions() as session:
        gallery = await session.get(MyPhotoGalleryModel, scope.gallery_id)
        job = await session.get(MyPhotoJobModel, scope.job_id)
        assert gallery.published_revision == (1 if failure == "stale_revision" else 0)
        assert job.status == expected
        assert "private diagnostic" not in (job.error_detail or "")
        if failure != "no_faces":
            assert not tuple(await session.scalars(select(MyPhotoFaceOccurrenceModel)))


async def test_partial_index_batches_resume_without_duplicate_publication(db_session, monkeypatch):
    scope = await operational_index_scope(db_session, monkeypatch, asset_count=11, batch_size=10)
    calls = []

    class FaceSearch:
        async def index_faces(self, request):
            calls.append(request)
            return _result(request)

    async def execute():
        return await operational_runtime.execute_operational_job(
            scope.job_id,
            settings=scope.settings,
            providers=SimpleNamespace(provider_name="aws", face_search=FaceSearch()),
            lease_owner="synthetic-index-worker",
        )

    first = await execute()
    assert first.state == "retrying" and first.retry_after_seconds == 1
    async with scope.sessions() as session, session.begin():
        gallery = await session.get(MyPhotoGalleryModel, scope.gallery_id)
        job = await session.get(MyPhotoJobModel, scope.job_id)
        assert gallery.published_revision == 0
        assert job.processed_count == job.succeeded_count == 10
        job.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    second = await execute()
    assert second.state == "succeeded"
    assert (await execute()).state == "noop"
    assert [request.assets[0].asset_identity for request in calls] == ["asset-00000", "asset-00010"]
    async with scope.sessions() as session:
        job = await session.get(MyPhotoJobModel, scope.job_id)
        gallery = await session.get(MyPhotoGalleryModel, scope.gallery_id)
        assert gallery.published_revision == gallery.face_index_version == 1
        assert job.processed_count == job.succeeded_count == 11 and job.failed_count == 0
        assert len(tuple(await session.scalars(select(MyPhotoFaceOccurrenceModel)))) == 11
