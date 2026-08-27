from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.application.security.mobile_access_policy import AuthorizedMobileTrip
from app.core.config.settings import MyPhotosSettings
from app.core.security.mobile_jwt import MobileAccessClaims
from app.infrastructure.database.gc_mobile_models import (
    GCGroupAccessModel,
    MobilePassengerIdentityModel,
)
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    PassportSubmissionModel,
)
from app.infrastructure.database.my_photos_models import (
    MyPhotoEnrollmentModel,
    MyPhotoFaceOccurrenceModel,
    MyPhotoGalleryModel,
    MyPhotoMatchModel,
    MyPhotoMediaAssetModel,
    MyPhotoSearchRunModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.my_photos.development_fixture import bootstrap_development_gallery
from app.infrastructure.my_photos.providers import build_provider_bundle
from app.infrastructure.my_photos.service import MyPhotosService
from app.infrastructure.my_photos.worker_runtime import execute_search_job
from app.presentation.api.v1.routes import mobile_my_photos
from app.presentation.dependencies.mobile_auth import require_unrestricted_mobile_claims
from app.presentation.middleware.error_handler import register_exception_handlers

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1",
        reason="requires a migrated isolated PostgreSQL service-integration database",
    ),
]


def _postgres_url() -> str:
    return (
        "postgresql+asyncpg://"
        f"{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}@"
        f"{os.environ.get('POSTGRES_HOST', 'localhost')}:"
        f"{os.environ.get('POSTGRES_PORT', '5432')}/"
        f"{os.environ['POSTGRES_DB']}"
    )


@dataclass(frozen=True, slots=True)
class _Passenger:
    identity: MobilePassengerIdentityModel
    claims: MobileAccessClaims
    trip: AuthorizedMobileTrip


@dataclass(frozen=True, slots=True)
class _Fixture:
    agency_ids: tuple[uuid.UUID, ...]
    group_ids: tuple[uuid.UUID, ...]
    submission_ids: tuple[uuid.UUID, ...]
    group: ClientGroupModel
    access: GCGroupAccessModel
    passenger_a: _Passenger
    passenger_b: _Passenger
    other_tenant: _Passenger
    same_tenant_other_group_id: uuid.UUID


def _claims(identity: MobilePassengerIdentityModel) -> MobileAccessClaims:
    return MobileAccessClaims(
        principal_id=identity.id,
        account_id=identity.id,
        principal_type="passenger",
        agency_id=identity.agency_id,
        session_id=uuid.uuid4(),
        session_generation=1,
        password_change_required=False,
        expires_at=datetime.now(tz=UTC) + timedelta(minutes=30),
    )


