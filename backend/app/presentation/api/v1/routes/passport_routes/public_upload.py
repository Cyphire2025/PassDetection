"""Stable public passport upload API and explicit compatibility exports."""

import mimetypes as mimetypes
import uuid as uuid
from typing import Annotated as Annotated
from typing import Literal as Literal

from fastapi import APIRouter as APIRouter
from fastapi import BackgroundTasks as BackgroundTasks
from fastapi import Depends as Depends
from fastapi import File as File
from fastapi import Form as Form
from fastapi import Header as Header
from fastapi import HTTPException as HTTPException
from fastapi import Response as Response
from fastapi import UploadFile as UploadFile
from fastapi import status as status
from fastapi.responses import StreamingResponse as StreamingResponse
from sqlalchemy import select as select
from sqlalchemy.ext.asyncio import AsyncSession as AsyncSession

from app.application.dtos.passport_dtos import (
    passport_submission_output_from_entity as passport_submission_output_from_entity,
)
from app.application.mobile.passenger_change_propagation import (
    propagate_mobile_passenger_change as propagate_mobile_passenger_change,
)
from app.application.security.public_upload_capability import (
    public_upload_is_active as public_upload_is_active,
)
from app.application.use_cases.passports.reconcile_passport_upload_use_case import (
    ReconcilePassportUploadUseCase as ReconcilePassportUploadUseCase,
)
from app.application.use_cases.passports.retry_public_passport_extraction_use_case import (
    RetryPublicPassportExtractionUseCase as RetryPublicPassportExtractionUseCase,
)
from app.application.use_cases.passports.submit_passport_use_case import (
    SubmitPassportUseCase as SubmitPassportUseCase,
)
from app.core.logging.logger import get_logger as get_logger
from app.core.security.upload_session import (
    upload_session_matches_identifier as upload_session_matches_identifier,
)
from app.domain.entities.entities import (
    OFFICE_VISIBLE_PASSPORT_STATUS_VALUES as OFFICE_VISIBLE_PASSPORT_STATUS_VALUES,
)
from app.domain.entities.entities import GroupStatus as GroupStatus
from app.domain.entities.entities import PassportSubmission as PassportSubmission
from app.domain.exceptions.exceptions import EntityNotFoundError as EntityNotFoundError
from app.domain.exceptions.exceptions import PassDetectionError as PassDetectionError
from app.domain.exceptions.exceptions import StorageError as StorageError
from app.domain.value_objects.upload_configuration import (
    MAX_PUBLIC_DOCUMENT_BYTES as MAX_PUBLIC_DOCUMENT_BYTES,
)
from app.domain.value_objects.upload_configuration import configuration_for as configuration_for
from app.domain.value_objects.upload_configuration import (
    validate_visa_photo_source as validate_visa_photo_source,
)
from app.infrastructure.database.models import ClientGroupModel as ClientGroupModel
from app.infrastructure.database.session import get_db_session as get_db_session
from app.infrastructure.documents.storage_cleanup import (
    process_storage_cleanup_job as process_storage_cleanup_job,
)
from app.infrastructure.documents.storage_cleanup import (
    stage_storage_cleanup_jobs as stage_storage_cleanup_jobs,
)
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
from app.infrastructure.repositories.client_group_repository import (
    ClientGroupRepository as ClientGroupRepository,
)
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository as PassportSubmissionRepository,
)
from app.infrastructure.storage.minio_repository import (
    MinioStorageRepository as MinioStorageRepository,
)
from app.presentation.api.v1.object_streaming import (
    private_object_streaming_response as private_object_streaming_response,
)
from app.presentation.api.v1.response_contracts import binary_responses as binary_responses
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportSubmissionResponse as PassportSubmissionResponse,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    ReconcilePassportUploadRequest as ReconcilePassportUploadRequest,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    ReconcilePassportUploadResponse as ReconcilePassportUploadResponse,
)

from .dependencies import (
    _get_reconcile_passport_upload_use_case as _get_reconcile_passport_upload_use_case,
)
from .dependencies import (
    _get_retry_public_extraction_use_case as _get_retry_public_extraction_use_case,
)
from .dependencies import _get_submit_passport_use_case as _get_submit_passport_use_case
from .public_processing_support import dispatch_public_extraction as dispatch_public_extraction
from .public_security import _require_public_upload_credential as _require_public_upload_credential
from .public_security import _validated_upload_file as _validated_upload_file
from .public_upload_discard import discard_public_upload as discard_public_upload
from .public_upload_discard import router as _discard_router
from .public_upload_documents import (
    validate_public_upload_documents as validate_public_upload_documents,
)
from .public_upload_images import (
    get_public_upload_passport_document as get_public_upload_passport_document,
)
from .public_upload_images import (
    get_public_upload_passport_image as get_public_upload_passport_image,
)
from .public_upload_images import router as _images_router
from .public_upload_preparation import prepare_public_upload_file as prepare_public_upload_file
from .public_upload_preparation import router as _preparation_router
from .public_upload_scope import _get_public_upload_submission as _get_public_upload_submission
from .public_upload_scope import logger as logger
from .public_upload_status import get_upload_passport_status as get_upload_passport_status
from .public_upload_status import reconcile_passport_upload as reconcile_passport_upload
from .public_upload_status import router as _status_router
from .public_upload_status import scan_again_public_upload as scan_again_public_upload
from .public_upload_submission import router as _submission_router
from .public_upload_submission import upload_passport as upload_passport
from .response_support import _response_from_dto as _response_from_dto

router = APIRouter()
router.include_router(_preparation_router)
router.include_router(_submission_router)
router.include_router(_status_router)
router.include_router(_images_router)
router.include_router(_discard_router)
