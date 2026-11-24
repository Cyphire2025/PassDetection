"""Qualifier relation choices and persisted selection contracts."""

from __future__ import annotations

import unicodedata
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.exceptions.exceptions import ValidationError as DomainValidationError
from app.domain.value_objects.qualifier_relations import normalize_qualifier_choice


class QualifierRelationOptionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., min_length=1, max_length=40)
    label: str = Field(..., min_length=1, max_length=80)


class CreateQualifierSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    is_self: bool
    relation_code: str | None = Field(default=None, max_length=40)
    other_relation: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("other_relation", mode="before")
    @classmethod
    def normalize_other_relation_input(cls, value: object) -> object:
        return unicodedata.normalize("NFC", value).strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_exactly_one_path(self) -> CreateQualifierSelectionRequest:
        if self.is_self and (self.relation_code or self.other_relation is not None):
            raise ValueError("Choose either Self or a relationship, not both.")
        if not self.is_self and not self.relation_code:
            raise ValueError("Choose the passenger's relationship with the qualifier.")
        if (self.relation_code or "").casefold() != "other":
            if self.other_relation is not None:
                raise ValueError("Choose Other to enter a relationship.")
            return self
        try:
            _is_self, code, label = normalize_qualifier_choice(
                is_self=self.is_self,
                relation_code=self.relation_code,
                other_relation=self.other_relation,
            )
        except DomainValidationError as exc:
            raise ValueError(str(exc)) from exc
        self.relation_code = code
        self.other_relation = label if code == "other" else None
        return self


class QualifierSelectionStateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    is_self: bool
    relation_code: str | None = None
    relation_label: str
    selected_at: datetime
    expires_at: datetime
    status: Literal["active", "expired", "consumed"]
    submission_id: uuid.UUID | None = None


class CreateQualifierSelectionResponse(QualifierSelectionStateResponse):
    selection_token: str = Field(..., min_length=32, max_length=256)
