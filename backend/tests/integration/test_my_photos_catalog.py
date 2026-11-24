"""Real FK-backed catalog pages, cursor boundaries and feedback ownership."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.application.my_photos.errors import MyPhotosConflict, MyPhotosInvalidCursor
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.infrastructure.database.models import AuditLogModel
from app.infrastructure.database.my_photos_models import (
    MyPhotoEnrollmentModel,
    MyPhotoFaceOccurrenceModel,
    MyPhotoGalleryModel,
    MyPhotoMatchModel,
    MyPhotoMediaAssetModel,
    MyPhotoSearchRunModel,
)
from app.infrastructure.my_photos.service import MyPhotosService
from app.presentation.api.v1.schemas.my_photos_schemas import MyPhotosFeedbackRequest
from tests.integration.test_my_photos_provider_claim_freshness import (
    photo_database as photo_database,
)


async def seed_catalog(env):
    async with env.sessions() as session, session.begin():
        gallery = await session.get(MyPhotoGalleryModel, env.gallery_id)
        gallery.all_group_photos_enabled = True
        enrollment = await session.scalar(select(MyPhotoEnrollmentModel))
        enrollment.status = "enrolled"
        enrollment.provider_name = "development"
        enrollment.provider_reference_handle = "synthetic-private-reference"
        enrollment.reference_version = 1
        enrollment.enrolled_at = datetime.now(UTC)
        assets = [
            MyPhotoMediaAssetModel(
                id=uuid.uuid4(),
                gallery_id=gallery.id,
                agency_id=gallery.agency_id,
                group_id=gallery.group_id,
                immutable_asset_key=f"synthetic-{index}",
                original_filename=f"synthetic-{index}.jpg",
                mime_type="image/jpeg",
                width=100,
                height=80,
                aspect_ratio=1.25,
                byte_size=100,
                checksum_sha256="a" * 64,
                published_revision=2 if index == 3 else 1,
                sort_rank=10,
                processing_state="removed" if index == 2 else "indexed",
                availability_state="removed" if index == 2 else "original_available_online",
                storage_reference=f"synthetic/private/{index}",
            )
            for index in range(4)
        ]
        session.add_all(assets)
        await session.flush()
        faces = [
            MyPhotoFaceOccurrenceModel(
                id=uuid.uuid4(),
                media_asset_id=asset.id,
                agency_id=gallery.agency_id,
                group_id=gallery.group_id,
                provider_name="development",
                provider_face_reference=f"synthetic-face-{index}",
                idempotency_identity=f"synthetic-index-{index}",
                bounding_left=0.1,
                bounding_top=0.1,
                bounding_width=0.2,
                bounding_height=0.2,
                provider_model_version="synthetic-v1",
                index_version=1,
            )
            for index, asset in enumerate(assets[:3])
        ]
        session.add_all(faces)
        search = MyPhotoSearchRunModel(
            id=uuid.uuid4(),
            enrollment_id=enrollment.id,
            passenger_identity_id=enrollment.passenger_identity_id,
            gallery_id=gallery.id,
            agency_id=gallery.agency_id,
            group_id=gallery.group_id,
            gallery_revision=1,
            face_index_version=1,
            enrollment_version=1,
            idempotency_key="synthetic-complete-search",
            correlation_id="synthetic-catalog-correlation",
            status="complete",
            processed_face_count=3,
            total_face_count=3,
            matched_asset_count=3,
            best_match_count=3,
        )
        session.add(search)
        await session.flush()
        session.add_all(
            [
                MyPhotoMatchModel(
                    id=uuid.uuid4(),
                    search_run_id=search.id,
                    passenger_identity_id=enrollment.passenger_identity_id,
                    media_asset_id=asset.id,
                    face_occurrence_id=face.id,
                    agency_id=gallery.agency_id,
                    group_id=gallery.group_id,
                    gallery_revision=1,
                    similarity=95,
                    display_tier="best",
                    match_config_version="synthetic-v1",
                    sort_rank=10,
                )
                for asset, face in zip(assets[:3], faces, strict=True)
            ]
        )
        return [asset.id for asset in assets[:2]]


def service_for(session, env):
    return MyPhotosService(
        session,
        settings=env.settings,
        providers=SimpleNamespace(
            provider_name="disabled",
            liveness=SimpleNamespace(ready=False, client_flow="unavailable"),
            face_search=SimpleNamespace(ready=False),
        ),
    )


@pytest.mark.parametrize("match_filter", ["best", "all"])
async def test_catalog_pages_are_revision_bound_and_exclude_removed_or_future_assets(
    photo_database, match_filter
):
    env = photo_database
    visible = await seed_catalog(env)
    async with env.sessions() as session:
        service = service_for(session, env)
        first = await service.photo_page(
            claims=env.passenger.claims,
            trip=env.passenger.trip,
            match_filter=match_filter,
            cursor=None,
            limit=1,
        )
        second = await service.photo_page(
            claims=env.passenger.claims,
            trip=env.passenger.trip,
            match_filter=match_filter,
            cursor=first.next_cursor,
            limit=1,
        )
        assert first.total_count == second.total_count == 2
        assert first.snapshot_revision == second.snapshot_revision == 1
        assert first.next_cursor is not None and second.next_cursor is None
        assert {first.items[0].asset_id, second.items[0].asset_id} == set(visible)
        assert first.items[0].asset_id != second.items[0].asset_id
        assert "synthetic/private" not in first.model_dump_json()
        with pytest.raises(MyPhotosInvalidCursor):
            await service.photo_page(
                claims=env.passenger.claims,
                trip=env.passenger.trip,
                match_filter="possible" if match_filter == "best" else "best",
                cursor=first.next_cursor,
                limit=1,
            )
        with pytest.raises(MyPhotosInvalidCursor):
            await service.photo_page(
                claims=env.passenger.claims,
                trip=env.passenger.trip,
                match_filter=match_filter,
                cursor="invalid-cursor-signature",
                limit=1,
            )


async def test_feedback_is_owned_and_idempotent_and_all_photos_can_be_disabled(photo_database):
    env = photo_database
    visible = await seed_catalog(env)
    async with env.sessions() as session:
        service = service_for(session, env)
        request = MyPhotosFeedbackRequest(
            feedback="this_is_me", idempotency_key="synthetic-feedback"
        )
        for _ in range(2):
            result = await service.record_feedback(
                claims=env.passenger.claims,
                trip=env.passenger.trip,
                asset_id=visible[0],
                request=request,
            )
            assert result.feedback == "this_is_me"
            await session.commit()
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditLogModel)
                .where(AuditLogModel.action == "my_photos_match_feedback")
            )
            == 1
        )
        with pytest.raises(MyPhotosConflict):
            await service.record_feedback(
                claims=env.passenger.claims,
                trip=env.passenger.trip,
                asset_id=visible[0],
                request=request.model_copy(update={"feedback": "not_me"}),
            )
        with pytest.raises(EntityNotFoundError):
            await service.record_feedback(
                claims=env.other_passenger.claims,
                trip=env.other_passenger.trip,
                asset_id=visible[0],
                request=request,
            )
        gallery = await session.get(MyPhotoGalleryModel, env.gallery_id)
        gallery.all_group_photos_enabled = False
        await session.commit()
        with pytest.raises(MyPhotosConflict):
            await service.photo_page(
                claims=env.passenger.claims,
                trip=env.passenger.trip,
                match_filter="all",
                cursor=None,
                limit=1,
            )