async def _seed_fixture(session_factory: async_sessionmaker) -> _Fixture:  # type: ignore[type-arg]
    agency_a = AgencyModel(
        id=uuid.uuid4(),
        name="My Photos Service Integration A",
        email=f"my-photos-a-{uuid.uuid4()}@example.test",
    )
    agency_b = AgencyModel(
        id=uuid.uuid4(),
        name="My Photos Service Integration B",
        email=f"my-photos-b-{uuid.uuid4()}@example.test",
    )
    group_a = ClientGroupModel(
        id=uuid.uuid4(),
        name="Synthetic MICE Group",
        token=f"my-photos-{uuid.uuid4()}",
        agency_id=agency_a.id,
        status="active",
        departure_cities=[],
    )
    group_a_other = ClientGroupModel(
        id=uuid.uuid4(),
        name="Same Tenant Other Group",
        token=f"my-photos-{uuid.uuid4()}",
        agency_id=agency_a.id,
        status="active",
        departure_cities=[],
    )
    group_b = ClientGroupModel(
        id=uuid.uuid4(),
        name="Other Tenant Group",
        token=f"my-photos-{uuid.uuid4()}",
        agency_id=agency_b.id,
        status="active",
        departure_cities=[],
    )
    submissions = tuple(
        PassportSubmissionModel(
            id=uuid.uuid4(),
            group_id=group.id,
            agency_id=group.agency_id,
            client_name=f"Synthetic Passenger {index}",
            image_s3_key=f"service-integration/{uuid.uuid4()}.jpg",
            acquisition_mode="file",
            status="staff_approved",
        )
        for index, group in enumerate((group_a, group_a, group_b), start=1)
    )
    access_a = GCGroupAccessModel(
        id=uuid.uuid4(),
        agency_id=agency_a.id,
        group_id=group_a.id,
        is_enabled=True,
        passenger_access_enabled=True,
    )
    access_a_other = GCGroupAccessModel(
        id=uuid.uuid4(),
        agency_id=agency_a.id,
        group_id=group_a_other.id,
        is_enabled=True,
        passenger_access_enabled=True,
    )
    access_b = GCGroupAccessModel(
        id=uuid.uuid4(),
        agency_id=agency_b.id,
        group_id=group_b.id,
        is_enabled=True,
        passenger_access_enabled=True,
    )
    accesses = (access_a, access_a_other, access_b)
    identities = tuple(
        MobilePassengerIdentityModel(
            id=uuid.uuid4(),
            agency_id=submission.agency_id,
            group_id=submission.group_id,
            gc_group_access_id=access.id,
            passenger_submission_id=submission.id,
            normalized_phone_number=f"+91990000{index:04d}",
            phone_lookup_hash=hashlib.sha256(f"my-photos-{uuid.uuid4()}".encode()).hexdigest(),
            status="eligible",
        )
        for index, (submission, access) in enumerate(
            zip(submissions, (access_a, access_a, access_b), strict=True),
            start=1,
        )
    )

    async with session_factory() as session:
        session.add_all((agency_a, agency_b))
        await session.flush()
        session.add_all((group_a, group_a_other, group_b))
        await session.flush()
        session.add_all(submissions)
        session.add_all(accesses)
        await session.flush()
        session.add_all(identities)
        await session.commit()

    passenger_a = _Passenger(
        identity=identities[0],
        claims=_claims(identities[0]),
        trip=AuthorizedMobileTrip(group_a, access_a, "passenger", identities[0]),
    )
    passenger_b = _Passenger(
        identity=identities[1],
        claims=_claims(identities[1]),
        trip=AuthorizedMobileTrip(group_a, access_a, "passenger", identities[1]),
    )
    other_tenant = _Passenger(
        identity=identities[2],
        claims=_claims(identities[2]),
        trip=AuthorizedMobileTrip(group_b, access_b, "passenger", identities[2]),
    )
    return _Fixture(
        agency_ids=(agency_a.id, agency_b.id),
        group_ids=(group_a.id, group_a_other.id, group_b.id),
        submission_ids=tuple(row.id for row in submissions),
        group=group_a,
        access=access_a,
        passenger_a=passenger_a,
        passenger_b=passenger_b,
        other_tenant=other_tenant,
        same_tenant_other_group_id=group_a_other.id,
    )


async def _cleanup_fixture(
    session_factory: async_sessionmaker,
    fixture: _Fixture,  # type: ignore[type-arg]
) -> None:
    async with session_factory() as session:
        # My Photos audit rows are deliberate append-only evidence. Migration
        # 0087 removes their tenant/user foreign keys and rejects UPDATE/DELETE,
        # so cleanup must retain them while removing the disposable domain rows.
        await session.execute(
            delete(PassportSubmissionModel).where(
                PassportSubmissionModel.id.in_(fixture.submission_ids)
            )
        )
        await session.execute(
            delete(ClientGroupModel).where(ClientGroupModel.id.in_(fixture.group_ids))
        )
        await session.execute(delete(AgencyModel).where(AgencyModel.id.in_(fixture.agency_ids)))
        await session.commit()


