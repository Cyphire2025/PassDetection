from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.application.my_photos.cursor import GalleryCursor, GalleryCursorCodec
from app.application.my_photos.errors import (
    MyPhotosInvalidCursor,
    MyPhotosRateLimited,
    MyPhotosUnavailable,
)
from app.application.my_photos.limits import MAX_MY_PHOTOS_MEDIA_BYTES
from app.application.my_photos.providers import (
    DeliveryAuthorization,
    DeliveryRequest,
    LivenessResult,
    LivenessSessionHandle,
)
from app.core.config.settings import MyPhotosSettings
from app.infrastructure.database.my_photos_models import (
    MyPhotoAssetVariantModel,
    MyPhotoEnrollmentModel,
    MyPhotoGalleryModel,
    MyPhotoJobModel,
    MyPhotoLivenessSessionModel,
    MyPhotoMediaAssetModel,
)
from app.infrastructure.my_photos import (
    MY_PHOTOS_CONTROL_QUEUE,
    MY_PHOTOS_INDEX_QUEUE,
    MY_PHOTOS_INDEX_TASK,
    MY_PHOTOS_MEDIA_QUEUE,
    MY_PHOTOS_MEDIA_TASK,
    MY_PHOTOS_RECOVERY_TASK,
    MY_PHOTOS_SEARCH_QUEUE,
    MY_PHOTOS_SEARCH_TASK,
)
from app.infrastructure.my_photos.delivery_service import (
    MyPhotosDeliveryService,
    _authorize_provider_batch,
    _validated_delivery_authorization,
)
from app.infrastructure.my_photos.revision_runtime import publish_gallery_revision
from app.infrastructure.my_photos.service import (
    MyPhotosService,
    _validated_liveness_result,
    _validated_liveness_session_handle,
)
from app.infrastructure.my_photos.summary_projector import MyPhotosSummaryProjector
from app.infrastructure.processing.celery_app import celery_app
from app.presentation.api.v1.routes.mobile_my_photos import (
    _image_extension,
    _photo_preview_bytes_response,
    _rate_limited_response,
)
from app.presentation.api.v1.schemas.my_photos_schemas import (
    MyPhotosConsentRequest,
    MyPhotosDownloadAuthorizationRequest,
    MyPhotosDownloadEstimateQualityResponse,
    MyPhotosPhotoPageResponse,
    MyPhotosSearchRunResponse,
)


def _delivery_request() -> DeliveryRequest:
    return DeliveryRequest(
        tenant_scope="tenant-a",
        group_scope="group-a",
        passenger_scope="passenger-a",
        authorization_identity="authorization-a:1",
        asset_identity="asset-a",
        media_reference="private/tenant-a/group-a/asset-a/original",
        quality="original",
        availability_state="original_available_online",
        expected_size_bytes=123,
        checksum_sha256="a" * 64,
        content_type="image/png",
    )


def _delivery_result() -> DeliveryAuthorization:
    return DeliveryAuthorization(
        state="delivery_available",
        provider_authorization_reference="opaque-delivery-reference",
        expected_size_bytes=123,
        checksum_sha256="a" * 64,
        supports_ranges=True,
        expires_at=datetime.now(tz=UTC) + timedelta(seconds=120),
        content_type="image/png",
        transport="direct_object_storage",
    )


def test_strict_requests_reject_unknown_fields_and_duplicate_assets() -> None:
    with pytest.raises(ValidationError):
        MyPhotosConsentRequest.model_validate(
            {
                "consent_version": "consent-v1",
                "accepted": True,
                "idempotency_key": "consent-key-1",
                "unexpected": "rejected",
            }
        )
    asset_id = uuid.uuid4()
    with pytest.raises(ValidationError):
        MyPhotosDownloadAuthorizationRequest.model_validate(
            {
                "idempotency_key": "download-key-1",
                "items": [
                    {"asset_id": str(asset_id), "quality": "original"},
                    {"asset_id": str(asset_id), "quality": "original"},
                ],
            }
        )


