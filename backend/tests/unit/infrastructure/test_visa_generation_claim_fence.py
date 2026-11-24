"""An expired Visa generation may not publish or mutate a newer attempt."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import func, select

from app.domain.exceptions.resource_capacity import ImageProcessingBusy
from app.infrastructure.ai.gemini_visa_image_edit_service import (
    GeminiVisaImageEditNotConfigured,
    GeminiVisaImageEditProviderUnavailable,
    GeminiVisaImageEditResult,
)
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    PassportSubmissionModel,
    PassportVisaAiImageJobModel,
    PassportVisaAiImageModel,
    StorageCleanupJobModel,
)
from app.infrastructure.documents.storage_cleanup import StorageCleanupCipher
from app.infrastructure.repositories.passport_visa_ai_image_job_repository import (
    PassportVisaAiImageJobRepository,
)
from app.infrastructure.visa_ai_image_jobs import runtime
from tests.persistence import persist_graph


@pytest.fixture
async def generation(db_session, monkeypatch):
    agency_id, group_id, submission_id, job_id = (uuid.uuid4() for _ in range(4))
    await persist_graph(
        db_session,
        [
            AgencyModel(id=agency_id, name="Synthetic", email="synthetic@example.invalid"),
            ClientGroupModel(
                id=group_id, agency_id=agency_id, name="Synthetic", token=uuid.uuid4().hex
            ),
            PassportSubmissionModel(
                id=submission_id,
                agency_id=agency_id,
                group_id=group_id,
                client_name="Synthetic",
                image_s3_key="front",
                passport_photo_s3_key="visa",
            ),
            PassportVisaAiImageJobModel(
                id=job_id,
                submission_id=submission_id,
                original_source_storage_key="visa",
                input_storage_key="visa",
                prompt="White background",
                prompt_sha256="a" * 64,
                status="queued",
                attempts=0,
                max_attempts=3,
            ),
        ],
    )
    await db_session.commit()

    @asynccontextmanager
    async def factory():
        try:
            yield db_session
        finally:
            if db_session.in_transaction():
                await db_session.rollback()

    async def newer_claim():
        row = await db_session.get(PassportVisaAiImageJobModel, job_id)
        row.status = "queued"
        await db_session.flush()
        job, claimed = await PassportVisaAiImageJobRepository(db_session).claim_running(job_id)
        assert claimed and job is not None and job.attempts == 2
        await db_session.commit()

    storage = SimpleNamespace(
        get_file=AsyncMock(return_value=b"synthetic"),
        upload_file=AsyncMock(),
        delete_files=AsyncMock(),
    )
    service = SimpleNamespace(edit=AsyncMock())
    monkeypatch.setattr(runtime, "AsyncSessionFactory", factory)
    monkeypatch.setattr(runtime, "MinioStorageRepository", Mock(return_value=storage))
    monkeypatch.setattr(runtime, "GeminiVisaImageEditService", Mock(return_value=service))
    return SimpleNamespace(
        job_id=job_id,
        submission_id=submission_id,
        storage=storage,
        service=service,
        newer_claim=newer_claim,
        winner_key=f"passport-ai-library/{agency_id}/{submission_id}/visa_photo/{job_id.hex}.jpg",
    )


def _result():
    return GeminiVisaImageEditResult(
        content=b"synthetic-result",
        content_type="image/jpeg",
        prompt_sha256="a" * 64,
        model="synthetic",
    )


async def _assert_newer_attempt_untouched(session, identifier):
    row = await session.get(PassportVisaAiImageJobModel, identifier)
    assert row.status == "running" and row.attempts == 2
    assert row.result_image_id is None and row.error_code is None
    assert await session.scalar(select(func.count()).select_from(PassportVisaAiImageModel)) == 0


async def test_old_provider_result_cannot_upload_after_recovery(db_session, generation):
    async def edit(*args, **kwargs):
        await generation.newer_claim()
        return _result()

    generation.service.edit.side_effect = edit
    await runtime.run_visa_ai_image_job(
        job_id=str(generation.job_id), submission_id=str(generation.submission_id)
    )
    generation.storage.upload_file.assert_not_awaited()
    generation.storage.delete_files.assert_not_awaited()
    await _assert_newer_attempt_untouched(db_session, generation.job_id)


async def test_recovery_during_upload_cleans_only_the_old_attempt_artifact(db_session, generation):
    generation.service.edit.return_value = _result()

    async def upload(*args, **kwargs):
        await generation.newer_claim()

    generation.storage.upload_file.side_effect = upload
    await runtime.run_visa_ai_image_job(
        job_id=str(generation.job_id), submission_id=str(generation.submission_id)
    )
    key = generation.storage.upload_file.await_args.args[1]
    assert key != generation.winner_key
    generation.storage.delete_files.assert_awaited_once_with([key])
    await _assert_newer_attempt_untouched(db_session, generation.job_id)


async def test_committed_generation_survives_a_completion_logging_failure(
    db_session, generation, monkeypatch
):
    generation.service.edit.return_value = _result()
    monkeypatch.setattr(
        runtime.logger, "info", Mock(side_effect=RuntimeError("synthetic log sink"))
    )
    await runtime.run_visa_ai_image_job(
        job_id=str(generation.job_id),
        submission_id=str(generation.submission_id),
    )
    row = await db_session.get(PassportVisaAiImageJobModel, generation.job_id)
    assert row.status == "succeeded" and row.result_image_id is not None
    generation.storage.upload_file.assert_awaited_once()
    generation.storage.delete_files.assert_not_awaited()


async def test_upload_has_encrypted_cleanup_intent_cancelled_by_publication(db_session, generation):
    generation.service.edit.return_value = _result()

    async def upload(content, key, content_type):
        marker = await db_session.scalar(select(StorageCleanupJobModel))
        assert marker is not None and marker.source == "passport_ai_generation_compensation"
        assert marker.next_attempt_at.replace(tzinfo=UTC) > datetime.now(tz=UTC)
        assert key.encode() not in marker.storage_keys_ciphertext
        assert StorageCleanupCipher.from_settings().decrypt(
            marker.storage_keys_ciphertext, key_version=marker.encryption_key_version
        ) == (key,)
        await db_session.rollback()

    generation.storage.upload_file.side_effect = upload
    await runtime.run_visa_ai_image_job(
        job_id=str(generation.job_id), submission_id=str(generation.submission_id)
    )
    row = await db_session.get(PassportVisaAiImageJobModel, generation.job_id)
    assert row.status == "succeeded"
    assert await db_session.scalar(select(func.count()).select_from(StorageCleanupJobModel)) == 0
    generation.storage.delete_files.assert_not_awaited()


async def test_failed_compensation_retains_durable_encrypted_cleanup_intent(db_session, generation):
    generation.service.edit.return_value = _result()
    generation.storage.upload_file.side_effect = RuntimeError("Synthetic interrupted upload")
    generation.storage.delete_files.side_effect = RuntimeError("Synthetic unavailable storage")
    with pytest.raises(runtime.VisaAiImageJobRetryRequested):
        await runtime.run_visa_ai_image_job(
            job_id=str(generation.job_id), submission_id=str(generation.submission_id)
        )
    marker = await db_session.scalar(select(StorageCleanupJobModel))
    assert marker is not None and marker.status == "pending"
    key = generation.storage.upload_file.await_args.args[1]
    assert StorageCleanupCipher.from_settings().decrypt(
        marker.storage_keys_ciphertext, key_version=marker.encryption_key_version
    ) == (key,)
    row = await db_session.get(PassportVisaAiImageJobModel, generation.job_id)
    assert row.status == "queued" and row.attempts == 1


async def test_cancelled_compensation_cannot_delete_committed_artifact(db_session, generation):
    await runtime._delete_generated_best_effort(
        generation.storage,
        generation.winner_key,
        compensation_job_id=uuid.uuid4(),
    )
    generation.storage.delete_files.assert_not_awaited()


@pytest.mark.parametrize(
    "error",
    [
        GeminiVisaImageEditProviderUnavailable("Synthetic unavailable"),
        GeminiVisaImageEditNotConfigured("Synthetic rejected"),
        ImageProcessingBusy(),
    ],
)
async def test_old_failure_cannot_fail_requeue_or_refund_a_newer_attempt(
    db_session, generation, error
):
    async def edit(*args, **kwargs):
        await generation.newer_claim()
        raise error

    generation.service.edit.side_effect = edit
    await runtime.run_visa_ai_image_job(
        job_id=str(generation.job_id), submission_id=str(generation.submission_id)
    )
    await _assert_newer_attempt_untouched(db_session, generation.job_id)
