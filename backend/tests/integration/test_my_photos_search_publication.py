"""Actual match publication coalesces faces and carries feedback across search versions."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy import select

from app.application.my_photos.providers import FaceSearchResult, ProviderFaceMatch
from app.infrastructure.database.my_photos_models import (
    MyPhotoEnrollmentModel,
    MyPhotoFaceOccurrenceModel,
    MyPhotoJobModel,
    MyPhotoMatchModel,
    MyPhotoMediaAssetModel,
    MyPhotoSearchRunModel,
)
from app.infrastructure.my_photos import worker_runtime
from tests.integration.test_my_photos_provider_claim_freshness import (
    photo_database as photo_database,
)
from tests.integration.test_my_photos_search_failure_authority import _queued_search


async def test_search_publication_preserves_strongest_asset_match_and_prior_feedback(
    photo_database, monkeypatch
):
    env = photo_database
    prior_id, prior_job_id = await _queued_search(env, idempotency_key="synthetic-prior-search")
    search_id, job_id = await _queued_search(env)
    monkeypatch.setattr(worker_runtime, "AsyncSessionFactory", env.sessions)
    async with env.sessions() as session, session.begin():
        enrollment = await session.scalar(select(MyPhotoEnrollmentModel))
        prior = await session.get(MyPhotoSearchRunModel, prior_id)
        prior.status = "complete"
        prior.processed_face_count = prior.matched_asset_count = prior.best_match_count = 1
        prior.completed_at = datetime.now(UTC)
        prior_job = await session.get(MyPhotoJobModel, prior_job_id)
        prior_job.status = "succeeded"
        prior_job.processed_count = prior_job.succeeded_count = 1
        prior_job.completed_at = datetime.now(UTC)
        search = await session.get(MyPhotoSearchRunModel, search_id)
        search.total_face_count = 5
        job = await session.get(MyPhotoJobModel, job_id)
        job.total_count = 5
        assets = []
        for index in range(3):
            asset = MyPhotoMediaAssetModel(
                id=uuid.uuid4(),
                gallery_id=env.gallery_id,
                agency_id=enrollment.agency_id,
                group_id=enrollment.group_id,
                immutable_asset_key=f"synthetic-match-asset-{index}",
                media_type="photo",
                archive_reference=f"synthetic-original-{index}",
                original_filename=f"synthetic-{index}.jpg",
                mime_type="image/jpeg",
                width=640,
                height=480,
                aspect_ratio=640 / 480,
                byte_size=1234,
                checksum_sha256="a" * 64,
                processing_state="indexed",
                availability_state="original_available_online",
                published_revision=1,
                sort_rank=index,
            )
            session.add(asset)
            assets.append(asset)
        await session.flush()
        faces = []
        for reference, index, active in [
            ("face-best", 0, True),
            ("face-same-asset", 0, True),
            ("face-possible", 1, True),
            ("face-below-threshold", 2, True),
            ("face-inactive", 2, False),
        ]:
            face = MyPhotoFaceOccurrenceModel(
                id=uuid.uuid4(),
                media_asset_id=assets[index].id,
                agency_id=enrollment.agency_id,
                group_id=enrollment.group_id,
                provider_name="synthetic-provider",
                provider_face_reference=reference,
                idempotency_identity="synthetic-" + reference,
                bounding_left=0.1,
                bounding_top=0.1,
                bounding_width=0.3,
                bounding_height=0.3,
                provider_model_version="synthetic-v1",
                index_version=1,
                active=active,
            )
            session.add(face)
            faces.append(face)
        await session.flush()
        session.add(
            MyPhotoMatchModel(
                search_run_id=prior_id,
                passenger_identity_id=enrollment.passenger_identity_id,
                media_asset_id=assets[0].id,
                face_occurrence_id=faces[0].id,
                agency_id=enrollment.agency_id,
                group_id=enrollment.group_id,
                gallery_revision=1,
                similarity=93,
                display_tier="best",
                match_config_version="synthetic-prior",
                feedback="not_me",
                feedback_idempotency_key="synthetic-prior-feedback",
                active=True,
                sort_rank=0,
            )
        )
        asset_ids = [asset.id for asset in assets]

    class Provider:
        async def search(self, _request):
            return FaceSearchResult(
                matches=tuple(
                    ProviderFaceMatch(reference, similarity)
                    for reference, similarity in [
                        ("face-same-asset", 90),
                        ("face-best", 93),
                        ("face-best", 97),
                        ("face-possible", 85),
                        ("face-below-threshold", 50),
                        ("face-inactive", 99),
                    ]
                ),
                provider_model_version="synthetic-v1",
            )

    result = await worker_runtime.execute_search_job(
        search_id,
        settings=env.settings,
        providers=SimpleNamespace(face_search=Provider()),
        lease_owner="synthetic-match-worker",
    )
    assert result.state == "succeeded"
    async with env.sessions() as session:
        active = list(
            await session.scalars(
                select(MyPhotoMatchModel)
                .where(MyPhotoMatchModel.active.is_(True))
                .order_by(MyPhotoMatchModel.sort_rank)
            )
        )
        assert [match.media_asset_id for match in active] == asset_ids[:2]
        assert [match.similarity for match in active] == [97, 85]
        assert [match.display_tier for match in active] == ["best", "possible"]
        assert [match.feedback for match in active] == ["not_me", "none"]
        assert all(match.feedback_idempotency_key is None for match in active)
        previous = await session.scalar(
            select(MyPhotoMatchModel).where(MyPhotoMatchModel.search_run_id == prior_id)
        )
        assert not previous.active and previous.superseded_at is not None
        search = await session.get(MyPhotoSearchRunModel, search_id)
        assert search.matched_asset_count == 2
        assert search.best_match_count == search.possible_match_count == 1
