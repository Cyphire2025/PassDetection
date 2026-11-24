"""Delivery provider awaits cannot restart access windows or accept stale claims."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select, update

from app.application.my_photos.errors import MyPhotosUnavailable
from app.application.my_photos.providers import DeliveryAuthorization, DeliveryResolution
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.infrastructure.database.my_photos_models import (
    MyPhotoAssetVariantModel,
    MyPhotoDeliveryAuthorizationModel,
    MyPhotoGalleryModel,
    MyPhotoMediaAssetModel,
)
from app.infrastructure.my_photos.service import MyPhotosService
from app.presentation.api.v1.schemas.my_photos_schemas import (
    MyPhotosDownloadAuthorizationRequest,
)
from tests.integration.test_my_photos_provider_claim_freshness import (
    photo_database as photo_database,
)


async def _seed_delivery(env):
    now = datetime.now(UTC)
    async with env.sessions() as session, session.begin():
        gallery = await session.get(MyPhotoGalleryModel, env.gallery_id)
        gallery.all_group_photos_enabled = True
        gallery.provider_name = "aws"
        gallery.availability_ends_at = now + timedelta(seconds=30)
        asset = MyPhotoMediaAssetModel(
            id=uuid.uuid4(),
            gallery_id=gallery.id,
            agency_id=gallery.agency_id,
            group_id=gallery.group_id,
            immutable_asset_key="synthetic-delivery-asset",
            media_type="photo",
            archive_reference="synthetic-archive",
            storage_reference="synthetic-object",
            original_filename="synthetic.jpg",
            mime_type="image/jpeg",
            width=640,
            height=480,
            aspect_ratio=640 / 480,
            byte_size=1234,
            checksum_sha256="a" * 64,
            processing_state="indexed",
            availability_state="original_available_online",
            published_revision=1,
            sort_rank=0,
        )
        session.add(asset)
        await session.flush()
        session.add(
            MyPhotoAssetVariantModel(
                media_asset_id=asset.id,
                agency_id=gallery.agency_id,
                group_id=gallery.group_id,
                variant_kind="preview",
                storage_reference="synthetic-preview",
                mime_type="image/jpeg",
                width=640,
                height=480,
                byte_size=1234,
                checksum_sha256="a" * 64,
                availability_state="delivery_available",
                delivery_version=1,
            )
        )
        identity = env.passenger.identity
        grant = MyPhotoDeliveryAuthorizationModel(
            id=uuid.uuid4(),
            passenger_identity_id=identity.id,
            passenger_submission_id=identity.passenger_submission_id,
            gc_group_access_id=identity.gc_group_access_id,
            agency_id=gallery.agency_id,
            group_id=gallery.group_id,
            media_asset_id=asset.id,
            quality="original",
            status="available",
            idempotency_key="synthetic-grant",
            request_fingerprint="a" * 64,
            delivery_version=1,
            provider_authorization_reference="synthetic-provider-grant",
            transport="direct_object_storage",
            expected_size_bytes=1234,
            checksum_sha256="a" * 64,
            content_type="image/jpeg",
            supports_ranges=True,
            expires_at=now + timedelta(seconds=300),
        )
        session.add(grant)
    return SimpleNamespace(asset_id=asset.id, grant_id=grant.id, end=gallery.availability_ends_at)


def _authorization(request):
    return DeliveryAuthorization(
        state="delivery_available",
        provider_authorization_reference="synthetic-provider-grant",
        expected_size_bytes=request.expected_size_bytes,
        checksum_sha256=request.checksum_sha256,
        supports_ranges=True,
        expires_at=datetime.now(UTC) + timedelta(seconds=299),
        content_type=request.content_type,
        transport="direct_object_storage",
    )


async def _resolve(service, env, seeded, mode):
    if mode == "download":
        return await service.production_download_location(
            claims=env.passenger.claims,
            trip=env.passenger.trip,
            authorization_id=seeded.grant_id,
        )
    return await service.preview_content_or_location(
        claims=env.passenger.claims,
        trip=env.passenger.trip,
        asset_id=seeded.asset_id,
        variant="preview",
    )


@pytest.mark.parametrize("mode", ["download", "preview"])
@pytest.mark.parametrize("change", ["disabled", "window_expired", "asset_removed"])
async def test_delivery_rechecks_scope_after_provider_await(photo_database, mode, change):
    env = photo_database
    seeded = await _seed_delivery(env)

    class Provider:
        async def authorize(self, request):
            return _authorization(request)

        async def resolve(self, request):
            async with env.sessions() as session, session.begin():
                if change == "asset_removed":
                    await session.execute(
                        update(MyPhotoMediaAssetModel)
                        .where(
                            MyPhotoMediaAssetModel.id == seeded.asset_id,
                        )
                        .values(processing_state="removed", availability_state="removed")
                    )
                else:
                    values = (
                        {"feature_enabled": False}
                        if change == "disabled"
                        else {"availability_ends_at": datetime.now(UTC) - timedelta(seconds=1)}
                    )
                    await session.execute(
                        update(MyPhotoGalleryModel)
                        .where(
                            MyPhotoGalleryModel.id == env.gallery_id,
                        )
                        .values(**values)
                    )
            return DeliveryResolution(
                "https://storage.example.test/private", request.expires_at, True
            )

    providers = SimpleNamespace(provider_name="aws", media=Provider())
    async with env.sessions() as session:
        service = MyPhotosService(session, settings=env.settings, providers=providers)
        with pytest.raises((MyPhotosUnavailable, EntityNotFoundError)):
            await _resolve(service, env, seeded, mode)


@pytest.mark.parametrize("mode", ["download", "preview"])
async def test_delivery_deadline_does_not_exceed_gallery_access_window(photo_database, mode):
    env = photo_database
    seeded = await _seed_delivery(env)
    requests = []

    class Provider:
        async def authorize(self, request):
            return _authorization(request)

        async def resolve(self, request):
            requests.append(request)
            return DeliveryResolution(
                "https://storage.example.test/private", request.expires_at, True
            )

    providers = SimpleNamespace(provider_name="aws", media=Provider())
    async with env.sessions() as session:
        service = MyPhotosService(session, settings=env.settings, providers=providers)
        response = await _resolve(service, env, seeded, mode)
    assert requests[0].expires_at <= seeded.end
    assert response.expires_at <= seeded.end


@pytest.mark.parametrize("change", ["replaced", "expired"])
async def test_delivery_authorization_cannot_publish_over_a_changed_claim(photo_database, change):
    env = photo_database
    seeded = await _seed_delivery(env)
    async with env.sessions() as session, session.begin():
        await session.delete(await session.get(MyPhotoDeliveryAuthorizationModel, seeded.grant_id))

    class Provider:
        async def authorize(self, request):
            async with env.sessions() as session, session.begin():
                values = (
                    {"claim_token": "synthetic-new-owner"}
                    if change == "replaced"
                    else {"claim_expires_at": datetime.now(UTC) - timedelta(seconds=1)}
                )
                await session.execute(
                    update(MyPhotoDeliveryAuthorizationModel)
                    .where(
                        MyPhotoDeliveryAuthorizationModel.media_asset_id == seeded.asset_id,
                    )
                    .values(**values)
                )
            return _authorization(request)

    providers = SimpleNamespace(provider_name="aws", media=Provider())
    request = MyPhotosDownloadAuthorizationRequest(
        idempotency_key="synthetic-new-download",
        items=[{"asset_id": seeded.asset_id, "quality": "original"}],
    )
    async with env.sessions() as session:
        service = MyPhotosService(session, settings=env.settings, providers=providers)
        await service.authorize_downloads(
            claims=env.passenger.claims,
            trip=env.passenger.trip,
            request=request,
        )
        await session.commit()
    async with env.sessions() as session:
        row = await session.scalar(
            select(MyPhotoDeliveryAuthorizationModel).where(
                MyPhotoDeliveryAuthorizationModel.media_asset_id == seeded.asset_id,
            )
        )
        assert row.status == "authorizing"
        assert row.provider_authorization_reference is None
        if change == "replaced":
            assert row.claim_token == "synthetic-new-owner"


@pytest.mark.parametrize("change", ["cancelled", "replaced"])
async def test_download_rechecks_current_grant_after_provider_await(photo_database, change):
    env = photo_database
    seeded = await _seed_delivery(env)

    class Provider:
        async def resolve(self, request):
            async with env.sessions() as session, session.begin():
                row = await session.get(MyPhotoDeliveryAuthorizationModel, seeded.grant_id)
                if change == "cancelled":
                    row.status = "cancelled"
                    row.provider_authorization_reference = None
                    row.transport = "unavailable"
                    row.expected_size_bytes = None
                    row.checksum_sha256 = None
                    row.content_type = None
                    row.supports_ranges = False
                    row.expires_at = None
                else:
                    row.provider_authorization_reference = "synthetic-replacement-grant"
            return DeliveryResolution(
                "https://storage.example.test/private", request.expires_at, True
            )

    providers = SimpleNamespace(provider_name="aws", media=Provider())
    async with env.sessions() as session:
        service = MyPhotosService(session, settings=env.settings, providers=providers)
        with pytest.raises((MyPhotosUnavailable, EntityNotFoundError)):
            await _resolve(service, env, seeded, "download")


async def test_preview_deadline_is_bounded_by_the_current_derivative_expiry(photo_database):
    env = photo_database
    seeded = await _seed_delivery(env)
    expiry = datetime.now(UTC) + timedelta(seconds=5)
    async with env.sessions() as session, session.begin():
        await session.execute(
            update(MyPhotoAssetVariantModel)
            .where(
                MyPhotoAssetVariantModel.media_asset_id == seeded.asset_id,
            )
            .values(expires_at=expiry)
        )
    requests = []

    class Provider:
        async def authorize(self, request):
            return _authorization(request)

        async def resolve(self, request):
            requests.append(request)
            return DeliveryResolution(
                "https://storage.example.test/private", request.expires_at, True
            )

    providers = SimpleNamespace(provider_name="aws", media=Provider())
    async with env.sessions() as session:
        service = MyPhotosService(session, settings=env.settings, providers=providers)
        await _resolve(service, env, seeded, "preview")
    assert requests[0].expires_at <= expiry
