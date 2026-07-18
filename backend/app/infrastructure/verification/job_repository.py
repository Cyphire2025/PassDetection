"""Persistence for durable post-submission verification jobs."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.infrastructure.database.models import (
    PassportPostSubmissionVerificationJobModel,
)


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


@dataclass(frozen=True)
class PostSubmissionVerificationJob:
    id: uuid.UUID
    submission_id: uuid.UUID
    verification_revision: int
    status: str
    attempts: int
    max_attempts: int
    celery_task_id: str | None
    error_code: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PostSubmissionVerificationJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_entity(
        model: PassportPostSubmissionVerificationJobModel,
    ) -> PostSubmissionVerificationJob:
        return PostSubmissionVerificationJob(
            id=model.id,
            submission_id=model.submission_id,
            verification_revision=model.verification_revision,
            status=model.status,
            attempts=model.attempts,
            max_attempts=model.max_attempts,
            celery_task_id=model.celery_task_id,
            error_code=model.error_code,
            started_at=model.started_at,
            finished_at=model.finished_at,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    async def enqueue(
        self,
        *,
        submission_id: uuid.UUID,
        verification_revision: int,
    ) -> PostSubmissionVerificationJob:
        existing = await self.for_revision(submission_id, verification_revision)
        if existing:
            return existing
        now = _utcnow()
        model = PassportPostSubmissionVerificationJobModel(
            id=uuid.uuid4(),
            submission_id=submission_id,
            verification_revision=verification_revision,
            status="queued",
            attempts=0,
            max_attempts=get_settings().processing_job_max_attempts,
            created_at=now,
            updated_at=now,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(model)
                await self._session.flush()
        except IntegrityError:
            existing = await self.for_revision(submission_id, verification_revision)
            if existing is None:
                raise
            return existing
        return self._to_entity(model)

    async def get(self, job_id: uuid.UUID) -> PostSubmissionVerificationJob | None:
        model = await self._get_model(job_id)
        return self._to_entity(model) if model else None

    async def for_revision(
        self,
        submission_id: uuid.UUID,
        verification_revision: int,
    ) -> PostSubmissionVerificationJob | None:
        result = await self._session.execute(
            select(PassportPostSubmissionVerificationJobModel).where(
                PassportPostSubmissionVerificationJobModel.submission_id
                == submission_id,
                PassportPostSubmissionVerificationJobModel.verification_revision
                == verification_revision,
            )
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def claim_running(
        self,
        job_id: uuid.UUID,
    ) -> tuple[PostSubmissionVerificationJob | None, bool]:
        result = await self._session.execute(
            select(PassportPostSubmissionVerificationJobModel)
            .where(PassportPostSubmissionVerificationJobModel.id == job_id)
            .with_for_update()
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None, False
        if model.status in {"succeeded", "failed"}:
            return self._to_entity(model), False
        if model.status == "running":
            lease_cutoff = _utcnow() - timedelta(
                seconds=get_settings().gemini_timeout_seconds + 30
            )
            if model.updated_at >= lease_cutoff:
                return self._to_entity(model), False
        if model.attempts >= model.max_attempts:
            model.status = "failed"
            model.error_code = "attempt_limit_reached"
            model.finished_at = _utcnow()
            model.updated_at = _utcnow()
            await self._session.flush()
            return self._to_entity(model), False

        model.status = "running"
        model.attempts += 1
        model.started_at = model.started_at or _utcnow()
        model.updated_at = _utcnow()
        await self._session.flush()
        return self._to_entity(model), True

    async def set_task_id(self, job_id: uuid.UUID, task_id: str | None) -> None:
        model = await self._require_model(job_id)
        model.celery_task_id = task_id
        model.updated_at = _utcnow()
        await self._session.flush()

    async def mark_succeeded(self, job_id: uuid.UUID) -> None:
        model = await self._require_model(job_id)
        model.status = "succeeded"
        model.error_code = None
        model.finished_at = _utcnow()
        model.updated_at = _utcnow()
        await self._session.flush()

    async def mark_retryable(self, job_id: uuid.UUID, error_code: str) -> None:
        model = await self._require_model(job_id)
        model.status = "queued" if model.attempts < model.max_attempts else "failed"
        model.error_code = error_code[:80]
        model.celery_task_id = None
        model.finished_at = _utcnow() if model.status == "failed" else None
        model.updated_at = _utcnow()
        await self._session.flush()

    async def queued_for_recovery(
        self,
        *,
        limit: int = 100,
        stale_after_seconds: float = 10.0,
        stale_dispatched_after_seconds: float = 900.0,
    ) -> list[PostSubmissionVerificationJob]:
        now = _utcnow()
        undispatched_cutoff = now - timedelta(seconds=max(0.0, stale_after_seconds))
        dispatched_cutoff = now - timedelta(
            seconds=max(
                stale_after_seconds,
                stale_dispatched_after_seconds,
            )
        )
        result = await self._session.execute(
            select(PassportPostSubmissionVerificationJobModel)
            .where(
                PassportPostSubmissionVerificationJobModel.status == "queued",
                or_(
                    (
                        PassportPostSubmissionVerificationJobModel.celery_task_id.is_(
                            None
                        )
                        & (
                            PassportPostSubmissionVerificationJobModel.updated_at
                            <= undispatched_cutoff
                        )
                    ),
                    (
                        PassportPostSubmissionVerificationJobModel.celery_task_id.is_not(
                            None
                        )
                        & (
                            PassportPostSubmissionVerificationJobModel.updated_at
                            <= dispatched_cutoff
                        )
                    ),
                ),
            )
            .order_by(PassportPostSubmissionVerificationJobModel.created_at)
            .limit(limit)
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def requeue_expired_running(self, *, limit: int = 100) -> int:
        """Release jobs left running after a worker or API process died."""

        lease_cutoff = _utcnow() - timedelta(
            seconds=get_settings().gemini_timeout_seconds + 30
        )
        result = await self._session.execute(
            select(PassportPostSubmissionVerificationJobModel)
            .where(
                PassportPostSubmissionVerificationJobModel.status == "running",
                PassportPostSubmissionVerificationJobModel.updated_at <= lease_cutoff,
            )
            .order_by(PassportPostSubmissionVerificationJobModel.updated_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        models = list(result.scalars().all())
        now = _utcnow()
        for model in models:
            model.status = "queued"
            model.celery_task_id = None
            model.error_code = "worker_lease_expired"
            model.updated_at = now
        if models:
            await self._session.flush()
        return len(models)

    async def _get_model(
        self,
        job_id: uuid.UUID,
    ) -> PassportPostSubmissionVerificationJobModel | None:
        result = await self._session.execute(
            select(PassportPostSubmissionVerificationJobModel).where(
                PassportPostSubmissionVerificationJobModel.id == job_id
            )
        )
        return result.scalar_one_or_none()

    async def _require_model(
        self,
        job_id: uuid.UUID,
    ) -> PassportPostSubmissionVerificationJobModel:
        model = await self._get_model(job_id)
        if model is None:
            raise LookupError(f"Post-submission verification job {job_id} was not found")
        return model
