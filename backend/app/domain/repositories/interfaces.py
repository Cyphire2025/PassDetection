"""
Repository Interfaces (Abstract Base Classes)
=============================================
Defines the contracts that the Infrastructure layer must implement.

Rules:
  - Only abstract methods — no implementation details.
  - Methods use Domain entities as arguments and return types.
  - The Application layer depends ONLY on these interfaces,
    never on concrete SQLAlchemy repositories.

This is the Dependency Inversion Principle in action.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Sequence

from app.domain.entities.entities import (
    Agency,
    ClientGroup,
    PassportSubmission,
    QualifierSelection,
    User,
)
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
    require_selfie: bool = False
    allow_files_from_device: bool = True
    ask_nearest_domestic_airport: bool = False
    relation_with_qualifier_enabled: bool = False
    designation_enabled: bool = False
    agency_dealership_name_enabled: bool = False
    notes: str | None = None


class IUserRepository(ABC):
    """Contract for user persistence operations."""

    @abstractmethod
    async def get_by_id(self, user_id: uuid.UUID) -> User | None: ...

    @abstractmethod
    async def get_by_email(self, email: str) -> User | None: ...

    @abstractmethod
    async def save(self, user: User) -> User: ...

    @abstractmethod
    async def update(self, user: User) -> User: ...

    @abstractmethod
    async def delete(self, user_id: uuid.UUID) -> None: ...

    @abstractmethod
    async def list_by_agency(
        self, agency_id: uuid.UUID, *, skip: int = 0, limit: int = 50
    ) -> list[User]: ...


class IAgencyRepository(ABC):
    """Contract for agency persistence operations."""

    @abstractmethod
    async def get_by_id(self, agency_id: uuid.UUID) -> Agency | None: ...

    @abstractmethod
    async def get_by_email(self, email: str) -> Agency | None: ...

    @abstractmethod
    async def save(self, agency: Agency) -> Agency: ...

    @abstractmethod
    async def update(self, agency: Agency) -> Agency: ...

    @abstractmethod
    async def list_all(self, *, skip: int = 0, limit: int = 50) -> list[Agency]: ...


class IClientGroupRepository(ABC):
    """Contract for upload link persistence operations."""

    @abstractmethod
    async def get_by_id(self, link_id: uuid.UUID) -> ClientGroup | None: ...

    @abstractmethod
    async def get_by_token(self, token: str) -> ClientGroup | None: ...

    @abstractmethod
    async def save(self, link: ClientGroup) -> ClientGroup: ...

    @abstractmethod
    async def update(self, link: ClientGroup) -> ClientGroup: ...

    @abstractmethod
    async def list_by_agency(
        self,
        agency_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 50,
        status_filter: str | None = None,
        created_by_user_id: uuid.UUID | None = None,
        visible_to_user: User | None = None,
    ) -> list[ClientGroup]: ...

    @abstractmethod
    async def count_active_by_agency(
        self,
        agency_id: uuid.UUID,
        *,
        created_by_user_id: uuid.UUID | None = None,
        visible_to_user: User | None = None,
    ) -> int: ...


class IQualifierSelectionRepository(ABC):
    """Contract for short-lived public qualifier selections."""

    @abstractmethod
    async def get_by_token_hash(
        self,
        group_id: uuid.UUID,
        token_hash: str,
        *,
        for_update: bool = False,
    ) -> QualifierSelection | None: ...

    @abstractmethod
    async def save(self, selection: QualifierSelection) -> QualifierSelection: ...

    @abstractmethod
    async def get_submission_id(
        self,
        selection_id: uuid.UUID,
    ) -> uuid.UUID | None: ...


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

class IObjectStorageRepository(ABC):
    """Contract for object storage operations (e.g., S3/MinIO)."""

    @abstractmethod
    async def upload_file(self, file_content: bytes, file_name: str, content_type: str) -> str:
        """Uploads a file and returns its storage key/path."""
        ...

    @abstractmethod
    async def get_file(self, key: str) -> bytes:
        """Downloads a file from object storage."""
        ...

    @abstractmethod
    async def get_presigned_url(self, key: str, expires_in_seconds: int = 3600) -> str:
        """Generates a presigned URL for downloading/viewing a file."""
        ...

    @abstractmethod
    async def delete_files(self, keys: list[str]) -> int:
        """Deletes files from object storage and returns the number requested for deletion."""
        ...

