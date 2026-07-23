"""Persistence and claim semantics for Visa-photo AI generation jobs."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.domain.value_objects.passport_visa_ai_image_job import (
    PassportVisaAiImageJob,
)
from app.infrastructure.database.models import PassportVisaAiImageJobModel


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class PassportVisaAiImageJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_value(model: PassportVisaAiImageJobModel) -> PassportVisaAiImageJob:
        return PassportVisaAiImageJob(
            id=model.id,
            submission_id=model.submission_id,
            original_source_storage_key=model.original_source_storage_key,
            input_storage_key=model.input_storage_key,
            prompt=model.prompt,
            prompt_sha256=model.prompt_sha256,
            requested_by_user_id=model.requested_by_user_id,
            status=model.status,  # type: ignore[arg-type]
            attempts=model.attempts,
            max_attempts=model.max_attempts,
            celery_task_id=model.celery_task_id,
            result_image_id=model.result_image_id,
            error_code=model.error_code,
            error_message=model.error_message,
            started_at=model.started_at,
            finished_at=model.finished_at,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    async def enqueue(
        self,
        *,
        submission_id: uuid.UUID,
        original_source_storage_key: str,
        input_storage_key: str,
        prompt: str,
        requested_by_user_id: uuid.UUID,
    ) -> tuple[PassportVisaAiImageJob, bool]:
        active = await self.active_for_submission(submission_id)
        if active:
            return active, False

        now = _utcnow()
        row = PassportVisaAiImageJobModel(
            id=uuid.uuid4(),
            submission_id=submission_id,
            original_source_storage_key=original_source_storage_key,
            input_storage_key=input_storage_key,
            prompt=prompt,
            prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            requested_by_user_id=requested_by_user_id,
            status="queued",
            attempts=0,
            max_attempts=get_settings().gemini_image_edit_job_max_attempts,
            created_at=now,
            updated_at=now,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(row)
                await self._session.flush()
        except IntegrityError:
            active = await self.active_for_submission(submission_id)
            if active is None:
                raise
            return active, False
        return self._to_value(row), True

    async def get_for_submission(
        self,
        submission_id: uuid.UUID,
        job_id: uuid.UUID,
    ) -> PassportVisaAiImageJob | None:
        result = await self._session.execute(
            select(PassportVisaAiImageJobModel).where(
                PassportVisaAiImageJobModel.id == job_id,
                PassportVisaAiImageJobModel.submission_id == submission_id,
            )
        )
        row = result.scalar_one_or_none()
        return self._to_value(row) if row else None

    async def active_for_submission(
        self,
        submission_id: uuid.UUID,
    ) -> PassportVisaAiImageJob | None:
        result = await self._session.execute(
            select(PassportVisaAiImageJobModel)
            .where(
                PassportVisaAiImageJobModel.submission_id == submission_id,
                PassportVisaAiImageJobModel.status.in_(("queued", "running")),
            )
            .order_by(PassportVisaAiImageJobModel.created_at.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return self._to_value(row) if row else None

    async def claim_running(
        self,
        job_id: uuid.UUID,
    ) -> tuple[PassportVisaAiImageJob | None, bool]:
        row = await self._locked(job_id)
        if row is None:
            return None, False
        if row.status in {"succeeded", "failed", "running"}:
            return self._to_value(row), False
        if row.attempts >= row.max_attempts:
            self._set_failed(
                row,
                error_code="attempt_limit_reached",
                error_message="Visa AI generation could not be completed after bounded retries.",
            )
            await self._session.flush()
            return self._to_value(row), False

        now = _utcnow()
        row.status = "running"
        row.attempts += 1
        row.started_at = row.started_at or now
        row.error_code = None
        row.error_message = None
        row.updated_at = now
        await self._session.flush()
        return self._to_value(row), True

    async def set_task_id(self, job_id: uuid.UUID, task_id: str | None) -> None:
        row = await self._require(job_id)
        row.celery_task_id = task_id
        row.updated_at = _utcnow()
        await self._session.flush()

    async def mark_succeeded(
        self,
        job_id: uuid.UUID,
        *,
        result_image_id: uuid.UUID,
    ) -> None:
        row = await self._require(job_id)
        now = _utcnow()
        row.status = "succeeded"
        row.result_image_id = result_image_id
        row.error_code = None
        row.error_message = None
        row.finished_at = now
        row.updated_at = now
        await self._session.flush()

    async def mark_retryable(
        self,
        job_id: uuid.UUID,
        *,
        error_code: str,
        error_message: str,
    ) -> bool:
        row = await self._require(job_id)
        now = _utcnow()
        can_retry = row.attempts < row.max_attempts
        row.status = "queued" if can_retry else "failed"
        row.error_code = error_code[:80]
        row.error_message = error_message[:320]
        row.celery_task_id = None
        row.finished_at = None if can_retry else now
        row.updated_at = now
        await self._session.flush()
        return can_retry

    async def mark_failed(
        self,
        job_id: uuid.UUID,
        *,
        error_code: str,
        error_message: str,
    ) -> None:
        row = await self._require(job_id)
        self._set_failed(
            row,
            error_code=error_code,
            error_message=error_message,
        )
        await self._session.flush()

    async def recover_stale(
        self,
        job_id: uuid.UUID,
    ) -> PassportVisaAiImageJob | None:
        row = await self._locked(job_id)
        if row is None or row.status != "running":
            return None
        cutoff = _utcnow() - timedelta(
            seconds=get_settings().gemini_image_edit_timeout_seconds + 90
        )
        if row.updated_at > cutoff:
            return None
        row.status = "queued"
        row.celery_task_id = None
        row.error_code = "worker_lease_expired"
        row.error_message = "The AI worker stopped unexpectedly; generation was queued again."
        row.updated_at = _utcnow()
        await self._session.flush()
        return self._to_value(row)

    async def _locked(
        self,
        job_id: uuid.UUID,
    ) -> PassportVisaAiImageJobModel | None:
        result = await self._session.execute(
            select(PassportVisaAiImageJobModel)
            .where(PassportVisaAiImageJobModel.id == job_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def _require(self, job_id: uuid.UUID) -> PassportVisaAiImageJobModel:
        result = await self._session.execute(
            select(PassportVisaAiImageJobModel).where(
                PassportVisaAiImageJobModel.id == job_id
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise LookupError(f"Visa AI image job {job_id} was not found")
        return row

    @staticmethod
    def _set_failed(
        row: PassportVisaAiImageJobModel,
        *,
        error_code: str,
        error_message: str,
    ) -> None:
        now = _utcnow()
        row.status = "failed"
        row.error_code = error_code[:80]
        row.error_message = error_message[:320]
        row.finished_at = now
        row.updated_at = now
