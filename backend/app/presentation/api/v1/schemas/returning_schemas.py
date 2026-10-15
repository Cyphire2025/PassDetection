"""Public allowlists: proof material is input-only and never echoed back."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ReturningRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClaimStartRequest(ReturningRequest):
    group_token: str = Field(min_length=1, max_length=128)
    method: Literal["phone", "passport", "code"]
    phone_number: str | None = Field(default=None, max_length=64)
    passport_number: str | None = Field(default=None, min_length=3, max_length=32)
    issuing_country: str | None = Field(default=None, min_length=3, max_length=3)
    document_type: str = Field(default="P", min_length=1, max_length=16)
    individual_code: str | None = Field(default=None, min_length=1, max_length=128)


class PassportCheckRequest(ReturningRequest):
    passport_number: str | None = Field(default=None, min_length=3, max_length=32)
    issuing_country: str | None = Field(default=None, min_length=3, max_length=3)
    document_type: str = Field(default="P", min_length=1, max_length=16)
    individual_code: str | None = Field(default=None, min_length=1, max_length=128)


class CodeVerifyRequest(ReturningRequest):
    code: str = Field(pattern=r"^[0-9]{6}$")


class CandidateSelectRequest(ReturningRequest):
    handle: str = Field(min_length=32, max_length=128)


class AnswerRequest(ReturningRequest):
    answers: dict[Annotated[str, Field(max_length=32)], Annotated[str, Field(max_length=32)]] = Field(max_length=3)


class ChangeQuestionRequest(ReturningRequest):
    field: Literal["date_of_birth", "issue_date", "expiry_date"]


class ConfirmClaimRequest(ReturningRequest):
    acting_for: Literal["self", "family"] | None = None
    contact_change_confirmed: bool = False


class ClaimStageResponse(BaseModel):
    stage: Literal["contact", "identify", "passport", "challenge", "confirm", "recovery", "review"]
    questions: list[str] = Field(default_factory=list)
    available_questions: list[str] = Field(default_factory=list)
    can_change_question: bool = False
    expires_in_seconds: int | None = None


class ReturningCapabilitiesResponse(BaseModel):
    enabled: bool
    code_label: str | None = None


class OTPRequestResponse(BaseModel):
    expires_in_seconds: int
    resend_after_seconds: int


class MaskedCandidateResponse(BaseModel):
    handle: str
    label: str
    passport_hint: str


class CandidatePageResponse(BaseModel):
    items: list[MaskedCandidateResponse]
    narrowing_required: bool


class ContactChangeRequest(ReturningRequest):
    phone_number: str = Field(min_length=8, max_length=64)


class OwnedReuseSource(ReturningRequest):
    source_submission_id: UUID
    expected_extraction_revision: int = Field(ge=0)


class CompleteReuseRequest(ReturningRequest):
    question_version: str = Field(min_length=1, max_length=128)
    review_version: str = Field(min_length=64, max_length=64)
    expected_participation_revision: int | None = Field(default=None, ge=1)
    custom_answers: dict[str, str] = Field(default_factory=dict, max_length=20)
    custom_detail_answers: dict[str, str] = Field(default_factory=dict, max_length=20)
    current_details: dict[str, str] = Field(default_factory=dict, max_length=20)
    information_confirmed: Literal[True]
    idempotency_key: str = Field(min_length=16, max_length=128)
    owned_source: OwnedReuseSource | None = None