def test_gallery_cursor_is_scope_filter_revision_and_signature_bound() -> None:
    passenger_id, group_id, asset_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    codec = GalleryCursorCodec("cursor-contract-secret")
    token = codec.encode(GalleryCursor(passenger_id, group_id, 4, "best", 27, asset_id))
    decoded = codec.decode(
        token,
        passenger_id=passenger_id,
        group_id=group_id,
        revision=4,
        match_filter="best",
    )
    assert (decoded.sort_rank, decoded.asset_id) == (27, asset_id)
    for kwargs in (
        {"passenger_id": uuid.uuid4(), "group_id": group_id, "revision": 4, "match_filter": "best"},
        {
            "passenger_id": passenger_id,
            "group_id": uuid.uuid4(),
            "revision": 4,
            "match_filter": "best",
        },
        {
            "passenger_id": passenger_id,
            "group_id": group_id,
            "revision": 4,
            "match_filter": "possible",
        },
    ):
        with pytest.raises(MyPhotosInvalidCursor) as captured:
            codec.decode(token, **kwargs)  # type: ignore[arg-type]
        assert captured.value.code == "MY_PHOTOS_CURSOR_INVALID"
    with pytest.raises(MyPhotosInvalidCursor) as stale:
        codec.decode(
            token,
            passenger_id=passenger_id,
            group_id=group_id,
            revision=5,
            match_filter="best",
        )
    assert stale.value.code == "MY_PHOTOS_CURSOR_STALE"
    with pytest.raises(MyPhotosInvalidCursor):
        codec.decode(
            token[:-1] + ("A" if token[-1] != "A" else "B"),
            passenger_id=passenger_id,
            group_id=group_id,
            revision=4,
            match_filter="best",
        )


def test_empty_final_photo_page_is_strict_and_snapshot_bound() -> None:
    response = MyPhotosPhotoPageResponse.model_validate(
        {
            "snapshot_revision": 1,
            "filter": "best",
            "items": [],
            "next_cursor": None,
            "page_size": 48,
            "total_count": 0,
        }
    )
    assert response.items == []
    assert response.next_cursor is None
    with pytest.raises(ValidationError):
        MyPhotosPhotoPageResponse.model_validate(
            {
                **response.model_dump(mode="json"),
                "unexpected": "rejected",
            }
        )


def test_download_estimate_schema_enforces_mobile_item_ceiling() -> None:
    values = {
        "quality": "original",
        "supported_item_count": 1,
        "exact_byte_total": MAX_MY_PHOTOS_MEDIA_BYTES,
        "maximum_item_bytes": MAX_MY_PHOTOS_MEDIA_BYTES,
        "estimate_complete": True,
    }
    assert (
        MyPhotosDownloadEstimateQualityResponse.model_validate(values).maximum_item_bytes
        == MAX_MY_PHOTOS_MEDIA_BYTES
    )
    with pytest.raises(ValidationError):
        MyPhotosDownloadEstimateQualityResponse.model_validate(
            {**values, "maximum_item_bytes": MAX_MY_PHOTOS_MEDIA_BYTES + 1}
        )


