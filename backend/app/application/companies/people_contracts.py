"""Small staff-only contracts for current identities and immutable documents."""

import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.application.companies.original_record import OriginalRecord
from app.domain.services.traveller_verification import (
    VerificationFailure,
    exact_passport_number,
    issuing_context,
)
from app.domain.value_objects.passport_fields import validate_reviewed_passport_payload


class PersonItem(BaseModel):
    id: uuid.UUID
    display_name: str
    status: str
    revision: int
    trip_count: int
    document_version_count: int
    duplicate_status: Literal["none", "possible"]
    current_passport_last4: str | None


class PersonPage(BaseModel):
    indexing_pending: bool = False
    items: list[PersonItem]
    next_cursor: str | None
    has_more: bool


class CurrentDocument(BaseModel):
    id: uuid.UUID
    passport_id: uuid.UUID
    revision_number: int
    fields: dict[str, str]
    issuing_country: str
    document_type: str


class CurrentPerson(BaseModel):
    id: uuid.UUID
    status: str
    display_name: str
    revision: int
    contact_revision: int
    phone_number: str | None
    phone_verified: bool
    current_document: CurrentDocument | None
    original_record: OriginalRecord | None = None


class PersonEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=3, max_length=500)
    display_name: str = Field(min_length=1, max_length=120)
    phone_number: str | None = Field(default=None, max_length=32)
    fields: dict[str, str] | None = None

    @field_validator("fields")
    @classmethod
    def bounded_fields(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is not None:
            validate_reviewed_passport_payload(value)
            if "passport_number" in value:
                try:
                    exact_passport_number(value["passport_number"])
                except VerificationFailure as exc:
                    raise ValueError("Enter a valid full passport number.") from exc
        return value


class DocumentAsset(BaseModel):
    id: uuid.UUID
    side: str
    content_type: str
    byte_size: int
    availability: str


class DocumentVersion(BaseModel):
    id: uuid.UUID
    passport_id: uuid.UUID
    revision_number: int
    status: str
    created_at: datetime
    change_kind: str
    is_current: bool
    fields: dict[str, str]
    assets: list[DocumentAsset]


class DocumentPage(BaseModel):
    items: list[DocumentVersion]
    next_cursor: str | None
    has_more: bool


class DocumentUpload(PersonEdit):
    change_kind: Literal["scan", "renewal", "correction"]
    side: Literal["front", "back", "cover", "back_cover", "photo"]
    issuing_country: str = Field(min_length=2, max_length=3)
    document_type: str = Field(min_length=1, max_length=32)
    fields: dict[str, str]
    # Upload changes document evidence only; current display/contact are held.
    display_name: str = Field(default="", max_length=120)

    @model_validator(mode="after")
    def valid_document_context(self) -> Self:
        try:
            issuing_context(self.issuing_country, self.document_type)
            exact_passport_number(self.fields.get("passport_number", ""))
        except VerificationFailure as exc:
            raise ValueError("Enter a valid issuing country, document type and full passport number.") from exc
        return self


class SourceDocument(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    group_name: str
    created_at: datetime
    revision_number: int
    available_sides: list[str]


class SourceDocumentPage(BaseModel):
    items: list[SourceDocument]
    next_cursor: str | None
    has_more: bool
