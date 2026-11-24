"""Compatibility imports for focused domain owners; existing caller paths are retained."""

from app.domain.entities.client_group import ClientGroup as ClientGroup
from app.domain.entities.enums import (
    CONFIRMED_PASSPORT_STATUS_VALUES as CONFIRMED_PASSPORT_STATUS_VALUES,
)
from app.domain.entities.enums import (
    OFFICE_VISIBLE_PASSPORT_STATUS_VALUES as OFFICE_VISIBLE_PASSPORT_STATUS_VALUES,
)
from app.domain.entities.enums import (
    OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES as OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES,
)
from app.domain.entities.enums import (
    PENDING_REVIEW_PASSPORT_STATUS_VALUES as PENDING_REVIEW_PASSPORT_STATUS_VALUES,
)
from app.domain.entities.enums import (
    RETRYABLE_POST_SUBMISSION_PROVIDER_STATUSES as RETRYABLE_POST_SUBMISSION_PROVIDER_STATUSES,
)
from app.domain.entities.enums import (
    GroupStatus as GroupStatus,
)
from app.domain.entities.enums import (
    PassportExtractionStatus as PassportExtractionStatus,
)
from app.domain.entities.enums import (
    PassportProcessingStatus as PassportProcessingStatus,
)
from app.domain.entities.enums import (
    StaffApprovalOutcome as StaffApprovalOutcome,
)
from app.domain.entities.enums import (
    UserRole as UserRole,
)
from app.domain.entities.identity import Agency as Agency
from app.domain.entities.identity import User as User
from app.domain.entities.passport_submission import PassportSubmission as PassportSubmission
from app.domain.entities.qualifier_selection import QualifierSelection as QualifierSelection
