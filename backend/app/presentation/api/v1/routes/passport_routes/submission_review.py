"""Stable passport review API and explicit compatibility exports."""

import uuid as uuid
from dataclasses import replace as replace

from fastapi import APIRouter as APIRouter
from fastapi import BackgroundTasks as BackgroundTasks
from fastapi import Depends as Depends
from fastapi import Header as Header
from fastapi import HTTPException as HTTPException
from fastapi import Response as Response
from fastapi import status as status
from fastapi.responses import JSONResponse as JSONResponse
from sqlalchemy import select as select
from sqlalchemy.ext.asyncio import AsyncSession as AsyncSession

from app.application.dtos.passport_dtos import (
    PassportSubmissionOutputDTO as PassportSubmissionOutputDTO,
)
from app.application.mobile.passenger_change_propagation import (
    propagate_mobile_passenger_change as propagate_mobile_passenger_change,
)
from app.application.security.authorization_policy import AuthorizationPolicy as AuthorizationPolicy
from app.application.use_cases.passports.client_submit_passport_use_case import (
    ClientSubmitPassportUseCase as ClientSubmitPassportUseCase,
)
from app.application.use_cases.passports.confirm_passport_submission_use_case import (
    ConfirmPassportSubmissionUseCase as ConfirmPassportSubmissionUseCase,
)
from app.application.use_cases.passports.get_passport_submission_use_case import (
    GetPassportSubmissionUseCase as GetPassportSubmissionUseCase,
)
from app.application.use_cases.passports.reextract_passport_submission_use_case import (
    ReextractPassportSubmissionUseCase as ReextractPassportSubmissionUseCase,
)
from app.application.use_cases.passports.retry_post_submission_verification_use_case import (
    RetryPostSubmissionVerificationUseCase as RetryPostSubmissionVerificationUseCase,
)
from app.application.use_cases.passports.staff_approve_passport_use_case import (
    StaffApprovalResult as StaffApprovalResult,
)
from app.application.use_cases.passports.staff_approve_passport_use_case import (
    StaffApprovePassportUseCase as StaffApprovePassportUseCase,
)
from app.core.logging.logger import get_logger as get_logger
from app.domain.entities.entities import StaffApprovalOutcome as StaffApprovalOutcome
from app.domain.entities.entities import User as User
from app.domain.exceptions.exceptions import AuthorizationError as AuthorizationError
from app.domain.exceptions.exceptions import ConflictError as ConflictError
from app.domain.exceptions.exceptions import EntityNotFoundError as EntityNotFoundError
from app.domain.exceptions.exceptions import PassDetectionError as PassDetectionError
from app.domain.exceptions.exceptions import StaffApprovalStaleError as StaffApprovalStaleError
from app.domain.exceptions.exceptions import (
    StaffApprovalUnavailableError as StaffApprovalUnavailableError,
)
from app.domain.exceptions.exceptions import StorageError as StorageError
from app.infrastructure.database.models import ClientGroupModel as ClientGroupModel
from app.infrastructure.database.session import get_db_session as get_db_session
from app.infrastructure.documents.storage_cleanup import (
    process_storage_cleanup_job as process_storage_cleanup_job,
)
from app.infrastructure.ecr import dispatch_passport_ecr_checks as dispatch_passport_ecr_checks
from app.infrastructure.observability.operational_events import OperationalEvent as OperationalEvent
from app.infrastructure.observability.operational_events import (
    record_operational_event as record_operational_event,
)
from app.infrastructure.processing.dispatcher import (
    queued_job_needs_redelivery as queued_job_needs_redelivery,
)
from app.infrastructure.processing.job_repository import (
    PassportProcessingJobRepository as PassportProcessingJobRepository,
)
from app.infrastructure.repositories.audit_log_repository import (
    AuditLogRepository as AuditLogRepository,
)
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository as PassportSubmissionRepository,
)
from app.infrastructure.repositories.sensitive_read_audit import (
    record_sensitive_read as record_sensitive_read,
)
from app.infrastructure.storage.minio_repository import (
    MinioStorageRepository as MinioStorageRepository,
)
from app.infrastructure.verification.dispatcher import (
    PostSubmissionVerificationDispatcher as PostSubmissionVerificationDispatcher,
)
from app.infrastructure.verification.job_repository import (
    PostSubmissionVerificationJob as PostSubmissionVerificationJob,
)
from app.infrastructure.verification.job_repository import (
    PostSubmissionVerificationJobRepository as PostSubmissionVerificationJobRepository,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    ClientSubmitPassportRequest as ClientSubmitPassportRequest,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    ConfirmPassportSubmissionRequest as ConfirmPassportSubmissionRequest,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportSubmissionResponse as PassportSubmissionResponse,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    StaffApprovePassportRequest as StaffApprovePassportRequest,
)
from app.presentation.dependencies.auth import get_current_active_user as get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf as require_cookie_csrf

from .dependencies import (
    _get_client_submit_passport_use_case as _get_client_submit_passport_use_case,
)
from .dependencies import _get_confirm_passport_use_case as _get_confirm_passport_use_case
from .dependencies import _get_get_passport_use_case as _get_get_passport_use_case
from .dependencies import _get_reextract_passport_use_case as _get_reextract_passport_use_case
from .dependencies import (
    _get_retry_post_submission_verification_use_case as _get_retry_post_submission_verification_use_case,
)
from .dependencies import (
    _get_staff_approve_passport_use_case as _get_staff_approve_passport_use_case,
)
from .processing_support import _dispatch_processing_job as _dispatch_processing_job
from .response_support import _ensure_submission_qr as _ensure_submission_qr
from .response_support import _response_from_dto as _response_from_dto
from .response_support import _response_from_submission as _response_from_submission
from .submission_contact import (
    require_verified_submission_contact as require_verified_submission_contact,
)
from .submission_execution import execute_client_review as execute_client_review
from .submission_review_approval import router as _approval_router
from .submission_review_approval import staff_approve_passport as staff_approve_passport
from .submission_review_client import client_submit_passport as client_submit_passport
from .submission_review_client import router as _client_router
from .submission_review_confirmation import confirm_passport as confirm_passport
from .submission_review_confirmation import router as _confirmation_router
from .submission_review_processing import cancel_passport_processing as cancel_passport_processing
from .submission_review_processing import reextract_passport as reextract_passport
from .submission_review_processing import (
    retry_post_submission_verification as retry_post_submission_verification,
)
from .submission_review_processing import router as _processing_router
from .submission_review_read import get_passport as get_passport
from .submission_review_read import router as _read_router
from .submission_review_support import (
    _cleanup_uncommitted_promotions as _cleanup_uncommitted_promotions,
)
from .submission_review_support import (
    _dispatch_committed_verification as _dispatch_committed_verification,
)
from .submission_review_support import _schedule_review_history as _schedule_review_history
from .submission_review_support import (
    _staff_approval_conflict_response as _staff_approval_conflict_response,
)
from .submission_review_support import logger as logger
from .submission_side_effects import stage_submission_side_effects as stage_submission_side_effects

router = APIRouter()
router.include_router(_read_router)
router.include_router(_client_router)
router.include_router(_approval_router)
router.include_router(_processing_router)
router.include_router(_confirmation_router)
