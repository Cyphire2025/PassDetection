"""Provider errors have no authority to mutate a stale operation claim."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import update

from app.application.my_photos.errors import MyPhotosUnavailable
from app.infrastructure.database.my_photos_models import (
    MyPhotoGalleryModel,
    MyPhotoJobModel,
    MyPhotoMediaAssetModel,
)
from app.infrastructure.my_photos import operational_runtime
from tests.integration.my_photos_operational_fixtures import operational_media_scope


@pytest.mark.parametrize("error_kind", ["unavailable", "invalid"])
@pytest.mark.parametrize(
    "change", [None, "expired", "cancelled", "disabled", "removed", "reassigned"]
)
async def test_provider_failure_cannot_change_stale_job_or_asset(
    db_session, monkeypatch, error_kind, change
):
    scope = await operational_media_scope(db_session, monkeypatch)

    class Media:
        async def prepare(self, _request):
            async with scope.sessions() as session, session.begin():
                if change == "disabled":
                    await session.execute(
                        update(MyPhotoGalleryModel)
                        .where(MyPhotoGalleryModel.id == scope.gallery_id)
                        .values(feature_enabled=False)
                    )
                elif change == "removed":
                    await session.execute(
                        update(MyPhotoMediaAssetModel)
                        .where(MyPhotoMediaAssetModel.id == scope.asset_id)
                        .values(processing_state="removed", availability_state="removed")
                    )
                elif change is not None:
                    values = {
                        "expired": {"lease_expires_at": datetime.now(UTC) - timedelta(seconds=1)},
                        "cancelled": {"cancellation_requested_at": datetime.now(UTC)},
                        "reassigned": {"lease_owner": "synthetic-new-worker"},
                    }[change]
                    await session.execute(
                        update(MyPhotoJobModel)
                        .where(MyPhotoJobModel.id == scope.job_id)
                        .values(**values)
                    )
            if error_kind == "invalid":
                raise ValueError("synthetic invalid provider response")
            raise MyPhotosUnavailable("MY_PHOTOS_PROVIDER_UNAVAILABLE", "Synthetic failure.")

    result = await operational_runtime.execute_operational_job(
        scope.job_id,
        settings=scope.settings,
        providers=SimpleNamespace(media=Media()),
        lease_owner="synthetic-first-worker",
    )
    async with scope.sessions() as session:
        job = await session.get(MyPhotoJobModel, scope.job_id)
        asset = await session.get(MyPhotoMediaAssetModel, scope.asset_id)
        if change is not None:
            assert result.state == "lease_lost"
            assert job.status == "running"
            assert job.attempt_count == 0
            assert job.stable_error_code is None
            assert job.next_attempt_at is None
            if change == "removed":
                assert asset.processing_state == asset.availability_state == "removed"
            else:
                assert asset.availability_state != "failed"
        elif error_kind == "invalid":
            assert result.state == job.status == "failed"
            assert job.stable_error_code == "MEDIA_PROVIDER_RESULT_INVALID"
            assert asset.availability_state == "failed"
        else:
            assert result.state == job.status == "retrying"
            assert job.attempt_count == 1
            assert job.next_attempt_at is not None
            assert job.lease_owner is None
            assert result.retry_after_seconds >= 1
