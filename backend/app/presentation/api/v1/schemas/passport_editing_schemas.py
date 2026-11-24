"""Focused passport editing API contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PassportImageTypeValue = Literal[
    "visa_photo", "passport_front", "passport_back", "passport_cover", "passport_back_cover"
]


class PassportImageCropCoordinates(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float = Field(..., ge=0.0, le=1.0, allow_inf_nan=False)
    y: float = Field(..., ge=0.0, le=1.0, allow_inf_nan=False)
    width: float = Field(..., ge=0.08, le=1.0, allow_inf_nan=False)
    height: float = Field(..., ge=0.08, le=1.0, allow_inf_nan=False)
    rotation_degrees: int = Field(default=0, ge=0, le=359)
    sharpness: float = Field(default=1.0, ge=1.0, le=3.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_bounds(self) -> PassportImageCropCoordinates:
        if self.x + self.width > 1.000001 or self.y + self.height > 1.000001:
            raise ValueError("Crop coordinates must stay inside the image.")
        return self


class PassportImageCropUpdateRequest(PassportImageCropCoordinates):
    expected_revision: int = Field(..., ge=0)


class PassportImageCropResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(..., ge=0)


class PassportImageCropResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_type: PassportImageTypeValue
    original_url: str
    editable_source_url: str
    cropped_url: str
    crop: PassportImageCropCoordinates | None = None
    source_width: int | None = Field(default=None, ge=1)
    source_height: int | None = Field(default=None, ge=1)
    sharpness: float = Field(default=1.0, ge=1.0, le=3.0)
    sharpness_algorithm_version: Literal[1, 2] = 1
    ai_edited: bool = False
    revision: int = Field(default=0, ge=0)


class PassportVisaAiPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(..., min_length=3, max_length=1000)


class PassportVisaAiImageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    image_url: str
    prompt: str = Field(..., min_length=3, max_length=1000)
    model: str
    created_at: datetime
    is_current: bool = False


class PassportVisaAiImageListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PassportVisaAiImageResponse]


class PassportVisaAiImageJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    status: Literal["queued", "running", "succeeded", "failed"]
    prompt: str = Field(..., min_length=3, max_length=1000)
    attempts: int = Field(..., ge=0)
    max_attempts: int = Field(..., ge=1, le=3)
    error_message: str | None = None
    result: PassportVisaAiImageResponse | None = None
    created_at: datetime
    updated_at: datetime


class PassportVisaAiImageUseRequest(PassportImageCropCoordinates):
    expected_revision: int = Field(..., ge=0)
