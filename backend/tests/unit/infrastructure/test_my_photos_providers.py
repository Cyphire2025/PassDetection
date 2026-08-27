from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.application.my_photos.errors import MyPhotosUnavailable
from app.application.my_photos.providers import (
    DeliveryRequest,
    FaceIndexAsset,
    FaceIndexBatchRequest,
    FaceSearchRequest,
    LivenessSessionRequest,
    MediaPreparationRequest,
    ReferenceDeletionRequest,
)
from app.core.config.settings import MyPhotosSettings
from app.infrastructure.my_photos.providers import (
    DevelopmentFaceSearchProvider,
    DevelopmentLivenessProvider,
    DevelopmentMediaDeliveryProvider,
    DisabledFaceSearchProvider,
    build_provider_bundle,
)
from app.infrastructure.my_photos.synthetic_media import synthetic_media_checksum


def _face_request(reference: str = "dev-reference:passenger-one") -> FaceSearchRequest:
    return FaceSearchRequest(
        tenant_scope="tenant-a",
        group_scope="group-a",
        collection_reference="dev-collection:group-a",
        reference_face_handle=reference,
        maximum_results=5_000,
    )


def test_development_provider_is_rejected_outside_local_development() -> None:
    config = MyPhotosSettings(
        liveness_provider="development",
        face_search_provider="development",
        media_provider="development",
    )
    with pytest.raises(RuntimeError, match="forbidden outside development"):
        build_provider_bundle(
            SimpleNamespace(app_env="production", my_photos=config)  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_disabled_face_provider_fails_closed() -> None:
    with pytest.raises(MyPhotosUnavailable) as captured:
        await DisabledFaceSearchProvider().search(_face_request())
    assert captured.value.code == "MY_PHOTOS_PROVIDER_NOT_CONFIGURED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scenario", "outcome", "error_code"),
    [
        ("no_face", "no_face", "NO_FACE"),
        ("multiple_faces", "multiple_faces", "MULTIPLE_FACES"),
        ("rejected", "rejected", "LIVENESS_REJECTED"),
        ("expired", "expired", "SESSION_EXPIRED"),
    ],
)
async def test_liveness_simulator_has_distinct_bounded_outcomes(
    scenario: str, outcome: str, error_code: str
) -> None:
    provider = DevelopmentLivenessProvider(
        scenario=scenario,  # type: ignore[arg-type]
        app_env="development",
    )
    expires_at = datetime.now(tz=UTC) + timedelta(minutes=2)
    request = LivenessSessionRequest(
        session_identity="session-one",
        tenant_scope="tenant-a",
        group_scope="group-a",
        passenger_scope="passenger-a",
        challenge_mode="movement_only",
        expires_at=expires_at,
        audit_image_retention_enabled=False,
        reference_frame_retention_seconds=0,
    )
    first = await provider.create_session(request)
    second = await provider.create_session(request)
    assert first == second
    result = await provider.get_result(first.provider_reference)
    assert result.outcome == outcome
    assert result.stable_error_code == error_code
    assert result.reference_face_handle is None


@pytest.mark.asyncio
async def test_successful_liveness_reference_supports_idempotent_deletion() -> None:
    provider = DevelopmentLivenessProvider(scenario="success", app_env="development")
    request = LivenessSessionRequest(
        session_identity="session-one",
        tenant_scope="tenant-a",
        group_scope="group-a",
        passenger_scope="passenger-a",
        challenge_mode="movement_and_light",
        expires_at=datetime.now(tz=UTC) + timedelta(minutes=2),
    )
    handle = await provider.create_session(request)
    result = await provider.get_result(handle.provider_reference)
    assert result.outcome == "passed"
    assert result.reference_face_handle is not None
    deletion = ReferenceDeletionRequest(
        tenant_scope="tenant-a",
        group_scope="group-a",
        passenger_scope="passenger-a",
        provider_reference=result.reference_face_handle,
        deletion_identity="delete-one",
    )
    assert (await provider.delete_reference(deletion)).outcome == "deleted"
    assert (await provider.delete_reference(deletion)).outcome == "deleted"