@pytest.mark.asyncio
async def test_expired_ready_gallery_publishes_revision_while_withholding_results() -> None:
    now = datetime.now(tz=UTC)
    session = SimpleNamespace(execute=AsyncMock(side_effect=AssertionError("unexpected query")))
    projector = MyPhotosSummaryProjector(
        session,  # type: ignore[arg-type]
        settings=SimpleNamespace(  # type: ignore[arg-type]
            my_photos=SimpleNamespace(
                consent_version="consent-v1",
                maximum_liveness_attempts=5,
            )
        ),
        providers=SimpleNamespace(  # type: ignore[arg-type]
            liveness=SimpleNamespace(ready=True, client_flow="native"),
            face_search=SimpleNamespace(ready=True),
        ),
        gallery_window_state=lambda _gallery, _now: "expired",
        search_response=lambda selected: (
            None
            if selected is None
            else MyPhotosSearchRunResponse(
                id=selected.id,
                status=selected.status,
                processed_face_count=selected.processed_face_count,
                total_face_count=selected.total_face_count,
                progress_percent=100,
                matched_photo_count=selected.matched_asset_count,
                best_match_count=selected.best_match_count,
                possible_match_count=selected.possible_match_count,
                started_at=selected.started_at,
                completed_at=selected.completed_at,
                error_code=None,
            )
        ),
    )
    gallery = SimpleNamespace(
        id=uuid.uuid4(),
        feature_enabled=True,
        status="ready",
        published_revision=7,
        media_version=7,
        face_index_version=7,
        total_asset_count=500,
        indexed_asset_count=500,
        failed_asset_count=0,
        all_group_photos_enabled=True,
        published_at=now - timedelta(days=1),
        updated_at=now,
    )
    enrollment = SimpleNamespace(
        status="enrolled",
        consent_version="consent-v1",
        reference_version=3,
        max_attempts=5,
        attempt_count=1,
        cooldown_until=None,
        enrolled_at=now - timedelta(days=2),
        updated_at=now - timedelta(days=2),
        consented_at=now - timedelta(days=2),
    )
    search = SimpleNamespace(
        id=uuid.uuid4(),
        status="complete",
        gallery_revision=7,
        processed_face_count=500,
        total_face_count=500,
        matched_asset_count=19,
        best_match_count=15,
        possible_match_count=4,
        started_at=now - timedelta(minutes=2),
        completed_at=now - timedelta(minutes=1),
        stable_error_code=None,
    )

    response = await projector.build(
        group_name="Expired Gallery",
        group_id=uuid.uuid4(),
        gallery=gallery,  # type: ignore[arg-type]
        enrollment=enrollment,  # type: ignore[arg-type]
        search=search,  # type: ignore[arg-type]
        passenger_identity_id=uuid.uuid4(),
    )

    assert response.experience_state == "access_expired"
    assert response.capability.feature_enabled is True
    assert response.gallery.status == "ready"
    assert response.results.snapshot_revision == 7
    assert response.results.match_count == 0
    assert response.results.new_photo_count == 0
    assert response.results.downloadable_count == 0
    assert response.results.preparing_count == 0
    assert response.results.last_updated_at is None
    assert response.search is None
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_disabled_gallery_is_a_sanitized_capability_only_projection() -> None:
    now = datetime.now(tz=UTC)
    session = SimpleNamespace(execute=AsyncMock(side_effect=AssertionError("unexpected query")))
    projector = MyPhotosSummaryProjector(
        session,  # type: ignore[arg-type]
        settings=SimpleNamespace(  # type: ignore[arg-type]
            my_photos=SimpleNamespace(
                consent_version="consent-v1",
                maximum_liveness_attempts=5,
            )
        ),
        providers=SimpleNamespace(  # type: ignore[arg-type]
            liveness=SimpleNamespace(ready=True, client_flow="native"),
            face_search=SimpleNamespace(ready=True),
        ),
        gallery_window_state=lambda _gallery, _now: "active",
        search_response=lambda selected: (
            None
            if selected is None
            else (_ for _ in ()).throw(AssertionError("disabled search leaked"))
        ),
    )
    gallery = SimpleNamespace(
        id=uuid.uuid4(),
        feature_enabled=False,
        status="ready",
        published_revision=9,
        media_version=9,
        face_index_version=9,
        total_asset_count=5_000,
        indexed_asset_count=4_999,
        failed_asset_count=1,
        all_group_photos_enabled=True,
        published_at=now - timedelta(days=1),
        updated_at=now,
    )
    enrollment = SimpleNamespace(
        status="enrolled",
        consent_version="consent-v1",
        reference_version=3,
        max_attempts=5,
        attempt_count=1,
        cooldown_until=None,
        enrolled_at=now - timedelta(days=2),
        updated_at=now - timedelta(days=2),
        consented_at=now - timedelta(days=2),
    )
    search = SimpleNamespace(
        id=uuid.uuid4(),
        status="complete",
        gallery_revision=9,
        processed_face_count=5_000,
        total_face_count=5_000,
        matched_asset_count=19,
        best_match_count=15,
        possible_match_count=4,
        started_at=now - timedelta(minutes=2),
        completed_at=now - timedelta(minutes=1),
        stable_error_code=None,
    )

    response = await projector.build(
        group_name="Disabled Gallery",
        group_id=uuid.uuid4(),
        gallery=gallery,  # type: ignore[arg-type]
        enrollment=enrollment,  # type: ignore[arg-type]
        search=search,  # type: ignore[arg-type]
        passenger_identity_id=uuid.uuid4(),
    )

    assert response.experience_state == "feature_unavailable"
    assert response.capability.feature_enabled is False
    assert response.gallery.status == "not_uploaded"
    assert response.gallery.published_revision == 0
    assert response.gallery.media_version == 0
    assert response.gallery.face_index_version == 0
    assert response.gallery.total_asset_count == 0
    assert response.gallery.indexed_asset_count == 0
    assert response.gallery.failed_asset_count == 0
    assert response.gallery.all_group_photos_enabled is False
    assert response.gallery.published_at is None
    assert response.enrollment.status == "consent_required"
    assert response.search is None
    assert response.results.match_count == 0
    assert response.results.downloadable_count == 0
    assert response.results.preparing_count == 0
    session.execute.assert_not_awaited()


