"""Stored variants shared by all three staff-facing passport images."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.domain.value_objects.passport_image_crop import PassportImageType


class PassportImageLibrarySource(StrEnum):
    ORIGINAL = "original"
    MANUAL = "manual"
    AI_GENERATED = "ai_generated"


@dataclass(frozen=True, slots=True)
class PassportImageLibraryItem:
    id: uuid.UUID
    submission_id: uuid.UUID
    image_type: PassportImageType
    source: PassportImageLibrarySource
    storage_key: str
    original_source_storage_key: str
    content_sha256: str | None
    prompt: str | None
    prompt_sha256: str | None
    model: str | None
    created_by_user_id: uuid.UUID | None
    created_at: datetime
