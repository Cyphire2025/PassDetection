"""A real minimum-size fanout batch resumes without duplicating prior searches."""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import func, select

from app.infrastructure.database.gc_mobile_models import MobilePassengerIdentityModel
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.database.my_photos_models import (
    MyPhotoEnrollmentModel,
    MyPhotoJobModel,
    MyPhotoSearchRunModel,
)
from app.infrastructure.my_photos import revision_runtime
from tests.integration.test_my_photos_provider_claim_freshness import (
    photo_database as photo_database,
)
from tests.integration.test_my_photos_refresh_authority import _refresh_job
from tests.integration.test_my_photos_search_failure_authority import _queued_search


async def test_refresh_resumes_real_ten_row_batch_and_reuses_existing_identity(
    photo_database, monkeypatch
):
    env = photo_database
    existing_search_id, _existing_job_id = await _queued_search(env)
    job_id = await _refresh_job(env, condition="current", enrolled=True)
    now = datetime.now(UTC)
    identity = env.passenger.identity
    async with env.sessions() as session, session.begin():
        current = await session.scalar(select(MyPhotoEnrollmentModel))
        current.enrolled_at = now - timedelta(days=1)
        current.consented_at = now - timedelta(days=2)
        submissions = [
            PassportSubmissionModel(
                id=uuid.uuid4(),
                agency_id=identity.agency_id,
                group_id=identity.group_id,
                client_name=f"Synthetic refresh {index}",
                client_phone=f"+91997788{index:04d}",
                client_reviewed_at=now,
                image_s3_key=f"synthetic-refresh/{index}.jpg",
                acquisition_mode="file",
                status="staff_approved",
            )
            for index in range(10)
        ]
        session.add_all(submissions)
        await session.flush()
        passengers = [
            MobilePassengerIdentityModel(
                id=uuid.uuid4(),
                agency_id=identity.agency_id,
                group_id=identity.group_id,
                gc_group_access_id=identity.gc_group_access_id,
                passenger_submission_id=row.id,
                normalized_phone_number=row.client_phone,
                phone_lookup_hash=hashlib.sha256(row.id.bytes).hexdigest(),
                status="eligible",
            )
            for row in submissions
        ]
        session.add_all(passengers)
        await session.flush()
        session.add_all(
            [
                MyPhotoEnrollmentModel(
                    id=uuid.uuid4(),
                    passenger_identity_id=passenger.id,
                    passenger_submission_id=passenger.passenger_submission_id,
                    gc_group_access_id=identity.gc_group_access_id,
                    agency_id=identity.agency_id,
                    group_id=identity.group_id,
                    consent_version=env.settings.my_photos.consent_version,
                    consented_at=now - timedelta(days=2),
                    consent_idempotency_key=f"synthetic-refresh-{index}",
                    status="enrolled",
                    reference_version=1,
                    provider_name="development",
                    provider_reference_handle=f"synthetic-reference-{index}",
                    enrolled_at=now - timedelta(days=1),
                )
                for index, passenger in enumerate(passengers)
            ]
        )
        job = await session.get(MyPhotoJobModel, job_id)
        job.total_count = 11
    # Ten is the real settings minimum; no bypass of admission/configuration limits.
    settings = SimpleNamespace(
        my_photos=env.settings.my_photos.model_copy(update={"job_batch_size": 10})
    )
    monkeypatch.setattr(revision_runtime, "AsyncSessionFactory", env.sessions)
    first = await revision_runtime.execute_refresh_fanout(
        job_id=job_id, lease_owner="synthetic-worker", settings=settings
    )
    assert first.state == "continuing"
    async with env.sessions() as session, session.begin():
        job = await session.get(MyPhotoJobModel, job_id)
        assert job.processed_count == 10 and job.status == "retrying"
        assert job.checkpoint_cursor and job.lease_owner is None and job.lease_expires_at is None
        job.status = "running"
        job.lease_owner = "synthetic-worker"
        job.lease_expires_at = datetime.now(UTC) + timedelta(seconds=30)
    second = await revision_runtime.execute_refresh_fanout(
        job_id=job_id, lease_owner="synthetic-worker", settings=settings
    )
    assert second.state == "succeeded"
    created = (*first.search_run_ids, *second.search_run_ids)
    assert len(created) == len(set(created)) == 10
    assert existing_search_id not in created
    async with env.sessions() as session:
        job = await session.get(MyPhotoJobModel, job_id)
        assert job.processed_count == job.succeeded_count == job.total_count == 11
        assert await session.scalar(select(func.count(MyPhotoSearchRunModel.id))) == 11
        assert await session.scalar(select(func.count(MyPhotoJobModel.id))) == 12
    replay = await revision_runtime.execute_refresh_fanout(
        job_id=job_id, lease_owner="synthetic-worker", settings=settings
    )
    assert replay.state == "lease_lost" and replay.search_run_ids == ()
