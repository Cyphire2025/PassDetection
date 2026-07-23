"""Durable background job metadata for Visa-photo AI generation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

PassportVisaAiImageJobStatus = Literal[
    "queued",
    "running",
    "succeeded",
    "failed",
]


@dataclass(frozen=True, slots=True)
class PassportVisaAiImageJob:
    id: uuid.UUID
    submission_id: uuid.UUID
    original_source_storage_key: str
    input_storage_key: str
    prompt: str
    prompt_sha256: str
    requested_by_user_id: uuid.UUID | None
    status: PassportVisaAiImageJobStatus
    attempts: int
    max_attempts: int
    celery_task_id: str | None
    result_image_id: uuid.UUID | None
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime
