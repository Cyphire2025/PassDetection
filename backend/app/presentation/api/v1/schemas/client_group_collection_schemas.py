"""Custom collection question and detail schemas."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.presentation.api.v1.schemas.client_group_request_validation import validated_text_choices


class CustomQuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: uuid.UUID
    label: str = Field(..., min_length=1, max_length=100)
    options: list[str] = Field(..., min_length=2, max_length=50)
    enabled: bool = True
    required: bool = True

    @field_validator("options", mode="before")
    @classmethod
    def normalize_options(cls, values: list[str] | None) -> list[str]:
        seen: set[str] = set()
        options: list[str] = []
        for value in validated_text_choices(values, "Custom options"):
            option = " ".join(str(value).strip().split())
            if not option:
                continue
            if len(option) > 120:
                raise ValueError("Custom options must be 120 characters or fewer.")
            key = option.casefold()
            if key in seen:
                continue
            seen.add(key)
            options.append(option)
        return options


class CustomQuestionResponse(CustomQuestionRequest):
    pass


class CustomDetailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: uuid.UUID
    label: str = Field(..., min_length=1, max_length=100)
    enabled: bool = True
    required: bool = True


class CustomDetailResponse(CustomDetailRequest):
    pass
