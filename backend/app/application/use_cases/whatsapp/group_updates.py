"""Audience choices and stable contact identities for group text updates."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal

from app.domain.value_objects.travel_document_taxonomy import MOBILE_PERSONAL_DOCUMENT_TYPES

SubmissionFilter = Literal["all", "submitted", "not_submitted"]
DeliveryFilter = Literal["all", "sent", "pending"]


@dataclass(frozen=True)
class GroupUpdateFilters:
    submission_status: SubmissionFilter = "all"
    document_status: DeliveryFilter = "all"
    document_type: str = "visa"

    def __post_init__(self) -> None:
        if self.submission_status not in {"all", "submitted", "not_submitted"}:
            raise ValueError("Choose a submission status.")
        if self.document_status not in {"all", "sent", "pending"}:
            raise ValueError("Choose a document delivery status.")
        if self.document_type not in MOBILE_PERSONAL_DOCUMENT_TYPES:
            raise ValueError("Choose a visa or flight-ticket section.")


@dataclass(frozen=True)
class GroupUpdateContact:
    audience_key: str
    name: str
    recipient_id: uuid.UUID | None
    broadcast_group_id: uuid.UUID
    passenger_id: uuid.UUID | None
    phone_number: str | None
    phone_source: Literal["submitted", "imported"]
    submission_status: Literal["submitted", "not_submitted", "needs_review"]
    document_count: int = 0
    confirmed_count: int = 0
    reason: str | None = None
    passport_number: str | None = None
    email: str | None = None
    imported_details: dict[str, str] = field(default_factory=dict)

    @property
    def documents_sent(self) -> bool:
        return self.document_count > 0 and self.confirmed_count == self.document_count

    def matches(self, filters: GroupUpdateFilters) -> bool:
        return (
            (filters.submission_status == "all" or self.submission_status == filters.submission_status)
            and (filters.document_status == "all"
                 or (filters.document_status == "sent") == self.documents_sent)
        )
