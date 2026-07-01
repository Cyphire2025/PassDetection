"""Processing job state objects."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ProcessingJobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    DEAD_LETTER = "dead_letter"


@dataclass(frozen=True)
class PassportProcessingJob:
    id: uuid.UUID
    submission_id: uuid.UUID
    queue_name: str
    status: ProcessingJobStatus
    attempts: int
    max_attempts: int
    progress: float
    current_stage: str | None
    error_message: str | None
    celery_task_id: str | None
    cancel_requested: bool
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def can_retry(self) -> bool:
        return self.attempts < self.max_attempts

