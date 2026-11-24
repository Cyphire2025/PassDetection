"""Stable SQLAlchemy passport repository facade over explicit persistence/query owners."""

from __future__ import annotations

import hashlib as hashlib
import uuid as uuid
from collections.abc import Sequence as Sequence
from typing import Any as Any
from typing import Literal as Literal

from sqlalchemy import (
    Select as Select,
)
from sqlalchemy import (
    and_ as and_,
)
from sqlalchemy import (
    case as case,
)
from sqlalchemy import (
    delete as delete,
)
from sqlalchemy import (
    func as func,
)
from sqlalchemy import (
    or_ as or_,
)
from sqlalchemy import (
    select as select,
)
from sqlalchemy.exc import IntegrityError as IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession as AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy as AuthorizationPolicy
from app.core.logging.logger import get_logger as get_logger
from app.domain.entities.entities import (
    CONFIRMED_PASSPORT_STATUS_VALUES as CONFIRMED_PASSPORT_STATUS_VALUES,
)
from app.domain.entities.entities import (
    OFFICE_VISIBLE_PASSPORT_STATUS_VALUES as OFFICE_VISIBLE_PASSPORT_STATUS_VALUES,
)
from app.domain.entities.entities import (
    PENDING_REVIEW_PASSPORT_STATUS_VALUES as PENDING_REVIEW_PASSPORT_STATUS_VALUES,
)
from app.domain.entities.entities import (
    GroupStatus as GroupStatus,
)
from app.domain.entities.entities import (
    PassportExtractionStatus as PassportExtractionStatus,
)
from app.domain.entities.entities import (
    PassportProcessingStatus as PassportProcessingStatus,
)
from app.domain.entities.entities import (
    PassportSubmission as PassportSubmission,
)
from app.domain.entities.entities import (
    User as User,
)
from app.domain.exceptions.exceptions import EntityNotFoundError as EntityNotFoundError
from app.domain.repositories.interfaces import (
    IPassportSubmissionRepository as IPassportSubmissionRepository,
)
from app.domain.repositories.interfaces import (
    PassportSubmissionGroupSummary as PassportSubmissionGroupSummary,
)
from app.domain.value_objects.dashboard_summary import (
    RECENT_DASHBOARD_LIMIT as RECENT_DASHBOARD_LIMIT,
)
from app.domain.value_objects.dashboard_summary import (
    RECENT_DASHBOARD_TEXT_LIMIT as RECENT_DASHBOARD_TEXT_LIMIT,
)
from app.domain.value_objects.dashboard_summary import (
    DashboardProjectionLimitError as DashboardProjectionLimitError,
)
from app.domain.value_objects.dashboard_summary import (
    DashboardRecentSubmission as DashboardRecentSubmission,
)
from app.domain.value_objects.phone_number import (
    normalize_phone_number as normalize_phone_number,
)
from app.domain.value_objects.phone_number import (
    phone_storage_variants as phone_storage_variants,
)
from app.infrastructure.database.models import (
    ClientGroupModel as ClientGroupModel,
)
from app.infrastructure.database.models import (
    ManagerGroupAccessModel as ManagerGroupAccessModel,
)
from app.infrastructure.database.models import (
    PassportSubmissionModel as PassportSubmissionModel,
)
from app.infrastructure.database.search_expressions import (
    passport_search_fields as passport_search_fields,
)
from app.infrastructure.database.search_expressions import (
    substring_predicate as substring_predicate,
)
from app.infrastructure.repositories import passport_submission_contacts as _contacts
from app.infrastructure.repositories import passport_submission_groups as _groups
from app.infrastructure.repositories import passport_submission_mapping as _mapping
from app.infrastructure.repositories import passport_submission_persistence as _persistence
from app.infrastructure.repositories import passport_submission_processing as _processing
from app.infrastructure.repositories import passport_submission_queries as _queries
from app.infrastructure.repositories import passport_submission_reads as _reads
from app.infrastructure.repositories.operational_roster import (
    operational_roster_member as operational_roster_member,
)
from app.infrastructure.verification.job_repository import (
    PostSubmissionVerificationJobRepository as PostSubmissionVerificationJobRepository,
)

logger = get_logger(__name__)


class PassportSubmissionRepository(IPassportSubmissionRepository):
    """Submission persistence with the original transaction and visibility contract."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    _to_entity = staticmethod(_mapping._to_entity)

    _to_model = staticmethod(_mapping._to_model)

    async def get_by_id(self, submission_id: uuid.UUID) -> PassportSubmission | None:
        return await _reads.get_by_id(self._session, submission_id)

    async def get_by_upload_idempotency_key(
        self, group_id: uuid.UUID, upload_idempotency_key: str
    ) -> PassportSubmission | None:
        return await _reads.get_by_upload_idempotency_key(
            self._session, group_id, upload_idempotency_key
        )

    async def get_by_id_for_update(self, submission_id: uuid.UUID) -> PassportSubmission | None:
        "Lock one submission until the caller commits or rolls back."

        return await _reads.get_by_id_for_update(self._session, submission_id)

    async def save(self, submission: PassportSubmission) -> PassportSubmission:
        return await _persistence.save(self._session, submission)

    async def save_idempotent(
        self, submission: PassportSubmission
    ) -> tuple[PassportSubmission, bool]:
        return await _persistence.save_idempotent(self._session, submission)

    async def update(self, submission: PassportSubmission) -> PassportSubmission:
        return await _persistence.update(self._session, submission)

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
    ) -> PassportSubmission | None:
        return await _processing.apply_extraction_result(
            self._session,
            submission_id=submission_id,
            expected_revision=expected_revision,
            extracted_fields=extracted_fields,
            confidence=confidence,
            confidence_score=confidence_score,
            mrz_raw=mrz_raw,
            review_threshold=review_threshold,
        )

    async def apply_extraction_failure(
        self,
        *,
        submission_id: uuid.UUID,
        expected_revision: int,
        public_message: str,
        diagnostics: dict[str, object] | None = None,
    ) -> PassportSubmission | None:
        return await _processing.apply_extraction_failure(
            self._session,
            submission_id=submission_id,
            expected_revision=expected_revision,
            public_message=public_message,
            diagnostics=diagnostics,
        )

    async def apply_post_submission_verification(
        self,
        *,
        submission_id: uuid.UUID,
        expected_revision: int,
        decision: str,
        verification: dict[str, object],
    ) -> PassportSubmission | None:
        return await _processing.apply_post_submission_verification(
            self._session,
            submission_id=submission_id,
            expected_revision=expected_revision,
            decision=decision,
            verification=verification,
        )

    _apply_extraction_fields = staticmethod(_mapping._apply_extraction_fields)

    async def delete(self, submission_id: uuid.UUID) -> None:
        return await _persistence.delete_submission(self._session, submission_id)

    _office_visible_statuses = staticmethod(_queries._office_visible_statuses)

    _status_filter_values = staticmethod(_queries._status_filter_values)

    _apply_manager_group_scope = staticmethod(_queries._apply_manager_group_scope)

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
    ) -> list[PassportSubmission]:
        return await _reads.list_by_agency(
            self._session,
            agency_id,
            skip=skip,
            limit=limit,
            status_filter=status_filter,
            search=search,
            exclude_archived_groups=exclude_archived_groups,
            created_by_user_id=created_by_user_id,
            visible_to_user=visible_to_user,
        )

    def _agency_scope(
        self,
        stmt: Any,
        agency_id: uuid.UUID,
        *,
        status_filter: str | None,
        exclude_archived_groups: bool,
        created_by_user_id: uuid.UUID | None,
        visible_to_user: User | None,
    ) -> Any:
        "One canonical scope for full lists, counts and the bounded preview."

        return _queries._agency_scope(
            stmt,
            agency_id,
            status_filter=status_filter,
            exclude_archived_groups=exclude_archived_groups,
            created_by_user_id=created_by_user_id,
            visible_to_user=visible_to_user,
        )

    async def list_recent_dashboard_submissions(
        self,
        agency_id: uuid.UUID,
        *,
        created_by_user_id: uuid.UUID | None = None,
        visible_to_user: User | None = None,
    ) -> list[DashboardRecentSubmission]:
        return await _reads.list_recent_dashboard_submissions(
            self._session,
            agency_id,
            created_by_user_id=created_by_user_id,
            visible_to_user=visible_to_user,
        )

    def _group_scope(
        self,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
        *,
        exclude_archived_groups: bool = False,
        created_by_user_id: uuid.UUID | None = None,
        visible_to_user: User | None = None,
        operational_only: bool = False,
    ) -> Select[tuple[PassportSubmissionModel]]:
        return _queries._group_scope(
            agency_id,
            group_id,
            exclude_archived_groups=exclude_archived_groups,
            created_by_user_id=created_by_user_id,
            visible_to_user=visible_to_user,
            operational_only=operational_only,
        )

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
    ) -> list[PassportSubmission]:
        return await _reads.list_by_group(
            self._session,
            agency_id,
            group_id,
            skip=skip,
            limit=limit,
            search=search,
            exclude_archived_groups=exclude_archived_groups,
            created_by_user_id=created_by_user_id,
            visible_to_user=visible_to_user,
            operational_only=operational_only,
        )

    def _apply_search(self, stmt, search: str | None):  # type: ignore[no-untyped-def]
        return _queries._apply_search(stmt, search)

    async def list_group_summaries_by_agency(
        self,
        agency_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 50,
        exclude_archived_groups: bool = True,
        created_by_user_id: uuid.UUID | None = None,
        visible_to_user: User | None = None,
    ) -> list[PassportSubmissionGroupSummary]:
        return await _groups.list_group_summaries_by_agency(
            self._session,
            agency_id,
            skip=skip,
            limit=limit,
            exclude_archived_groups=exclude_archived_groups,
            created_by_user_id=created_by_user_id,
            visible_to_user=visible_to_user,
        )

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
    ) -> bool:
        return await _contacts.exists_contact_in_group(
            self._session,
            group_id,
            client_email=client_email,
            client_phone=client_phone,
            exclude_submission_id=exclude_submission_id,
            scope=scope,
            additional_emails=additional_emails,
            additional_phones=additional_phones,
        )

    async def count_by_agency(
        self,
        agency_id: uuid.UUID,
        *,
        status_filter: str | None = None,
        exclude_archived_groups: bool = False,
        created_by_user_id: uuid.UUID | None = None,
        visible_to_user: User | None = None,
    ) -> int:
        return await _reads.count_by_agency(
            self._session,
            agency_id,
            status_filter=status_filter,
            exclude_archived_groups=exclude_archived_groups,
            created_by_user_id=created_by_user_id,
            visible_to_user=visible_to_user,
        )
