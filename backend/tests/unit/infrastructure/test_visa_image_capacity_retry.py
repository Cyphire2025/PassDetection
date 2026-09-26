"""Transient native admission preserves the real durable row and attempt budget."""

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.domain.exceptions.resource_capacity import ImageProcessingBusy
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    PassportSubmissionModel,
    PassportVisaAiImageJobModel,
)
from app.infrastructure.repositories.passport_visa_ai_image_job_repository import (
    PassportVisaAiImageJobRepository,
)
from app.infrastructure.visa_ai_image_jobs import runtime
from tests.persistence import persist_graph


async def test_repeated_capacity_pressure_never_terminally_fails_accepted_visa_work(db_session, monkeypatch):
    agency = AgencyModel(id=uuid.uuid4(), name="Synthetic", email="capacity@example.test")
    group = ClientGroupModel(id=uuid.uuid4(), agency_id=agency.id, name="Synthetic", token=uuid.uuid4().hex)
    submission = PassportSubmissionModel(id=uuid.uuid4(), agency_id=agency.id, group_id=group.id,
        client_name="Synthetic", image_s3_key="front", passport_photo_s3_key="visa")
    job = PassportVisaAiImageJobModel(id=uuid.uuid4(), submission_id=submission.id,
        original_source_storage_key="visa", input_storage_key="visa", prompt="Synthetic",
        prompt_sha256="a" * 64, status="queued", attempts=0, max_attempts=1)
    await persist_graph(db_session, [agency, group, submission, job])
    await db_session.commit()

    @asynccontextmanager
    async def session_factory():
        yield db_session

    monkeypatch.setattr(runtime, "AsyncSessionFactory", session_factory)
    storage = SimpleNamespace(get_file=AsyncMock(return_value=b"synthetic"), upload_file=AsyncMock(), delete_files=AsyncMock())
    monkeypatch.setattr(runtime, "MinioStorageRepository", Mock(return_value=storage))
    service = SimpleNamespace(edit=AsyncMock(side_effect=ImageProcessingBusy()))
    monkeypatch.setattr(runtime, "GeminiVisaImageEditService", Mock(return_value=service))
    for _ in range(4):
        with pytest.raises(runtime.VisaAiImageJobRetryRequested):
            await runtime.run_visa_ai_image_job(job_id=str(job.id), submission_id=str(submission.id))
        await db_session.refresh(job)
        assert job.status == "queued" and job.attempts == 0
        assert job.error_code == "image_processing_busy" and job.finished_at is None
        assert job.celery_task_id is None
    storage.upload_file.assert_not_awaited()
    storage.delete_files.assert_not_awaited()
    # A completed row must never be reset by a late capacity notification.
    job.status = "succeeded"
    await db_session.commit()
    assert not await PassportVisaAiImageJobRepository(db_session).defer_capacity(job.id, message="late")
    assert job.status == "succeeded"
