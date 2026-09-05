"""Passport dependencies: focused workflow boundary."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.passports.client_submit_passport_use_case import (
    ClientSubmitPassportUseCase,
)
from app.application.use_cases.passports.confirm_passport_submission_use_case import (
    ConfirmPassportSubmissionUseCase,
)
from app.application.use_cases.passports.get_passport_submission_use_case import (
    GetPassportSubmissionUseCase,
)
from app.application.use_cases.passports.list_passport_group_summaries_use_case import (
    ListPassportGroupSummariesUseCase,
)
from app.application.use_cases.passports.list_passport_submissions_by_group_use_case import (
    ListPassportSubmissionsByGroupUseCase,
)
from app.application.use_cases.passports.list_passport_submissions_use_case import (
    ListPassportSubmissionsUseCase,
)
from app.application.use_cases.passports.reconcile_passport_upload_use_case import (
    ReconcilePassportUploadUseCase,
)
from app.application.use_cases.passports.reextract_passport_submission_use_case import (
    ReextractPassportSubmissionUseCase,
)
from app.application.use_cases.passports.retry_post_submission_verification_use_case import (
    RetryPostSubmissionVerificationUseCase,
)
from app.application.use_cases.passports.retry_public_passport_extraction_use_case import (
    RetryPublicPassportExtractionUseCase,
)
from app.application.use_cases.passports.staff_approve_passport_use_case import (
    StaffApprovePassportUseCase,
)
from app.application.use_cases.passports.submit_passport_use_case import SubmitPassportUseCase
from app.infrastructure.database.session import get_db_session
from app.infrastructure.mobile_group_capacity import SqlAlchemyGroupPassengerCapacityGuard
from app.infrastructure.processing.job_repository import PassportProcessingJobRepository
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.repositories.platform_policy_repository import PlatformPolicyRepository
from app.infrastructure.repositories.qualifier_selection_repository import (
    QualifierSelectionRepository,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository


def _get_submit_passport_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> SubmitPassportUseCase:
    return SubmitPassportUseCase(
        client_group_repo=ClientGroupRepository(session),
        passport_repo=PassportSubmissionRepository(session),
        storage_repo=MinioStorageRepository(),
        processing_job_repo=PassportProcessingJobRepository(session),
        qualifier_selection_repo=QualifierSelectionRepository(session),
        group_capacity_guard=SqlAlchemyGroupPassengerCapacityGuard(session),
    )


def _get_reconcile_passport_upload_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> ReconcilePassportUploadUseCase:
    return ReconcilePassportUploadUseCase(
        client_group_repo=ClientGroupRepository(session),
        passport_repo=PassportSubmissionRepository(session),
    )


def _get_list_passports_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> ListPassportSubmissionsUseCase:
    return ListPassportSubmissionsUseCase(passport_repo=PassportSubmissionRepository(session))


def _get_list_passport_groups_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> ListPassportGroupSummariesUseCase:
    return ListPassportGroupSummariesUseCase(passport_repo=PassportSubmissionRepository(session))


def _get_list_passports_by_group_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> ListPassportSubmissionsByGroupUseCase:
    return ListPassportSubmissionsByGroupUseCase(
        passport_repo=PassportSubmissionRepository(session)
    )


def _get_get_passport_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> GetPassportSubmissionUseCase:
    return GetPassportSubmissionUseCase(passport_repo=PassportSubmissionRepository(session))


def _get_confirm_passport_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> ConfirmPassportSubmissionUseCase:
    return ConfirmPassportSubmissionUseCase(passport_repo=PassportSubmissionRepository(session))


def _get_client_submit_passport_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> ClientSubmitPassportUseCase:
    return ClientSubmitPassportUseCase(
        passport_repo=PassportSubmissionRepository(session),
        client_group_repo=ClientGroupRepository(session),
        storage_repo=MinioStorageRepository(),
        platform_policy_provider=PlatformPolicyRepository(session),
    )


def _get_reextract_passport_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> ReextractPassportSubmissionUseCase:
    return ReextractPassportSubmissionUseCase(
        passport_repo=PassportSubmissionRepository(session),
        processing_job_repo=PassportProcessingJobRepository(session),
    )


def _get_retry_public_extraction_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> RetryPublicPassportExtractionUseCase:
    return RetryPublicPassportExtractionUseCase(
        passport_repo=PassportSubmissionRepository(session),
        client_group_repo=ClientGroupRepository(session),
        processing_job_repo=PassportProcessingJobRepository(session),
    )


def _get_staff_approve_passport_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> StaffApprovePassportUseCase:
    return StaffApprovePassportUseCase(passport_repo=PassportSubmissionRepository(session))


def _get_retry_post_submission_verification_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> RetryPostSubmissionVerificationUseCase:
    return RetryPostSubmissionVerificationUseCase(
        passport_repo=PassportSubmissionRepository(session)
    )
