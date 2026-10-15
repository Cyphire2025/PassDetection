"""Minimal combined records without document or contact disclosure."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class CompanySubmissionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    group_id: UUID
    group_name: str
    travel_date: date | None
    display_name: str
    status: Literal["client_submitted", "confirmed", "submitted", "ai_approved", "needs_review", "staff_approved"]
    created_at: datetime


class CompanySubmissionPage(BaseModel):
    items: list[CompanySubmissionResponse]
    next_cursor: str | None
    has_more: bool