@pytest.mark.asyncio
async def test_my_photos_real_postgresql_api_and_job_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise isolation, idempotency, pagination, redelivery, lifecycle, and scale on PostgreSQL."""

    engine = create_async_engine(_postgres_url(), poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    fixture = await _seed_fixture(session_factory)
    runtime_settings = SimpleNamespace(
        app_env="development",
        app_secret_key="my-photos-service-integration-secret",
        my_photos=MyPhotosSettings(
            liveness_provider="development",
            face_search_provider="development",
            media_provider="development",
            development_fixtures_enabled=True,
        ),
    )
    providers = build_provider_bundle(runtime_settings)  # type: ignore[arg-type]
    dispatched_searches: list[uuid.UUID] = []
    dispatched_media: list[uuid.UUID] = []

    class BoundMyPhotosService(MyPhotosService):
        def __init__(self, session):  # type: ignore[no-untyped-def]
            super().__init__(
                session,
                settings=runtime_settings,  # type: ignore[arg-type]
                providers=providers,
            )

    monkeypatch.setattr(mobile_my_photos, "MyPhotosService", BoundMyPhotosService)
    monkeypatch.setattr(
        mobile_my_photos,
        "enqueue_search_job",
        lambda search_id: dispatched_searches.append(search_id),
    )
    monkeypatch.setattr(
        mobile_my_photos,
        "enqueue_media_job",
        lambda job_id: dispatched_media.append(job_id),
    )

    claims_holder = {"claims": fixture.passenger_a.claims}
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(mobile_my_photos.router, prefix="/api/v1/mobile")

    async def override_claims() -> MobileAccessClaims:
        return claims_holder["claims"]

    async def override_session():  # type: ignore[no-untyped-def]
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[require_unrestricted_mobile_claims] = override_claims
    app.dependency_overrides[get_db_session] = override_session
    base = f"/api/v1/mobile/trips/{fixture.group.id}/my-photos"

    try:
        async with session_factory() as session:
            gallery = await bootstrap_development_gallery(
                session,
                trip=fixture.passenger_a.trip,
                settings=runtime_settings,  # type: ignore[arg-type]
            )
            assert gallery.status == "ready"
            assert gallery.total_asset_count == 5_000
            gallery_id = gallery.id
            initial_asset_count = await session.scalar(
                select(func.count(MyPhotoMediaAssetModel.id)).where(
                    MyPhotoMediaAssetModel.gallery_id == gallery.id
                )
            )
            initial_face_count = await session.scalar(
                select(func.count(MyPhotoFaceOccurrenceModel.id)).where(
                    MyPhotoFaceOccurrenceModel.group_id == fixture.group.id
                )
            )
            assert (initial_asset_count, initial_face_count) == (5_000, 6_000)

        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://service-integration.test",
        ) as client:
            summary = await client.get(base)
            assert summary.status_code == 200
            assert summary.headers["Cache-Control"] == "private, no-store"
            assert summary.json()["gallery"]["total_asset_count"] == 5_000
            assert summary.json()["results"]["match_count"] == 0
            assert summary.json()["experience_state"] == "consent_required"

            consent_required = await client.post(
                f"{base}/liveness-sessions",
                json={
                    "challenge_mode": "movement_only",
                    "idempotency_key": "pre-consent-liveness",
                },
            )
            assert consent_required.status_code == 422
            assert consent_required.json()["error"]["code"] == "MY_PHOTOS_CONSENT_REQUIRED"

            async with session_factory() as session:
                disabled_gallery = await session.get(MyPhotoGalleryModel, gallery_id)
                assert disabled_gallery is not None
                disabled_gallery.feature_enabled = False
                await session.commit()
            disabled = await client.get(base)
            assert disabled.status_code == 200
            assert disabled.json()["experience_state"] == "feature_unavailable"
            assert disabled.json()["capability"]["feature_enabled"] is False
            assert disabled.json()["gallery"]["total_asset_count"] == 0
            assert disabled.json()["gallery"]["published_revision"] == 0
            assert disabled.json()["results"]["match_count"] == 0
            assert disabled.json()["search"] is None
            disabled_consent = await client.post(
                f"{base}/consent",
                json={
                    "consent_version": runtime_settings.my_photos.consent_version,
                    "accepted": True,
                    "idempotency_key": "disabled-gallery-consent",
                },
            )
            assert disabled_consent.status_code == 503
            assert (
                disabled_consent.json()["error"]["code"]
                == "MY_PHOTOS_FEATURE_UNAVAILABLE"
            )
            async with session_factory() as session:
                enabled_gallery = await session.get(MyPhotoGalleryModel, gallery_id)
                assert enabled_gallery is not None
                enabled_gallery.feature_enabled = True
                await session.commit()

            claims_holder["claims"] = fixture.other_tenant.claims
            assert (await client.get(base)).status_code == 403
            claims_holder["claims"] = fixture.passenger_a.claims
            assert (
                await client.get(
                    f"/api/v1/mobile/trips/{fixture.same_tenant_other_group_id}/my-photos"
                )
            ).status_code == 403

            consent_payload = {
                "consent_version": runtime_settings.my_photos.consent_version,
                "accepted": True,
                "idempotency_key": "consent-concurrent-a",
            }
            concurrent = await asyncio.gather(
                client.post(f"{base}/consent", json=consent_payload),
                client.post(f"{base}/consent", json=consent_payload),
            )
            assert [response.status_code for response in concurrent] == [200, 200]
            malformed = await client.post(
                f"{base}/consent",
                json={**consent_payload, "unexpected": "rejected"},
            )
            assert malformed.status_code == 422
            assert malformed.json()["error"]["code"] == "REQUEST_VALIDATION_ERROR"

            async def enroll_and_queue(prefix: str) -> uuid.UUID:
                start_payload = {
                    "challenge_mode": "movement_only",
                    "idempotency_key": f"{prefix}-liveness-start",
                }
                concurrent_starts = await asyncio.gather(
                    client.post(f"{base}/liveness-sessions", json=start_payload),
                    client.post(f"{base}/liveness-sessions", json=start_payload),
                )
                successful_starts = [
                    response for response in concurrent_starts if response.status_code == 201
                ]
                processing_responses = [
                    response for response in concurrent_starts if response.status_code == 429
                ]
                assert successful_starts
                assert len(successful_starts) + len(processing_responses) == 2
                assert len({response.json()["session_id"] for response in successful_starts}) == 1
                assert all(
                    response.json()["error"]["code"] == "MY_PHOTOS_SESSION_PROCESSING"
                    for response in processing_responses
                )
                # A same-key request that waits behind the creator may observe
                # either its in-flight claim (429) or the completed idempotent
                # result (the same 201 session), depending on lock scheduling.
                started = successful_starts[0]
                repeated = await client.post(f"{base}/liveness-sessions", json=start_payload)
                assert repeated.status_code == 201
                assert started.json()["session_id"] == repeated.json()["session_id"]
                session_id = started.json()["session_id"]
                completed = await client.post(
                    f"{base}/liveness-sessions/{session_id}/complete",
                    json={
                        "outcome": "completed",
                        "idempotency_key": f"{prefix}-liveness-complete",
                    },
                )
                assert completed.status_code == 202
                assert completed.json()["search_status"] == "queued"
                return uuid.UUID(completed.json()["search_run_id"])

            first_search = await enroll_and_queue("passenger-a-v1")
            assert dispatched_searches[-1] == first_search
            result = await execute_search_job(
                first_search,
                settings=runtime_settings,  # type: ignore[arg-type]
                providers=providers,
            )
            assert result.state == "succeeded"
            duplicate = await execute_search_job(
                first_search,
                settings=runtime_settings,  # type: ignore[arg-type]
                providers=providers,
            )
            assert duplicate.state == "noop"

            summary = await client.get(base)
            assert summary.status_code == 200
            assert summary.json()["results"]["match_count"] == 57
            assert summary.json()["results"]["snapshot_revision"] == 1

            statements: list[str] = []

            def count_page_statement(*args: object) -> None:
                statements.append(str(args[2]))

            event.listen(engine.sync_engine, "before_cursor_execute", count_page_statement)
            try:
                first_page = await client.get(
                    base + "/photos", params={"filter": "best", "limit": 20}
                )
            finally:
                event.remove(engine.sync_engine, "before_cursor_execute", count_page_statement)
            assert first_page.status_code == 200
            assert first_page.json()["total_count"] == 34
            assert len(first_page.json()["items"]) == 20
            # Includes the two policy queries (trip + passenger ownership),
            # then seven bounded gallery/page queries with one variant batch.
            assert len(statements) <= 9
            cursor = first_page.json()["next_cursor"]
            assert cursor
            second_page = await client.get(
                base + "/photos",
                params={"filter": "best", "limit": 20, "cursor": cursor},
            )
            repeated_page = await client.get(
                base + "/photos",
                params={"filter": "best", "limit": 20, "cursor": cursor},
            )
            assert second_page.status_code == repeated_page.status_code == 200
            assert second_page.json() == repeated_page.json()
            assert len(second_page.json()["items"]) == 14
            assert second_page.json()["next_cursor"] is None
            first_ids = {item["asset_id"] for item in first_page.json()["items"]}
            second_ids = {item["asset_id"] for item in second_page.json()["items"]}
            assert not first_ids & second_ids
            possible = await client.get(base + "/photos", params={"filter": "possible"})
            assert possible.status_code == 200
            assert possible.json()["total_count"] == 23
            assert possible.json()["next_cursor"] is None
            all_group = await client.get(base + "/photos", params={"filter": "all", "limit": 60})
            assert all_group.status_code == 200
            assert all_group.json()["total_count"] == 5_000
            assert len(all_group.json()["items"]) == 60
            assert all_group.json()["next_cursor"]

            downloadable = next(
                item
                for item in first_page.json()["items"]
                if item["availability_state"]
                in {"original_available_online", "delivery_available"}
                and {"original", "optimized"}.issubset(item["download_qualities"])
            )
            download_payload = {
                "items": [
                    {"asset_id": downloadable["asset_id"], "quality": "original"},
                    {"asset_id": downloadable["asset_id"], "quality": "optimized"},
                ],
                "idempotency_key": "download-passenger-a-v1",
            }
            authorized_downloads = await client.post(
                f"{base}/download-authorizations",
                json=download_payload,
            )
            assert authorized_downloads.status_code == 200
            grants = authorized_downloads.json()["authorizations"]
            assert len(grants) == 2
            assert {grant["quality"] for grant in grants} == {"original", "optimized"}
            assert all(grant["state"] == "available" for grant in grants)
            assert all(grant["transport"] == "development_fixture" for grant in grants)
            assert all(grant["authorization_id"] for grant in grants)
            assert all(grant["resource_path"] for grant in grants)

            repeated_downloads = await client.post(
                f"{base}/download-authorizations",
                json=download_payload,
            )
            assert repeated_downloads.status_code == 200
            assert {
                (grant["quality"], grant["authorization_id"])
                for grant in repeated_downloads.json()["authorizations"]
            } == {
                (grant["quality"], grant["authorization_id"])
                for grant in grants
            }

            original_grant = next(grant for grant in grants if grant["quality"] == "original")
            content = await client.get(original_grant["resource_path"])
            assert content.status_code == 200
            assert len(content.content) == original_grant["expected_size_bytes"]
            assert hashlib.sha256(content.content).hexdigest() == original_grant["checksum_sha256"]
            assert content.headers["X-Content-SHA256"] == original_grant["checksum_sha256"]
            partial = await client.get(
                original_grant["resource_path"],
                headers={"Range": "bytes=0-15"},
            )
            assert partial.status_code == 206
            assert len(partial.content) == 16
            assert partial.headers["Content-Range"].startswith("bytes 0-15/")

            claims_holder["claims"] = fixture.passenger_b.claims
            assert (await client.get(original_grant["resource_path"])).status_code == 404
            claims_holder["claims"] = fixture.passenger_a.claims

            claims_holder["claims"] = fixture.passenger_b.claims
            passenger_b_consent = {
                "consent_version": runtime_settings.my_photos.consent_version,
                "accepted": True,
                "idempotency_key": "consent-passenger-b",
            }
            assert (
                await client.post(f"{base}/consent", json=passenger_b_consent)
            ).status_code == 200
            second_search = await enroll_and_queue("passenger-b-v1")
            assert (
                await execute_search_job(
                    second_search,
                    settings=runtime_settings,  # type: ignore[arg-type]
                    providers=providers,
                )
            ).state == "succeeded"

            async with session_factory() as session:
                matches_a = set(
                    (
                        await session.execute(
                            select(MyPhotoMatchModel.media_asset_id).where(
                                MyPhotoMatchModel.passenger_identity_id
                                == fixture.passenger_a.identity.id,
                                MyPhotoMatchModel.active.is_(True),
                            )
                        )
                    ).scalars()
                )
                matches_b = set(
                    (
                        await session.execute(
                            select(MyPhotoMatchModel.media_asset_id).where(
                                MyPhotoMatchModel.passenger_identity_id
                                == fixture.passenger_b.identity.id,
                                MyPhotoMatchModel.active.is_(True),
                            )
                        )
                    ).scalars()
                )
                assert len(matches_a) == len(matches_b) == 57
                assert matches_a & matches_b
                unique_a = next(iter(matches_a - matches_b))
                shared_asset_id = await session.scalar(
                    select(MyPhotoMediaAssetModel.id).where(
                        MyPhotoMediaAssetModel.group_id == fixture.group.id,
                        MyPhotoMediaAssetModel.immutable_asset_key == "dev-asset-00000",
                    )
                )
                assert shared_asset_id in matches_a & matches_b
                offline_asset = await session.scalar(
                    select(MyPhotoMediaAssetModel)
                    .join(
                        MyPhotoMatchModel,
                        MyPhotoMatchModel.media_asset_id == MyPhotoMediaAssetModel.id,
                    )
                    .where(
                        MyPhotoMatchModel.passenger_identity_id == fixture.passenger_a.identity.id,
                        MyPhotoMatchModel.active.is_(True),
                        MyPhotoMediaAssetModel.availability_state == "archived_offline",
                    )
                    .limit(1)
                )
                if offline_asset is None:
                    offline_asset = await session.get(MyPhotoMediaAssetModel, unique_a)
                    assert offline_asset is not None
                    offline_asset.availability_state = "archived_offline"
                    offline_asset.storage_reference = None
                    await session.commit()

            claims_holder["claims"] = fixture.passenger_a.claims
            feedback_payload = {
                "feedback": "this_is_me",
                "idempotency_key": "feedback-passenger-a",
            }
            feedback = await client.put(f"{base}/photos/{unique_a}/feedback", json=feedback_payload)
            assert feedback.status_code == 200
            assert (
                await client.put(f"{base}/photos/{unique_a}/feedback", json=feedback_payload)
            ).status_code == 200
            claims_holder["claims"] = fixture.passenger_b.claims
            assert (
                await client.put(
                    f"{base}/photos/{unique_a}/feedback",
                    json={
                        "feedback": "not_me",
                        "idempotency_key": "feedback-cross-passenger",
                    },
                )
            ).status_code == 404

            claims_holder["claims"] = fixture.passenger_a.claims
            carried_feedback_response = await client.put(
                f"{base}/photos/{shared_asset_id}/feedback",
                json={
                    "feedback": "this_is_me",
                    "idempotency_key": "feedback-carry-forward-a",
                },
            )
            assert carried_feedback_response.status_code == 200
            prepared = await client.post(
                f"{base}/photos/{offline_asset.id}/prepare",
                json={"quality": "original", "idempotency_key": "prepare-offline-a"},
            )
            assert prepared.status_code == 202
            assert prepared.json()["state"] == "rehydration_requested"
            assert dispatched_media[-1] == uuid.UUID(prepared.json()["preparation_id"])
            repeated_prepare = await client.post(
                f"{base}/photos/{offline_asset.id}/prepare",
                json={"quality": "original", "idempotency_key": "prepare-offline-a"},
            )
            assert repeated_prepare.status_code == 202
            assert repeated_prepare.json()["preparation_id"] == prepared.json()["preparation_id"]

            superseding_search = await enroll_and_queue("passenger-a-v2")
            assert (
                await execute_search_job(
                    superseding_search,
                    settings=runtime_settings,  # type: ignore[arg-type]
                    providers=providers,
                )
            ).state == "succeeded"
            async with session_factory() as session:
                active_a = await session.scalar(
                    select(func.count(MyPhotoMatchModel.id)).where(
                        MyPhotoMatchModel.passenger_identity_id == fixture.passenger_a.identity.id,
                        MyPhotoMatchModel.active.is_(True),
                    )
                )
                inactive_a = await session.scalar(
                    select(func.count(MyPhotoMatchModel.id)).where(
                        MyPhotoMatchModel.passenger_identity_id == fixture.passenger_a.identity.id,
                        MyPhotoMatchModel.active.is_(False),
                    )
                )
                carried_feedback = await session.scalar(
                    select(MyPhotoMatchModel.feedback).where(
                        MyPhotoMatchModel.passenger_identity_id == fixture.passenger_a.identity.id,
                        MyPhotoMatchModel.media_asset_id == shared_asset_id,
                        MyPhotoMatchModel.active.is_(True),
                    )
                )
                assert (active_a, inactive_a, carried_feedback) == (57, 57, "this_is_me")

            claims_holder["claims"] = fixture.passenger_b.claims
            removed_b = await client.request(
                "DELETE",
                f"{base}/enrollment",
                json={
                    "scope": "enrollment_and_search_data",
                    "idempotency_key": "delete-passenger-b",
                },
            )
            assert removed_b.status_code == 200
            assert removed_b.json()["removed_search_data"] is True
            assert removed_b.json()["local_downloads_affected"] is False

            claims_holder["claims"] = fixture.passenger_a.claims
            removed_a = await client.request(
                "DELETE",
                f"{base}/enrollment",
                json={
                    "scope": "enrollment_only",
                    "idempotency_key": "delete-passenger-a",
                },
            )
            assert removed_a.status_code == 200
            assert removed_a.json()["removed_search_data"] is False
            assert removed_a.json()["local_downloads_affected"] is False

        async with session_factory() as session:
            assert (
                await session.scalar(
                    select(func.count(MyPhotoEnrollmentModel.id)).where(
                        MyPhotoEnrollmentModel.passenger_identity_id
                        == fixture.passenger_a.identity.id
                    )
                )
            ) == 1
            assert (
                await session.scalar(
                    select(func.count(MyPhotoMatchModel.id)).where(
                        MyPhotoMatchModel.passenger_identity_id == fixture.passenger_a.identity.id,
                        MyPhotoMatchModel.active.is_(True),
                    )
                )
            ) == 57
            assert (
                await session.scalar(
                    select(func.count(MyPhotoMatchModel.id)).where(
                        MyPhotoMatchModel.passenger_identity_id == fixture.passenger_b.identity.id
                    )
                )
            ) == 0
            assert (
                await session.scalar(
                    select(func.count(MyPhotoSearchRunModel.id)).where(
                        MyPhotoSearchRunModel.passenger_identity_id
                        == fixture.passenger_b.identity.id
                    )
                )
            ) == 0
            final_asset_count = await session.scalar(
                select(func.count(MyPhotoMediaAssetModel.id)).where(
                    MyPhotoMediaAssetModel.group_id == fixture.group.id
                )
            )
            final_face_count = await session.scalar(
                select(func.count(MyPhotoFaceOccurrenceModel.id)).where(
                    MyPhotoFaceOccurrenceModel.group_id == fixture.group.id
                )
            )
            assert (final_asset_count, final_face_count) == (
                initial_asset_count,
                initial_face_count,
            )
    finally:
        await _cleanup_fixture(session_factory, fixture)
        await engine.dispose()