def test_my_photos_tasks_use_dedicated_routes_without_moving_document_jobs() -> None:
    routes = celery_app.conf.task_routes
    assert routes[MY_PHOTOS_SEARCH_TASK] == {"queue": MY_PHOTOS_SEARCH_QUEUE}
    assert routes[MY_PHOTOS_INDEX_TASK] == {"queue": MY_PHOTOS_INDEX_QUEUE}
    assert routes[MY_PHOTOS_MEDIA_TASK] == {"queue": MY_PHOTOS_MEDIA_QUEUE}
    assert routes[MY_PHOTOS_RECOVERY_TASK] == {"queue": MY_PHOTOS_CONTROL_QUEUE}

    beat = celery_app.conf.beat_schedule
    assert beat["recover-my-photos-durable-jobs"] == {
        "task": MY_PHOTOS_RECOVERY_TASK,
        "schedule": 30.0,
        "options": {"queue": MY_PHOTOS_CONTROL_QUEUE},
    }
    assert beat["cleanup-deferred-document-storage"]["options"]["queue"] == "passport_ocr"
    assert beat["reconcile-orphaned-document-storage"]["options"]["queue"] == "passport_ocr"


def test_rate_limit_response_is_private_stable_and_bounded() -> None:
    response = _rate_limited_response(
        MyPhotosRateLimited(
            45,
            "Face Scan is being processed. Try again shortly.",
            code="MY_PHOTOS_SESSION_PROCESSING",
        )
    )
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "45"
    assert response.headers["Cache-Control"] == "private, no-store"
    assert b"MY_PHOTOS_SESSION_PROCESSING" in response.body


def test_authenticated_preview_bytes_are_no_store_and_use_content_derived_extension() -> None:
    asset_id = uuid.uuid4()
    response = _photo_preview_bytes_response(
        content=b"private-photo-bytes",
        checksum="a" * 64,
        asset_id=asset_id,
        variant="preview",
    )
    assert response.headers["Cache-Control"] == "private, no-store"
    assert response.headers["Pragma"] == "no-cache"
    assert "ETag" not in response.headers
    assert response.headers["Content-Disposition"] == (
        f'inline; filename="my-photo-{asset_id}-preview.png"'
    )
    assert _image_extension("image/jpeg") == ".jpg"
    assert _image_extension("image/png") == ".png"
    assert _image_extension("image/webp") == ".webp"


@pytest.mark.parametrize(
    "malformed",
    [
        replace(_delivery_result(), provider_authorization_reference="https://public.example/a"),
        replace(_delivery_result(), expected_size_bytes=122),
        replace(_delivery_result(), checksum_sha256="b" * 64),
        replace(_delivery_result(), content_type="image/jpeg"),
        replace(
            _delivery_result(),
            expires_at=datetime.now(tz=UTC) + timedelta(seconds=600),
        ),
    ],
)
def test_delivery_provider_results_fail_closed_when_malformed(
    malformed: DeliveryAuthorization,
) -> None:
    with pytest.raises(ValueError):
        _validated_delivery_authorization(
            malformed,
            _delivery_request(),
            maximum_ttl_seconds=300,
        )


