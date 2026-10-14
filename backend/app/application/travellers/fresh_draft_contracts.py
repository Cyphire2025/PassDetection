"""Only existing collection fields are accepted by the isolated fresh draft."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class FreshCollection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    acquisition_mode: Literal["file", "camera"] = "file"
    visa_photo_source: Literal["file", "camera"] | None = None
    qualifier_selection_token: str | None = Field(default=None, max_length=256)
    submission_mode: Literal["single", "family"] = "single"
    family_group_id: UUID | None = None
    family_member_index: int | None = Field(default=None, ge=0, le=19)
    family_relation: str | None = Field(default=None, max_length=80)
    family_gender: str | None = Field(default=None, max_length=40)
    family_head_name: str | None = Field(default=None, max_length=255)
    family_head_email: EmailStr | None = None
    family_head_phone: str | None = Field(default=None, max_length=64)


class FreshDraftComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    phone_verification_id: UUID
    idempotency_key: str = Field(min_length=16, max_length=128)
    information_confirmed: Literal[True]
