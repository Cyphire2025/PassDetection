"""Bounded private draft input; no storage keys or identity selectors are public."""
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.application.travellers.fresh_draft_contracts import FreshCollection
from app.domain.value_objects.passport_fields import validate_reviewed_passport_payload

DraftSide = Literal["front", "back", "cover", "back_cover", "photo"]
ShortKey = Annotated[str, Field(min_length=1, max_length=128)]
Answer = Annotated[str, Field(max_length=500)]


class DraftPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    passport_fields: dict[str, str] = Field(default_factory=dict, max_length=10)
    current_details: dict[ShortKey, Answer] = Field(default_factory=dict, max_length=20)
    custom_answers: dict[ShortKey, Answer] = Field(default_factory=dict, max_length=20)
    custom_detail_answers: dict[ShortKey, Answer] = Field(default_factory=dict, max_length=20)
    collection: FreshCollection | None = None

    @field_validator("passport_fields")
    @classmethod
    def bounded_passport_fields(cls, value: dict[str, str]) -> dict[str, str]:
        # Autosave permits incomplete dates; final publication normalizes them.
        validate_reviewed_passport_payload(value)
        return value


class DraftStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_version: str = Field(min_length=64, max_length=64)


class DraftSave(DraftPayload):
    expected_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=16, max_length=128)


class DraftDocument(BaseModel):
    id: UUID
    side: DraftSide
    state: Literal["uploading", "ready"]


class DraftView(DraftPayload):
    id: UUID
    revision: int
    expires_at: datetime
    status: Literal["active", "submitted"]
    verified_phone: str | None = None
    phone_verification_id: UUID | None = None
    phone_verification_expires_at: datetime | None = None
    participation_id: UUID | None = None
    source_submission_id: UUID | None = None
    result_status: str | None = None
    documents: list[DraftDocument] = Field(default_factory=list, max_length=5)
    extraction_status: Literal["none", "pending", "running", "succeeded", "failed"] = "none"
    extracted_fields: dict[str, str] = Field(default_factory=dict, max_length=10)
    ecr_status: Literal["none", "pending", "running", "succeeded", "failed"] = "none"
    ecr_result: Literal["ECR", "NA", "REVIEW"] | None = None


class DraftComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    review_version: str = Field(min_length=64, max_length=64)
    question_version: str = Field(min_length=1, max_length=128)
    expected_participation_revision: int | None = Field(default=None, ge=1)
    information_confirmed: Literal[True]
    idempotency_key: str = Field(min_length=16, max_length=128)
    owned_source: "DraftOwnedSource | None" = None


class DraftOwnedSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_submission_id: UUID
    expected_extraction_revision: int = Field(ge=1)


DraftComplete.model_rebuild()
