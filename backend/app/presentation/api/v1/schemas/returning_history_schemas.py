"""Explicit historical disclosure schemas; storage locators never serialize."""

import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel

from app.application.travellers.current_details import CurrentDetailField
from app.presentation.api.v1.schemas.client_group_schemas import (
    CustomDetailResponse,
    CustomQuestionResponse,
)


class ReviewedPassport(BaseModel):
    id: uuid.UUID
    number: str
    issuing_country: str
    document_type: str
    date_of_birth: date | None
    issue_date: date | None
    expiry_date: date | None
    revision: int


class ReviewedDocument(BaseModel):
    id: uuid.UUID
    label: str
    content_type: str
    available: bool


class AvailablePassport(BaseModel):
    id: uuid.UUID
    number: str
    issuing_country: str
    document_type: str
    is_default: bool
    expiry_date: date | None


class ReviewedSuitability(BaseModel):
    outcome: Literal["suitable", "replacement_required", "review_required", "cannot_assess"]
    reason_codes: list[str]


class CurrentRequirements(BaseModel):
    custom_questions: list[CustomQuestionResponse]
    custom_details: list[CustomDetailResponse]
    require_selfie: bool
    current_detail_fields: list[CurrentDetailField]


class ReturningHistoryResponse(BaseModel):
    display_name: str
    contact_phone: str | None
    passport: ReviewedPassport | None
    extracted_fields: dict[str, str]
    documents: list[ReviewedDocument]
    suitability: ReviewedSuitability
    group_requirements: CurrentRequirements
    missing_requirements: list[str]
    question_version: str
    review_version: str
    participation_revision: int | None
    saved_answers: dict[str, dict[str, str]]
    available_passports: list[AvailablePassport]