@pytest.mark.asyncio
async def test_delivery_authorization_batch_is_ordered_bounded_and_partial() -> None:
    class Provider:
        ready = True

        def __init__(self) -> None:
            self.active = 0
            self.maximum_active = 0

        async def authorize(self, request: DeliveryRequest) -> DeliveryAuthorization:
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
            try:
                await asyncio.sleep(0.01)
                if request.authorization_identity.endswith(":2"):
                    raise MyPhotosUnavailable(
                        "MY_PHOTOS_MEDIA_UNAVAILABLE", "Photo delivery is unavailable."
                    )
                return _delivery_result()
            finally:
                self.active -= 1

    provider = Provider()
    calls = tuple(
        (
            uuid.uuid4(),
            f"claim-{index}",
            replace(_delivery_request(), authorization_identity=f"authorization:{index}"),
        )
        for index in range(5)
    )
    results = await _authorize_provider_batch(
        provider=provider,  # type: ignore[arg-type]
        pending_calls=calls,
        maximum_ttl_seconds=300,
        timeout_seconds=1,
        concurrency=2,
        maximum_batch_size=5,
    )
    assert provider.maximum_active == 2
    assert [result[0] for result in results] == [call[0] for call in calls]
    assert results[2][2] is None
    assert results[2][3] == "MY_PHOTOS_MEDIA_UNAVAILABLE"
    assert sum(result[2] is not None for result in results) == 4


@pytest.mark.asyncio
async def test_delivery_authorization_batch_bounds_each_provider_timeout() -> None:
    class SlowProvider:
        ready = True

        async def authorize(self, request: DeliveryRequest) -> DeliveryAuthorization:
            del request
            await asyncio.sleep(0.1)
            return _delivery_result()

    call = (uuid.uuid4(), "claim-timeout", _delivery_request())
    results = await _authorize_provider_batch(
        provider=SlowProvider(),  # type: ignore[arg-type]
        pending_calls=(call,),
        maximum_ttl_seconds=300,
        timeout_seconds=0.01,  # type: ignore[arg-type]
        concurrency=1,
        maximum_batch_size=1,
    )
    assert results[0][2] is None
    assert results[0][3] == "DELIVERY_PROVIDER_UNAVAILABLE"


def test_liveness_provider_results_are_bounded_and_shape_checked() -> None:
    now = datetime.now(tz=UTC)
    requested_expiry = now + timedelta(seconds=180)
    valid = _validated_liveness_session_handle(
        LivenessSessionHandle("opaque-session", now + timedelta(seconds=120)),
        requested_expiry=requested_expiry,
        client_flow="development_simulator",
    )
    assert valid.provider_reference == "opaque-session"
    with pytest.raises(ValueError):
        _validated_liveness_session_handle(
            LivenessSessionHandle("https://public.example/session", requested_expiry),
            requested_expiry=requested_expiry,
            client_flow="development_simulator",
        )
    with pytest.raises(ValueError):
        _validated_liveness_session_handle(
            LivenessSessionHandle("opaque-session", now + timedelta(seconds=120)),
            requested_expiry=requested_expiry,
            client_flow="native",
        )
    native = _validated_liveness_session_handle(
        LivenessSessionHandle(
            "opaque-session",
            now + timedelta(seconds=120),
            native_launch_handle="opaque-native-launch",
        ),
        requested_expiry=requested_expiry,
        client_flow="native",
    )
    assert native.native_launch_handle == "opaque-native-launch"
    with pytest.raises(ValueError):
        _validated_liveness_result(LivenessResult(outcome="passed", reference_face_handle=None))
    with pytest.raises(ValueError):
        _validated_liveness_result(
            LivenessResult(
                outcome="rejected",
                reference_face_handle="must-not-survive",
            )
        )


def test_nonretryable_liveness_result_is_not_advertised_as_retryable() -> None:
    now = datetime.now(tz=UTC)
    session = MyPhotoLivenessSessionModel(
        id=uuid.uuid4(),
        enrollment_id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        idempotency_key="session-key-1",
        challenge_mode="movement_only",
        status="rejected",
        provider_name="provider",
        provider_session_reference="opaque-session",
        stable_error_code="LIVENESS_REJECTED",
        completion_idempotency_key="completion-key-1",
        completion_outcome="completed",
        result_retryable=False,
        expires_at=now + timedelta(seconds=60),
        consumed_at=now,
    )
    enrollment = MyPhotoEnrollmentModel(status="rejected", cooldown_until=None)
    response = MyPhotosService._completion_response(  # type: ignore[arg-type]
        None,
        session,
        enrollment,
        None,
    )
    assert response.retryable is False
    assert response.error_code == "LIVENESS_REJECTED"


def test_provider_timeouts_must_be_shorter_than_durable_claims() -> None:
    with pytest.raises(ValidationError):
        MyPhotosSettings(
            liveness_provider_claim_seconds=10,
            liveness_provider_timeout_seconds=10,
        )
    with pytest.raises(ValidationError):
        MyPhotosSettings(job_lease_seconds=30, face_search_provider_timeout_seconds=30)
    with pytest.raises(ValidationError):
        MyPhotosSettings(delivery_claim_seconds=15, media_provider_timeout_seconds=15)


