"""Durable, identity-verified Visa-photo AI generation metadata."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class PassportVisaAiImage:
    id: uuid.UUID
    submission_id: uuid.UUID
    original_source_storage_key: str
    input_storage_key: str
    generated_storage_key: str
    prompt: str
    prompt_sha256: str
    content_sha256: str
    model: str
    created_by_user_id: uuid.UUID | None
    created_at: datetime
