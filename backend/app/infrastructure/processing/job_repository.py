"""Persistence operations for passport OCR processing jobs."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.infrastructure.database.models import PassportProcessingJobModel
from app.infrastructure.processing.job_state import PassportProcessingJob, ProcessingJobStatus


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class PassportProcessingJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_entity(model: PassportProcessingJobModel) -> PassportProcessingJob:
        return PassportProcessingJob(
            id=model.id,
            submission_id=model.submission_id,
            queue_name=model.queue_name,
            status=ProcessingJobStatus(model.status),
            attempts=model.attempts,
            max_attempts=model.max_attempts,
            extraction_revision=model.extraction_revision,
            progress=model.progress,
            current_stage=model.current_stage,
            error_message=model.error_message,
            celery_task_id=model.celery_task_id,
            cancel_requested=model.cancel_requested,
            started_at=model.started_at,
            finished_at=model.finished_at,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    async def create(
        self,
        *,
        submission_id: uuid.UUID,
        queue_name: str = "passport_ocr",
        max_attempts: int = 3,
        extraction_revision: int = 0,
    ) -> PassportProcessingJob:
        existing = await self.active_for_submission(
            submission_id,
            extraction_revision=extraction_revision,
        )
        if existing:
            return existing
        model = PassportProcessingJobModel(
            id=uuid.uuid4(),
            submission_id=submission_id,
            queue_name=queue_name,
            status=ProcessingJobStatus.QUEUED.value,
            attempts=0,
            max_attempts=max_attempts,
            extraction_revision=extraction_revision,
            progress=0.0,
            current_stage="queued",
            cancel_requested=False,
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )
        try:
            async with self._session.begin_nested():
                self._session.add(model)
                await self._session.flush()
        except IntegrityError:
            existing = await self.active_for_submission(
                submission_id,
                extraction_revision=extraction_revision,
            )
            if existing is None:
                raise
            return existing
        return self._to_entity(model)

    async def get(self, job_id: uuid.UUID) -> PassportProcessingJob | None:
        model = await self._get_model(job_id)
        return self._to_entity(model) if model else None

    async def set_task_id(self, job_id: uuid.UUID, task_id: str | None) -> None:
        model = await self._require_model(job_id)
        model.celery_task_id = task_id
        model.updated_at = _utcnow()
        await self._session.flush()

    async def mark_running(self, job_id: uuid.UUID, *, stage: str = "starting") -> PassportProcessingJob:
        job, _claimed = await self.claim_running(job_id, stage=stage)
        if job is None:
            raise LookupError(f"Passport processing job {job_id} was not found")
        return job

    async def claim_running(
        self,
        job_id: uuid.UUID,
        *,
        stage: str = "starting",
    ) -> tuple[PassportProcessingJob | None, bool]:
        result = await self._session.execute(
            select(PassportProcessingJobModel)
            .where(PassportProcessingJobModel.id == job_id)
            .with_for_update()
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None, False
        if model.status in {
            ProcessingJobStatus.SUCCEEDED.value,
            ProcessingJobStatus.FAILED.value,
            ProcessingJobStatus.CANCELLED.value,
            ProcessingJobStatus.DEAD_LETTER.value,
        }:
            return self._to_entity(model), False
        if model.status == ProcessingJobStatus.RUNNING.value:
            lease_cutoff = _utcnow() - timedelta(
                seconds=get_settings().processing_job_timeout_seconds + 30
            )
            if model.updated_at and model.updated_at >= lease_cutoff:
                return self._to_entity(model), False
        if model.cancel_requested:
            model.status = ProcessingJobStatus.CANCELLED.value
            model.current_stage = "cancelled"
            model.finished_at = _utcnow()
            model.updated_at = _utcnow()
            await self._session.flush()
            return self._to_entity(model), False

        model.status = ProcessingJobStatus.RUNNING.value
        model.attempts += 1
        model.progress = max(model.progress, 0.05)
        model.current_stage = stage
        model.started_at = model.started_at or _utcnow()
        model.updated_at = _utcnow()
        await self._session.flush()
        return self._to_entity(model), True

    async def checkpoint(self) -> None:
        """Publish job state and release any short-lived claim lock."""

        await self._session.commit()

    async def update_progress(self, job_id: uuid.UUID, *, progress: float, stage: str) -> PassportProcessingJob:
        model = await self._require_model(job_id)
        model.progress = min(max(progress, 0.0), 1.0)
        model.current_stage = stage
        model.updated_at = _utcnow()
        await self._session.flush()
        return self._to_entity(model)

    async def mark_retryable_failure(self, job_id: uuid.UUID, message: str) -> PassportProcessingJob:
        model = await self._require_model(job_id)
        model.status = ProcessingJobStatus.QUEUED.value
        model.current_stage = "retry_queued"
        model.error_message = message
        model.updated_at = _utcnow()
        await self._session.flush()
        return self._to_entity(model)

    async def mark_failed(self, job_id: uuid.UUID, message: str) -> PassportProcessingJob:
        model = await self._require_model(job_id)
        model.status = ProcessingJobStatus.FAILED.value
        model.progress = min(model.progress, 0.99)
        model.current_stage = "failed"
        model.error_message = message
        model.finished_at = _utcnow()
        model.updated_at = _utcnow()
        await self._session.flush()
        return self._to_entity(model)

    async def mark_dead_letter(self, job_id: uuid.UUID, message: str) -> PassportProcessingJob:
        model = await self._require_model(job_id)
        model.status = ProcessingJobStatus.DEAD_LETTER.value
        model.progress = min(model.progress, 0.99)
        model.current_stage = "dead_letter"
        model.error_message = message
        model.finished_at = _utcnow()
        model.updated_at = _utcnow()
        await self._session.flush()
        return self._to_entity(model)

    async def mark_succeeded(self, job_id: uuid.UUID) -> PassportProcessingJob:
        model = await self._require_model(job_id)
        model.status = ProcessingJobStatus.SUCCEEDED.value
        model.progress = 1.0
        model.current_stage = "completed"
        model.error_message = None
        model.finished_at = _utcnow()
        model.updated_at = _utcnow()
        await self._session.flush()
        return self._to_entity(model)

    async def request_cancel(self, job_id: uuid.UUID) -> PassportProcessingJob:
        model = await self._require_model(job_id)
        model.cancel_requested = True
        if model.status == ProcessingJobStatus.QUEUED.value:
            model.status = ProcessingJobStatus.CANCELLED.value
            model.current_stage = "cancelled"
            model.finished_at = _utcnow()
        model.updated_at = _utcnow()
        await self._session.flush()
        return self._to_entity(model)

    async def mark_cancelled(self, job_id: uuid.UUID, message: str | None = None) -> PassportProcessingJob:
        model = await self._require_model(job_id)
        model.cancel_requested = True
        model.status = ProcessingJobStatus.CANCELLED.value
        model.current_stage = "cancelled"
        model.error_message = message
        model.finished_at = _utcnow()
        model.updated_at = _utcnow()
        await self._session.flush()
        return self._to_entity(model)

    async def latest_for_submission(self, submission_id: uuid.UUID) -> PassportProcessingJob | None:
        result = await self._session.execute(
            select(PassportProcessingJobModel)
            .where(PassportProcessingJobModel.submission_id == submission_id)
            .order_by(PassportProcessingJobModel.created_at.desc())
            .limit(1)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def active_for_submission(
        self,
        submission_id: uuid.UUID,
        *,
        extraction_revision: int,
    ) -> PassportProcessingJob | None:
        result = await self._session.execute(
            select(PassportProcessingJobModel)
            .where(
                PassportProcessingJobModel.submission_id == submission_id,
                PassportProcessingJobModel.extraction_revision == extraction_revision,
                PassportProcessingJobModel.status.in_(
                    [
                        ProcessingJobStatus.QUEUED.value,
                        ProcessingJobStatus.RUNNING.value,
                    ]
                ),
            )
            .order_by(PassportProcessingJobModel.created_at.desc())
            .limit(1)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def _get_model(self, job_id: uuid.UUID) -> PassportProcessingJobModel | None:
        result = await self._session.execute(
            select(PassportProcessingJobModel)
            .where(PassportProcessingJobModel.id == job_id)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def claim_recoverable_jobs(self, *, limit: int = 2) -> list[PassportProcessingJob]:
        """Lease stale outbox rows, including published tasks that never ran.

        SKIP LOCKED allows each API process to repair disjoint work. Updating
        the timestamp before publication reserves a recovery interval; the
        worker's existing claim and extraction revision remain authoritative.
        """
        now = _utcnow()
        queued_cutoff = now - timedelta(seconds=60)
        running_cutoff = now - timedelta(
            seconds=get_settings().processing_job_timeout_seconds + 30
        )
        rows = await self._session.execute(
            select(PassportProcessingJobModel)
            .where(
                PassportProcessingJobModel.cancel_requested.is_(False),
                or_(
                    and_(
                        PassportProcessingJobModel.status == ProcessingJobStatus.QUEUED.value,
                        PassportProcessingJobModel.updated_at < queued_cutoff,
                    ),
                    and_(
                        PassportProcessingJobModel.status == ProcessingJobStatus.RUNNING.value,
                        PassportProcessingJobModel.updated_at < running_cutoff,
                    ),
                ),
            )
            .order_by(PassportProcessingJobModel.updated_at, PassportProcessingJobModel.id)
            .limit(min(max(limit, 1), 100))
            .with_for_update(skip_locked=True)
        )
        jobs: list[PassportProcessingJob] = []
        for model in rows.scalars():
            model.updated_at = now
            if model.attempts >= model.max_attempts:
                model.status = ProcessingJobStatus.DEAD_LETTER.value
                model.current_stage = "dead_letter"
                model.finished_at = now
                model.error_message = "Processing attempts exhausted after interruption. Retry manually."
                continue
            model.status = ProcessingJobStatus.QUEUED.value
            model.current_stage = "recovery_queued"
            jobs.append(self._to_entity(model))
        await self._session.flush()
        return jobs

    async def _require_model(self, job_id: uuid.UUID) -> PassportProcessingJobModel:
        model = await self._get_model(job_id)
        if model is None:
            raise LookupError(f"Passport processing job {job_id} was not found")
        return model
