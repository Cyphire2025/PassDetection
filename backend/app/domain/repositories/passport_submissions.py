"""Passport persistence and group summary contracts."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Sequence

from app.domain.entities.entities import PassportSubmission, User
from app.domain.value_objects.custom_questions import (
    CustomDetailDefinition,
    CustomQuestionDefinition,
)
from app.domain.value_objects.dashboard_summary import DashboardRecentSubmission
from app.domain.value_objects.trip_timezone import DEFAULT_TRIP_TIMEZONE


@dataclass(frozen=True)
class PassportSubmissionGroupSummary:
    group_id: uuid.UUID
    group_name: str
    group_status: str
    total_passports: int
    pending_review_count: int
    confirmed_count: int
    failed_count: int
    latest_submission_at: datetime
    destination: str | None = None
    travel_date: date | None = None
    return_date: date | None = None
    timezone: str = DEFAULT_TRIP_TIMEZONE
    package_name: str | None = None
    departure_cities: list[str] | None = None
    base_city_enabled: bool = False
    nearest_international_airport_enabled: bool = False
    staff_code_enabled: bool = False
    agent_employee_code_enabled: bool = False
    meal_preference_enabled: bool = False
    import_only: bool = False
    require_selfie: bool = False
    custom_questions: list[CustomQuestionDefinition] | None = None
    custom_details: list[CustomDetailDefinition] | None = None
    upload_configuration: dict[str, object] | None = None
    allow_files_from_device: bool = True
    ask_nearest_domestic_airport: bool = False
    relation_with_qualifier_enabled: bool = False
    designation_enabled: bool = False
    agency_dealership_name_enabled: bool = False
    notes: str | None = None


class IPassportSubmissionRepository(ABC):
    """Contract for passport submission persistence operations."""

    @abstractmethod
    async def get_by_id(self, submission_id: uuid.UUID) -> PassportSubmission | None: ...

    @abstractmethod
    async def get_by_id_for_update(
        self,
        submission_id: uuid.UUID,
    ) -> PassportSubmission | None:
        """Return one submission under a transaction-scoped row lock."""

        ...

    @abstractmethod
    async def get_by_upload_idempotency_key(
        self,
        group_id: uuid.UUID,
        upload_idempotency_key: str,
    ) -> PassportSubmission | None: ...

    @abstractmethod
    async def save(self, submission: PassportSubmission) -> PassportSubmission: ...

    @abstractmethod
    async def save_idempotent(
        self,
        submission: PassportSubmission,
    ) -> tuple[PassportSubmission, bool]: ...

    @abstractmethod
    async def update(self, submission: PassportSubmission) -> PassportSubmission: ...

    @abstractmethod
    async def apply_extraction_result(
        self,
        *,
        submission_id: uuid.UUID,
        expected_revision: int,
        extracted_fields: dict[str, object],
        confidence: float,
        confidence_score: dict[str, object] | None,
        mrz_raw: str | None,
        review_threshold: float = 0.85,
    ) -> PassportSubmission | None: ...

    @abstractmethod
    async def apply_extraction_failure(
        self,
        *,
        submission_id: uuid.UUID,
        expected_revision: int,
        public_message: str,
        diagnostics: dict[str, object] | None = None,
    ) -> PassportSubmission | None: ...

    @abstractmethod
    async def apply_post_submission_verification(
        self,
        *,
        submission_id: uuid.UUID,
        expected_revision: int,
        decision: str,
        verification: dict[str, object],
    ) -> PassportSubmission | None: ...

    @abstractmethod
    async def delete(self, submission_id: uuid.UUID) -> None: ...

    @abstractmethod
    async def list_by_agency(
        self,
        agency_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 50,
        status_filter: str | None = None,
        search: str | None = None,
        exclude_archived_groups: bool = False,
        created_by_user_id: uuid.UUID | None = None,
        visible_to_user: User | None = None,
    ) -> list[PassportSubmission]: ...

    @abstractmethod
    async def list_recent_dashboard_submissions(
        self,
        agency_id: uuid.UUID,
        *,
        created_by_user_id: uuid.UUID | None = None,
        visible_to_user: User | None = None,
    ) -> list[DashboardRecentSubmission]: ...

    @abstractmethod
    async def list_by_group(
        self,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int | None = 50,
        search: str | None = None,
        exclude_archived_groups: bool = False,
        created_by_user_id: uuid.UUID | None = None,
        visible_to_user: User | None = None,
        operational_only: bool = False,
    ) -> list[PassportSubmission]: ...

    @abstractmethod
    async def list_group_summaries_by_agency(
        self,
        agency_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 50,
        exclude_archived_groups: bool = True,
        created_by_user_id: uuid.UUID | None = None,
        visible_to_user: User | None = None,
    ) -> list[PassportSubmissionGroupSummary]: ...

    @abstractmethod
    async def exists_contact_in_group(
        self,
        group_id: uuid.UUID,
        *,
        client_email: str | None,
        client_phone: str | None,
        exclude_submission_id: uuid.UUID | None = None,
        scope: Literal["group", "platform"] = "group",
        additional_emails: Sequence[str] = (),
        additional_phones: Sequence[str] = (),
    ) -> bool: ...

    @abstractmethod
    async def count_by_agency(
        self,
        agency_id: uuid.UUID,
        *,
        status_filter: str | None = None,
        exclude_archived_groups: bool = False,
        created_by_user_id: uuid.UUID | None = None,
        visible_to_user: User | None = None,
    ) -> int: ...
