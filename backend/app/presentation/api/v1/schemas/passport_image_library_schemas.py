"""Response contracts for the common passport image library."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.presentation.api.v1.schemas.passport_schemas import PassportImageTypeValue


class PassportImageLibraryItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    image_type: PassportImageTypeValue
    image_url: str
    source: Literal["original", "manual", "ai_generated"]
    created_at: datetime
    is_current: bool = False
    prompt: str | None = None
    model: str | None = None


class PassportImageLibraryListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PassportImageLibraryItemResponse]
