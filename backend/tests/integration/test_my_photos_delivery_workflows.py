"""Actual synthetic media workflows supplement provider-boundary regressions."""

import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.application.my_photos.errors import MyPhotosConflict, MyPhotosUnavailable
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.infrastructure.database.my_photos_models import (
    MyPhotoDeliveryAuthorizationModel,
    MyPhotoGalleryModel,
    MyPhotoMediaAssetModel,
)
from app.infrastructure.my_photos.providers import build_provider_bundle
from app.infrastructure.my_photos.service import MyPhotosService
from app.infrastructure.my_photos.synthetic_media import synthetic_png
from app.presentation.api.v1.schemas.my_photos_schemas import MyPhotosDownloadAuthorizationRequest
from tests.integration.test_my_photos_delivery_freshness import _authorization, _seed_delivery
from tests.integration.test_my_photos_provider_claim_freshness import (
    photo_database as photo_database,
)


@pytest.mark.parametrize("failure", [False, True])
async def test_authorization_publication_replay_and_stable_failure(photo_database, failure):
    env = photo_database
    seeded = await _seed_delivery(env)
    async with env.sessions() as session, session.begin():
        await session.delete(await session.get(MyPhotoDeliveryAuthorizationModel, seeded.grant_id))
    calls = []

    class Provider:
        async def authorize(self, request):
            calls.append(request)
            if failure:
                raise RuntimeError("synthetic-private-detail-must-not-persist")
            return _authorization(request)

    providers = SimpleNamespace(provider_name="aws", media=Provider())
    request = MyPhotosDownloadAuthorizationRequest(
        idempotency_key="synthetic-workflow",
        items=[{"asset_id": seeded.asset_id, "quality": "original"}],
    )
    async with env.sessions() as session:
        service = MyPhotosService(session, settings=env.settings, providers=providers)
        response = await service.authorize_downloads(
            claims=env.passenger.claims,
            trip=env.passenger.trip,
            request=request,
        )
        await session.commit()
        assert response.authorizations[0].state == ("unavailable" if failure else "available")
        if not failure:
            replay = await service.authorize_downloads(
                claims=env.passenger.claims,
                trip=env.passenger.trip,
                request=request,
            )
            assert (
                replay.authorizations[0].authorization_id
                == response.authorizations[0].authorization_id
            )
            with pytest.raises(MyPhotosConflict) as captured:
                await service.authorize_downloads(
                    claims=env.passenger.claims,
                    trip=env.passenger.trip,
                    request=request.model_copy(
                        update={
                            "items": [
                                request.items[0].model_copy(
                                    update={"quality": "optimized"},
                                )
                            ]
                        }
                    ),
                )
            assert captured.value.code == "MY_PHOTOS_QUALITY_UNAVAILABLE"
            await session.rollback()
    assert len(calls) == 1
    async with env.sessions() as session:
        row = await session.scalar(select(MyPhotoDeliveryAuthorizationModel))
        if failure:
            assert row.status == "failed"
            assert row.stable_error_code == "DELIVERY_PROVIDER_UNAVAILABLE"
            assert row.provider_authorization_reference is None
        else:
            assert row.status == "available"
            assert row.expires_at.replace(tzinfo=UTC) <= seeded.end


@pytest.mark.parametrize("change", [None, "expired", "integrity", "disabled_fixture"])
async def test_development_media_uses_only_authenticated_synthetic_content(photo_database, change):
    env = photo_database
    seeded = await _seed_delivery(env)
    env.settings.my_photos = env.settings.my_photos.model_copy(
        update={
            "liveness_provider": "development",
            "face_search_provider": "development",
            "media_provider": "development",
            "development_fixtures_enabled": change != "disabled_fixture",
        }
    )
    providers = build_provider_bundle(env.settings)
    content = synthetic_png("synthetic-delivery-asset", "original")
    async with env.sessions() as session, session.begin():
        gallery = await session.get(MyPhotoGalleryModel, env.gallery_id)
        gallery.provider_name = "development"
        asset = await session.get(MyPhotoMediaAssetModel, seeded.asset_id)
        asset.mime_type = "image/png"
        asset.byte_size = len(content)
        asset.checksum_sha256 = hashlib.sha256(content).hexdigest()
        grant = await session.get(MyPhotoDeliveryAuthorizationModel, seeded.grant_id)
        grant.transport = "development_fixture"
        grant.expected_size_bytes = len(content)
        grant.checksum_sha256 = "0" * 64 if change == "integrity" else asset.checksum_sha256
        grant.content_type = "image/png"
        if change == "expired":
            grant.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    async with env.sessions() as session:
        service = MyPhotosService(session, settings=env.settings, providers=providers)
        if change in {"expired", "integrity"}:
            with pytest.raises(MyPhotosUnavailable):
                await service.development_download_content(
                    claims=env.passenger.claims,
                    trip=env.passenger.trip,
                    authorization_id=seeded.grant_id,
                )
        else:
            delivered, mime_type, checksum = await service.development_download_content(
                claims=env.passenger.claims,
                trip=env.passenger.trip,
                authorization_id=seeded.grant_id,
            )
            assert delivered == content and mime_type == "image/png"
            assert checksum == hashlib.sha256(content).hexdigest()
        if change == "disabled_fixture":
            with pytest.raises(EntityNotFoundError):
                await service.development_preview_content(
                    claims=env.passenger.claims,
                    trip=env.passenger.trip,
                    asset_id=seeded.asset_id,
                    variant="preview",
                )
        elif change is None:
            preview, _checksum = await service.development_preview_content(
                claims=env.passenger.claims,
                trip=env.passenger.trip,
                asset_id=seeded.asset_id,
                variant="preview",
            )
            assert preview.startswith(b"\x89PNG\r\n\x1a\n")
