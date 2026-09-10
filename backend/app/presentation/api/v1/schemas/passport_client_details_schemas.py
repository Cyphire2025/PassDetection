"""Bounded staff corrections; arbitrary metadata and passport fields are forbidden."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, EmailStr, Field, model_validator


class CustomAnswerCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question_id: uuid.UUID
    value: str = Field(max_length=120)


class CustomDetailCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    detail_id: uuid.UUID
    value: str = Field(max_length=500)


class UpdatePassportClientDetailsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_updated_at: AwareDatetime
    client_email: EmailStr | None = None
    client_phone: str | None = Field(default=None, max_length=32)
    departure_city: str | None = Field(default=None, max_length=120)
    nearest_domestic_airport: str | None = Field(default=None, max_length=120)
    base_city: str | None = Field(default=None, max_length=120)
    staff_code: str | None = Field(default=None, max_length=80)
    agent_employee_type: Literal["agent", "employee"] | None = None
    agent_employee_code: str | None = Field(default=None, max_length=80)
    designation: str | None = Field(default=None, max_length=160)
    agency_dealership_name: str | None = Field(default=None, max_length=200)
    meal_preference: str | None = Field(default=None, max_length=20)
    custom_answers: list[CustomAnswerCorrection] = Field(default_factory=list, max_length=20)
    custom_detail_answers: list[CustomDetailCorrection] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def require_changes(self) -> UpdatePassportClientDetailsRequest:
        if not self.model_fields_set - {"expected_updated_at"}:
            raise ValueError("Choose at least one client detail to update.")
        return self


class ClientDetailFieldResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    label: str
    value: str | None
    required: bool
    type: Literal["text", "email", "tel", "select"]
    options: list[str]
    max_length: int


class CustomAnswerFieldResponse(BaseModel):
    question_id: uuid.UUID
    label: str
    value: str | None
    required: bool
    options: list[str]
    max_length: int


class CustomDetailFieldResponse(BaseModel):
    detail_id: uuid.UUID
    label: str
    value: str | None
    required: bool
    max_length: int


class PassportClientDetailsResponse(BaseModel):
    updated_at: datetime
    fields: list[ClientDetailFieldResponse]
    custom_answers: list[CustomAnswerFieldResponse]
    custom_detail_answers: list[CustomDetailFieldResponse]
