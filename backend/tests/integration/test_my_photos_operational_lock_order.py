"""Admission locks gallery before job, matching cancellation and result publication."""

from types import SimpleNamespace

import pytest
from sqlalchemy import delete
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.my_photos.providers import MediaAvailabilityResult
from app.infrastructure.database.my_photos_models import MyPhotoGalleryModel, MyPhotoJobModel
from app.infrastructure.my_photos import operational_runtime
from tests.integration.my_photos_operational_fixtures import operational_media_scope


@pytest.mark.parametrize("condition", ["queued", "exhausted", "disabled"])
async def test_claim_and_terminalization_follow_gallery_job_asset_lock_order(
    db_session, monkeypatch, condition
):
    scope = await operational_media_scope(db_session, monkeypatch)
    async with scope.sessions() as session, session.begin():
        if condition == "disabled":
            gallery = await session.get(MyPhotoGalleryModel, scope.gallery_id)
            gallery.feature_enabled = False
        elif condition == "exhausted":
            job = await session.get(MyPhotoJobModel, scope.job_id)
            job.attempt_count = job.max_attempts
    lock_statements = []
    provider_called = False

    class RecordingSession(AsyncSession):
        async def execute(self, statement, *args, **kwargs):
            if not provider_called and getattr(statement, "_for_update_arg", None) is not None:
                lock_statements.append(
                    (
                        statement.column_descriptions[0]["entity"].__tablename__,
                        str(statement.compile(dialect=postgresql.dialect())),
                    )
                )
            return await super().execute(statement, *args, **kwargs)

    sessions = async_sessionmaker(db_session.bind, class_=RecordingSession, expire_on_commit=False)
    monkeypatch.setattr(operational_runtime, "AsyncSessionFactory", sessions)

    class Media:
        async def prepare(self, _request):
            nonlocal provider_called
            provider_called = True
            return MediaAvailabilityResult(
                state="delivery_available",
                byte_size=1234,
                checksum_sha256="a" * 64,
                delivery_version=2,
                storage_reference="synthetic-private-preview",
                content_type="image/jpeg",
                width=640,
                height=480,
            )

    result = await operational_runtime.execute_operational_job(
        scope.job_id,
        settings=scope.settings,
        providers=SimpleNamespace(media=Media()),
        lease_owner="synthetic-admission-worker",
    )
    assert result.state == ("succeeded" if condition == "queued" else "failed")
    assert provider_called is (condition == "queued")
    assert [table for table, _sql in lock_statements[:2]] == ["my_photo_galleries", "my_photo_jobs"]
    if condition != "queued":
        assert lock_statements[2][0] == "my_photo_media_assets"
    assert all("FOR UPDATE" in sql for _table, sql in lock_statements)


@pytest.mark.parametrize("deleted", ["job", "gallery"])
async def test_claim_rechecks_scope_after_unlocked_locator_read(db_session, monkeypatch, deleted):
    scope = await operational_media_scope(db_session, monkeypatch)
    removed = False

    class DeleteAfterLocatorSession(AsyncSession):
        async def execute(self, statement, *args, **kwargs):
            nonlocal removed
            result = await super().execute(statement, *args, **kwargs)
            if (
                not removed
                and getattr(statement, "_for_update_arg", None) is None
                and statement.column_descriptions[0].get("name") == "gallery_id"
            ):
                removed = True
                async with scope.sessions() as other, other.begin():
                    model = MyPhotoJobModel if deleted == "job" else MyPhotoGalleryModel
                    target = scope.job_id if deleted == "job" else scope.gallery_id
                    await other.execute(delete(model).where(model.id == target))
            return result

    monkeypatch.setattr(
        operational_runtime,
        "AsyncSessionFactory",
        async_sessionmaker(
            db_session.bind, class_=DeleteAfterLocatorSession, expire_on_commit=False
        ),
    )

    class Media:
        async def prepare(self, _request):
            raise AssertionError("A deleted claim or gallery must not reach a provider")

    result = await operational_runtime.execute_operational_job(
        scope.job_id,
        settings=scope.settings,
        providers=SimpleNamespace(media=Media()),
        lease_owner="synthetic-racing-worker",
    )
    assert removed
    assert result.state == "noop"
