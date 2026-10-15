"""Operational passenger labels; passport identity fields are not editable here."""

import uuid
from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class UpdatePassportDisplayNameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=255)
    expected_updated_at: AwareDatetime

    @field_validator("display_name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("Display name must be a single line without control characters.")
        value = " ".join(value.split())
        if not value:
            raise ValueError("Enter a display name.")
        return value


class PassportDisplayNameResponse(BaseModel):
    id: uuid.UUID
    client_name: str
    display_name: str | None
    updated_at: datetime
