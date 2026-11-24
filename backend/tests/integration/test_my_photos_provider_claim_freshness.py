"""Provider awaits cannot retain stale ORM claim or gallery authority."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import event, func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.application.my_photos.errors import MyPhotosConflict, MyPhotosUnavailable
from app.application.my_photos.providers import LivenessResult, LivenessSessionHandle
from app.core.config.settings import MyPhotosSettings
from app.infrastructure.database.models import Base
from app.infrastructure.database.my_photos_models import (
    MyPhotoEnrollmentModel,
    MyPhotoGalleryModel,
    MyPhotoJobModel,
    MyPhotoLivenessSessionModel,
    MyPhotoSearchRunModel,
)
from app.infrastructure.my_photos.service import MyPhotosService
from app.presentation.api.v1.schemas.my_photos_schemas import (
    MyPhotosLivenessCompleteRequest,
    MyPhotosLivenessStartRequest,
)
from tests.service_integration.test_my_photos_postgresql_contracts import _seed_fixture


@pytest.fixture
async def photo_database(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'photo-claims.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    # Pure fixture seeding only; this does not invoke that module's PostgreSQL
    # URL, provider bootstrap or skipped live-service qualification tests.
    fixture = await _seed_fixture(sessions)
    passenger = fixture.passenger_a
    policy = MyPhotosSettings(_env_file=None)
    settings = SimpleNamespace(
        app_env="development", my_photos=policy, app_secret_key="synthetic-photo-cursor-secret"
    )
    async with sessions() as session, session.begin():
        gallery = MyPhotoGalleryModel(
            id=uuid.uuid4(),
            agency_id=fixture.group.agency_id,
            group_id=fixture.group.id,
            gc_group_access_id=fixture.access.id,
            feature_enabled=True,
            status="ready",
            published_revision=1,
            media_version=1,
            face_index_version=1,
            published_at=datetime.now(UTC),
            provider_collection_reference="synthetic-collection",
        )
        enrollment = MyPhotoEnrollmentModel(
            id=uuid.uuid4(),
            passenger_identity_id=passenger.identity.id,
            passenger_submission_id=passenger.identity.passenger_submission_id,
            gc_group_access_id=fixture.access.id,
            agency_id=fixture.group.agency_id,
            group_id=fixture.group.id,
            consent_version=policy.consent_version,
            consented_at=datetime.now(UTC),
            consent_idempotency_key="synthetic-consent",
            status="ready",
        )
        session.add_all([gallery, enrollment])
    try:
        yield SimpleNamespace(
            sessions=sessions,
            passenger=passenger,
            settings=settings,
            gallery_id=gallery.id,
            other_passenger=fixture.passenger_b,
        )
    finally:
        await engine.dispose()


@pytest.mark.parametrize("phase", ["creation", "completion"])
@pytest.mark.parametrize(
    "change", ["claim_replaced", "claim_expired", "feature_disabled", "consent_revoked"]
)
async def test_late_provider_result_rechecks_durable_authority(photo_database, phase, change):
    env = photo_database
    replacement = "replacement-claim-owner"

    async def change_durable_state():
        async with env.sessions() as session, session.begin():
            if change == "claim_replaced":
                await session.execute(
                    update(MyPhotoLivenessSessionModel).values(
                        provider_claim_token=replacement,
                        provider_claim_expires_at=datetime.now(UTC) + timedelta(seconds=30),
                    )
                )
            elif change == "claim_expired":
                await session.execute(
                    update(MyPhotoLivenessSessionModel).values(
                        provider_claim_expires_at=datetime.now(UTC) - timedelta(seconds=1),
                    )
                )
            elif change == "feature_disabled":
                await session.execute(
                    update(MyPhotoGalleryModel)
                    .where(
                        MyPhotoGalleryModel.id == env.gallery_id,
                    )
                    .values(feature_enabled=False)
                )
            else:
                await session.execute(
                    update(MyPhotoEnrollmentModel).values(
                        status="revoked", revoked_at=datetime.now(UTC)
                    )
                )

    class Provider:
        ready = True
        client_flow = "development_simulator"

        async def create_session(self, request):
            if phase == "creation":
                await change_durable_state()
            return LivenessSessionHandle("synthetic-provider-session", request.expires_at)

        async def get_result(self, _reference):
            await change_durable_state()
            return LivenessResult("passed", reference_face_handle="synthetic-old-reference")

    providers = SimpleNamespace(
        provider_name="development", liveness=Provider(), face_search=SimpleNamespace(ready=True)
    )
    expected = MyPhotosUnavailable if change == "feature_disabled" else MyPhotosConflict
    async with env.sessions() as session:
        service = MyPhotosService(session, settings=env.settings, providers=providers)
        start = MyPhotosLivenessStartRequest(
            challenge_mode="movement_only", idempotency_key="synthetic-start"
        )
        if phase == "completion":
            created = await service.start_liveness(
                claims=env.passenger.claims, trip=env.passenger.trip, request=start
            )
            await session.commit()
        try:
            with pytest.raises(expected):
                if phase == "creation":
                    await service.start_liveness(
                        claims=env.passenger.claims, trip=env.passenger.trip, request=start
                    )
                else:
                    await service.complete_liveness(
                        claims=env.passenger.claims,
                        trip=env.passenger.trip,
                        session_id=created.session_id,
                        request=MyPhotosLivenessCompleteRequest(
                            outcome="completed", idempotency_key="synthetic-complete"
                        ),
                    )
                await session.commit()
        finally:
            await session.rollback()
    async with env.sessions() as session:
        assert await session.scalar(select(func.count()).select_from(MyPhotoSearchRunModel)) == 0
        enrollment = await session.scalar(select(MyPhotoEnrollmentModel))
        assert enrollment.provider_reference_handle is None and enrollment.reference_version == 0
        if change == "claim_replaced":
            liveness = await session.scalar(select(MyPhotoLivenessSessionModel))
            assert liveness.provider_claim_token == replacement
            assert liveness.status == ("creating" if phase == "creation" else "running")


async def test_current_provider_claim_completes_and_replays_without_duplicate_work(photo_database):
    env = photo_database
    calls = {"create": 0, "result": 0}

    class Provider:
        ready = True
        client_flow = "development_simulator"

        async def create_session(self, request):
            calls["create"] += 1
            return LivenessSessionHandle("synthetic-provider-session", request.expires_at)

        async def get_result(self, _reference):
            calls["result"] += 1
            return LivenessResult("passed", reference_face_handle="synthetic-current-reference")

    providers = SimpleNamespace(
        provider_name="development", liveness=Provider(), face_search=SimpleNamespace(ready=True)
    )
    async with env.sessions() as session:
        service = MyPhotosService(session, settings=env.settings, providers=providers)
        start = MyPhotosLivenessStartRequest(
            challenge_mode="movement_only", idempotency_key="synthetic-valid-start"
        )
        first = await service.start_liveness(
            claims=env.passenger.claims, trip=env.passenger.trip, request=start
        )
        await session.commit()
        replay = await service.start_liveness(
            claims=env.passenger.claims, trip=env.passenger.trip, request=start
        )
        assert first.session_id == replay.session_id
        complete = MyPhotosLivenessCompleteRequest(
            outcome="completed", idempotency_key="synthetic-valid-completion"
        )
        result = await service.complete_liveness(
            claims=env.passenger.claims,
            trip=env.passenger.trip,
            session_id=first.session_id,
            request=complete,
        )
        await session.commit()
        replay_result = await service.complete_liveness(
            claims=env.passenger.claims,
            trip=env.passenger.trip,
            session_id=first.session_id,
            request=complete,
        )
        assert replay_result.search_run_id == result.search_run_id
        assert result.enrollment_status == "enrolled" and result.search_status == "queued"
        assert calls == {"create": 1, "result": 1}
        assert await session.scalar(select(func.count()).select_from(MyPhotoSearchRunModel)) == 1
        assert await session.scalar(select(func.count()).select_from(MyPhotoJobModel)) == 1
        enrollment = await session.scalar(select(MyPhotoEnrollmentModel))
        assert enrollment.reference_version == 1 and enrollment.attempt_count == 0
        assert enrollment.provider_reference_handle == "synthetic-current-reference"