@pytest.mark.asyncio
async def test_gallery_revision_publication_is_atomic_and_queues_bounded_refresh() -> None:
    gallery = MyPhotoGalleryModel(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        feature_enabled=True,
        status="indexing",
        media_version=2,
        face_index_version=2,
        published_revision=1,
        total_asset_count=5_000,
        indexed_asset_count=5_002,
        failed_asset_count=1,
    )
    index_job = MyPhotoJobModel(
        gallery_id=gallery.id,
        agency_id=gallery.agency_id,
        group_id=gallery.group_id,
        job_type="index_gallery",
        status="running",
        idempotency_key="index-revision-2",
        target_revision=2,
        max_attempts=5,
        processed_count=3,
        total_count=3,
        succeeded_count=2,
        failed_count=1,
        correlation_id="revision-correlation",
    )
    coverage = SimpleNamespace(one=lambda: (3, 2, 1))
    total = SimpleNamespace(scalar_one=lambda: 5_003)
    eligible = SimpleNamespace(scalar_one=lambda: 2)
    refresh_id = uuid.uuid4()

    def assign_refresh_id(job: MyPhotoJobModel) -> None:
        job.id = refresh_id

    session = SimpleNamespace(
        execute=AsyncMock(side_effect=(coverage, total, eligible)),
        add=MagicMock(side_effect=assign_refresh_id),
        flush=AsyncMock(),
    )
    published_at = datetime.now(tz=UTC)

    published_refresh_id = await publish_gallery_revision(
        session,  # type: ignore[arg-type]
        gallery=gallery,
        index_job=index_job,
        settings=SimpleNamespace(  # type: ignore[arg-type]
            my_photos=SimpleNamespace(consent_version="consent-v1", job_max_attempts=5)
        ),
        published_at=published_at,
    )

    assert published_refresh_id == refresh_id
    assert gallery.published_revision == 2
    assert gallery.face_index_version == 2
    assert gallery.status == "ready"
    assert gallery.total_asset_count == 5_003
    assert gallery.published_at == published_at
    refresh = session.add.call_args.args[0]
    assert refresh.id == published_refresh_id
    assert refresh.job_type == "refresh_searches"
    assert refresh.target_revision == 2
    assert refresh.total_count == 2
    assert refresh.idempotency_key == "gallery-revision:2"


@pytest.mark.asyncio
async def test_gallery_revision_rejects_incomplete_coverage_before_publication() -> None:
    gallery = SimpleNamespace(id=uuid.uuid4(), published_revision=1)
    index_job = SimpleNamespace(
        target_revision=2,
        total_count=3,
        succeeded_count=2,
        failed_count=0,
    )
    session = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(one=lambda: (3, 2, 1)))
    )

    with pytest.raises(ValueError, match="coverage is incomplete"):
        await publish_gallery_revision(
            session,  # type: ignore[arg-type]
            gallery=gallery,  # type: ignore[arg-type]
            index_job=index_job,  # type: ignore[arg-type]
            settings=SimpleNamespace(),  # type: ignore[arg-type]
            published_at=datetime.now(tz=UTC),
        )

    assert gallery.published_revision == 1


def test_heic_original_is_not_advertised_without_normalized_variant() -> None:
    delivery = object.__new__(MyPhotosDeliveryService)
    delivery._settings = SimpleNamespace(  # type: ignore[attr-defined]
        app_env="production",
        my_photos=SimpleNamespace(development_fixtures_enabled=False),
    )
    delivery._providers = SimpleNamespace(provider_name="disabled")  # type: ignore[attr-defined]
    gallery = SimpleNamespace(published_revision=1, provider_name="disabled")
    asset = MyPhotoMediaAssetModel(
        id=uuid.uuid4(),
        immutable_asset_key="heic-one",
        mime_type="image/heic",
        width=4_000,
        height=3_000,
        aspect_ratio=4 / 3,
        byte_size=1_000,
        checksum_sha256="a" * 64,
        processing_state="indexed",
        availability_state="original_available_online",
        sort_rank=1,
    )
    response = delivery.photo_response(
        gallery=gallery,  # type: ignore[arg-type]
        group_id=uuid.uuid4(),
        account_cache_scope="cache-scope-1",
        match=None,
        asset=asset,
        thumbnail_variant=None,
        preview_variant=None,
        optimized_variant=None,
    )
    assert response.download_qualities == []
    assert response.thumbnail_state == "registered"
    assert response.thumbnail.transport == "unavailable"


