"""Original durable operation dispatch and media availability behavior remain intact."""

from types import SimpleNamespace

import pytest

from app.application.my_photos.errors import MyPhotosUnavailable
from app.application.my_photos.providers import MediaAvailabilityResult
from app.infrastructure.database.my_photos_models import MyPhotoJobModel, MyPhotoMediaAssetModel
from app.infrastructure.my_photos import operational_runtime
from tests.integration.my_photos_operational_fixtures import operational_media_scope


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("continuing", "retrying"),
        ("succeeded", "succeeded"),
        ("invalid", "failed"),
        ("unavailable", "retrying"),
    ],
)
async def test_refresh_dispatch_preserves_checkpoint_errors_and_result_contract(
    db_session, monkeypatch, state, expected
):
    scope = await operational_media_scope(db_session, monkeypatch)
    async with scope.sessions() as session, session.begin():
        job = await session.get(MyPhotoJobModel, scope.job_id)
        job.job_type, job.media_asset_id, job.target_revision = "refresh_searches", None, 1
    calls = []

    async def refresh(**kwargs):
        calls.append(kwargs)
        if state == "invalid":
            raise ValueError("Synthetic invalid checkpoint")
        if state == "unavailable":
            raise MyPhotosUnavailable("SYNTHETIC_UNAVAILABLE", "Synthetic failure.")
        return SimpleNamespace(state=state, search_run_ids=())

    monkeypatch.setattr(operational_runtime, "execute_refresh_fanout", refresh)
    result = await operational_runtime.execute_operational_job(
        scope.job_id,
        settings=scope.settings,
        providers=SimpleNamespace(),
        lease_owner="synthetic-refresh-worker",
    )
    assert result.state == expected
    assert len(calls) == 1 and calls[0]["job_id"] == scope.job_id
    assert calls[0]["lease_owner"] == "synthetic-refresh-worker"
    assert result.search_run_ids == ()


@pytest.mark.parametrize("outcome", ["preparing", "original", "changed_integrity", "unexpected"])
async def test_media_delivery_states_preserve_retry_and_integrity_boundaries(
    db_session, monkeypatch, outcome
):
    scope = await operational_media_scope(db_session, monkeypatch)
    if outcome in {"original", "changed_integrity"}:
        async with scope.sessions() as session, session.begin():
            job = await session.get(MyPhotoJobModel, scope.job_id)
            job.checkpoint_cursor = "original"

    class Media:
        async def prepare(self, _request):
            if outcome == "unexpected":
                raise RuntimeError("Synthetic private provider details")
            if outcome == "preparing":
                return MediaAvailabilityResult(
                    state="preparing_delivery",
                    byte_size=None,
                    checksum_sha256=None,
                    delivery_version=1,
                )
            return MediaAvailabilityResult(
                state="delivery_available",
                byte_size=100000,
                checksum_sha256=f"{100 if outcome == 'original' else 101:064x}",
                delivery_version=1,
                storage_reference="synthetic-original-reference",
                content_type="image/jpeg",
                width=1920,
                height=1080,
            )

    result = await operational_runtime.execute_operational_job(
        scope.job_id,
        settings=scope.settings,
        providers=SimpleNamespace(media=Media()),
        lease_owner="synthetic-media-worker",
    )
    async with scope.sessions() as session:
        job = await session.get(MyPhotoJobModel, scope.job_id)
        asset = await session.get(MyPhotoMediaAssetModel, scope.asset_id)
        if outcome == "original":
            assert result.state == job.status == "succeeded"
            assert asset.storage_reference == "synthetic-original-reference"
        elif outcome == "changed_integrity":
            assert result.state == job.status == "failed"
            assert job.stable_error_code == "MEDIA_INTEGRITY_CHANGED"
        else:
            assert result.state == job.status == "retrying"
            assert job.attempt_count == (0 if outcome == "preparing" else 1)
            assert "private provider details" not in (job.error_detail or "")
