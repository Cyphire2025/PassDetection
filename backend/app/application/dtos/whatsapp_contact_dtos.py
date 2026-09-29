"""Shared contact ingestion DTOs for website and reviewed application adapters."""

from typing import Literal

from pydantic import BaseModel, Field

WhatsAppContactRejectionCode = Literal[
    "missing_phone",
    "invalid_phone",
    "missing_name",
    "duplicate_phone",
]


class WhatsAppRecipientInput(BaseModel):
    name: str | None = None
    phone_number: str = Field(min_length=6, max_length=64)
    imported_fields: dict[str, str] = Field(default_factory=dict)


class WhatsAppRejectedContactInput(BaseModel):
    source_file_name: str = Field(min_length=1, max_length=255)
    sheet_name: str = Field(min_length=1, max_length=31)
    row_number: int = Field(ge=1, le=1_048_576)
    raw_name: str | None = Field(default=None, max_length=256)
    raw_phone_number: str | None = Field(default=None, max_length=64)
    imported_fields: dict[str, str] = Field(default_factory=dict)
    reason_code: WhatsAppContactRejectionCode


class WhatsAppSupportContactInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    phone_number: str = Field(min_length=6, max_length=64)