def test_optimized_download_is_advertised_only_for_persisted_usable_variant() -> None:
    delivery = object.__new__(MyPhotosDeliveryService)
    delivery._settings = SimpleNamespace(  # type: ignore[attr-defined]
        app_env="production",
        my_photos=SimpleNamespace(development_fixtures_enabled=False),
    )
    delivery._providers = SimpleNamespace(provider_name="disabled")  # type: ignore[attr-defined]
    gallery = SimpleNamespace(published_revision=1, provider_name="disabled")
    asset = MyPhotoMediaAssetModel(
        id=uuid.uuid4(),
        immutable_asset_key="jpeg-one",
        storage_reference="opaque/original/jpeg-one",
        original_filename="jpeg-one.jpg",
        mime_type="image/jpeg",
        width=4_000,
        height=3_000,
        aspect_ratio=4 / 3,
        byte_size=1_000,
        checksum_sha256="a" * 64,
        processing_state="indexed",
        availability_state="original_available_online",
        published_revision=1,
        sort_rank=1,
    )

    def response(variant: MyPhotoAssetVariantModel | None):  # type: ignore[no-untyped-def]
        return delivery.photo_response(
            gallery=gallery,  # type: ignore[arg-type]
            group_id=uuid.uuid4(),
            account_cache_scope="cache-scope-1",
            match=None,
            asset=asset,
            thumbnail_variant=None,
            preview_variant=None,
            optimized_variant=variant,
        )

    assert response(None).download_qualities == ["original"]
    base = MyPhotoAssetVariantModel(
        media_asset_id=asset.id,
        variant_kind="optimized",
        storage_reference=None,
        mime_type="image/jpeg",
        width=1_600,
        height=1_200,
        byte_size=600,
        checksum_sha256="b" * 64,
        availability_state="delivery_available",
        delivery_version=1,
    )
    assert response(base).download_qualities == ["original"]
    base.storage_reference = "opaque/optimized/jpeg-one"
    base.availability_state = "processing"
    assert response(base).download_qualities == ["original"]
    base.availability_state = "delivery_available"
    base.expires_at = datetime.now(tz=UTC) - timedelta(seconds=1)
    assert response(base).download_qualities == ["original"]
    base.expires_at = datetime.now(tz=UTC) + timedelta(minutes=5)
    assert response(base).download_qualities == ["original", "optimized"]


@pytest.mark.asyncio
async def test_download_plan_projects_mixed_online_preparing_failed_counts() -> None:
    delivery = object.__new__(MyPhotosDeliveryService)
    delivery._require_passenger = lambda claims, trip: SimpleNamespace(  # type: ignore[attr-defined]
        id=uuid.uuid4()
    )
    gallery = SimpleNamespace(id=uuid.uuid4(), published_revision=7)
    delivery._ready_gallery = AsyncMock(return_value=gallery)  # type: ignore[attr-defined]
    revision_result = SimpleNamespace(scalar_one=lambda: 7)
    aggregate_result = SimpleNamespace(one=lambda: (3, 300, 180, 2, 140, 80, 1, 2, 1))
    delivery._session = SimpleNamespace(  # type: ignore[attr-defined]
        execute=AsyncMock(side_effect=(revision_result, aggregate_result))
    )
    delivery._providers = SimpleNamespace(  # type: ignore[attr-defined]
        media=SimpleNamespace(ready=True)
    )
    claims = SimpleNamespace(agency_id=uuid.uuid4())
    trip = SimpleNamespace(group=SimpleNamespace(id=uuid.uuid4()))
    response = await delivery.download_plan(  # type: ignore[arg-type]
        claims=claims,
        trip=trip,
    )
    assert response.matched_item_count == 3
    assert response.downloadable_item_count == 1
    assert response.preparing_item_count == 1
    assert response.qualities[0].supported_item_count == 2
    assert response.qualities[1].supported_item_count == 2