@pytest.mark.asyncio
async def test_five_thousand_asset_index_and_late_search_use_one_contract() -> None:
    provider = DevelopmentFaceSearchProvider(scenario="success", app_env="development")
    indexed_references: set[str] = set()
    occurrence_count = 0
    for start in range(0, 5_000, 500):
        assets = tuple(
            FaceIndexAsset(
                asset_identity=f"dev-asset-{index:05d}",
                analysis_media_reference=f"analysis:{index}",
                idempotency_identity=f"index-v1:{index}",
            )
            for index in range(start, start + 500)
        )
        result = await provider.index_faces(
            FaceIndexBatchRequest(
                tenant_scope="tenant-a",
                group_scope="group-a",
                collection_reference="dev-collection:group-a",
                index_version=1,
                assets=assets,
            )
        )
        assert not result.failures
        assert len(result.occurrences) <= 600
        occurrence_count += len(result.occurrences)
        indexed_references.update(
            occurrence.provider_face_reference for occurrence in result.occurrences
        )

    assert occurrence_count == 6_000
    assert "dev-face-00000-primary" in indexed_references
    assert "dev-face-00000-secondary" in indexed_references

    # Late enrollment searches the already-indexed collection. It never sends
    # original assets or an eager 5,000-row payload through this contract.
    passenger_one = await provider.search(_face_request("dev-reference:passenger-one"))
    passenger_two = await provider.search(_face_request("dev-reference:passenger-two"))
    assert len(passenger_one.matches) == 57
    assert len(passenger_two.matches) == 57
    assert all(
        match.provider_face_reference in indexed_references
        for match in passenger_one.matches + passenger_two.matches
    )
    assert passenger_one.matches[0].provider_face_reference == "dev-face-00000-primary"
    assert passenger_two.matches[0].provider_face_reference == "dev-face-00000-secondary"
    assert {
        passenger_one.matches[0].provider_face_reference,
        passenger_two.matches[0].provider_face_reference,
    } == {"dev-face-00000-primary", "dev-face-00000-secondary"}
    assert any(match.similarity >= 92.0 for match in passenger_one.matches)
    assert any(80.0 <= match.similarity < 92.0 for match in passenger_one.matches)


@pytest.mark.asyncio
async def test_face_search_scenarios_are_deterministic_and_bounded() -> None:
    no_matches = DevelopmentFaceSearchProvider(scenario="no_matches", app_env="development")
    partial = DevelopmentFaceSearchProvider(scenario="partial_matches", app_env="development")
    assert (await no_matches.search(_face_request())).matches == ()
    assert len((await partial.search(_face_request())).matches) == 12

    throttled = DevelopmentFaceSearchProvider(scenario="throttled", app_env="development")
    with pytest.raises(MyPhotosUnavailable) as captured:
        await throttled.search(_face_request())
    assert captured.value.code == "MY_PHOTOS_PROVIDER_THROTTLED"


@pytest.mark.asyncio
async def test_development_media_distinguishes_offline_and_delivery_available() -> None:
    provider = DevelopmentMediaDeliveryProvider(app_env="development", ttl_seconds=300)
    offline = await provider.authorize(
        DeliveryRequest(
            tenant_scope="tenant-a",
            group_scope="group-a",
            passenger_scope="passenger-a",
            authorization_identity="authorization-one:1",
            asset_identity="dev-asset-00017",
            media_reference="development/group-a/dev-asset-00017/original",
            quality="original",
            availability_state="archived_offline",
            expected_size_bytes=100,
            checksum_sha256="0" * 64,
            content_type="image/png",
        )
    )
    assert offline.state == "preparing_delivery"
    assert offline.provider_authorization_reference is None

    expected_size, expected_checksum = synthetic_media_checksum("dev-asset-00001", "optimized")
    available_request = DeliveryRequest(
        tenant_scope="tenant-a",
        group_scope="group-a",
        passenger_scope="passenger-a",
        authorization_identity="authorization-two:1",
        asset_identity="dev-asset-00001",
        media_reference="development/group-a/dev-asset-00001/optimized",
        quality="optimized",
        availability_state="delivery_available",
        expected_size_bytes=expected_size,
        checksum_sha256=expected_checksum,
        content_type="image/png",
    )
    first = await provider.authorize(available_request)
    second = await provider.authorize(available_request)
    assert first.provider_authorization_reference == second.provider_authorization_reference
    assert first.expected_size_bytes == expected_size
    assert first.checksum_sha256 == expected_checksum
    assert first.supports_ranges is True

    preparation = await provider.prepare(
        MediaPreparationRequest(
            tenant_scope="tenant-a",
            group_scope="group-a",
            asset_identity="dev-asset-00017",
            variant="original",
            idempotency_identity="prepare-one",
        )
    )
    assert preparation.state in {"delivery_available", "rehydration_requested"}
