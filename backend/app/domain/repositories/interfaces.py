"""Compatibility imports for focused domain owners; existing caller paths are retained."""

from app.domain.repositories.client_groups import (
    IClientGroupRepository as IClientGroupRepository,
)
from app.domain.repositories.client_groups import (
    IQualifierSelectionRepository as IQualifierSelectionRepository,
)
from app.domain.repositories.identity import (
    IAgencyRepository as IAgencyRepository,
)
from app.domain.repositories.identity import (
    IUserRepository as IUserRepository,
)
from app.domain.repositories.object_storage import (
    IObjectStorageRepository as IObjectStorageRepository,
)
from app.domain.repositories.passport_submissions import (
    IPassportSubmissionRepository as IPassportSubmissionRepository,
)
from app.domain.repositories.passport_submissions import (
    PassportSubmissionGroupSummary as PassportSubmissionGroupSummary,
)
