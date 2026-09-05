"""Document distribution router and backwards-compatible exports."""

# ruff: noqa: F401
import asyncio
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import wraps
from time import perf_counter
from typing import Annotated, Literal, ParamSpec, TypeVar, cast

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.passenger_change_propagation import propagate_mobile_passenger_change
from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.whatsapp.document_templates import (
    default_document_message_content,
    render_document_message,
)
from app.application.use_cases.whatsapp.group_submission_matching import (
    RecipientForComparison,
    SubmissionForComparison,
    compare_group_submissions,
)
from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.domain.entities.entities import PassportSubmission, User, UserRole
from app.domain.exceptions.exceptions import AuthorizationError, StorageError
from app.domain.value_objects.travel_document_taxonomy import (
    DOCUMENT_TYPES,
    DOMESTIC_ONWARD_DOCUMENT_TYPE,
    DOMESTIC_RETURN_DOCUMENT_TYPE,
    INTERNATIONAL_ONWARD_DOCUMENT_TYPE,
    INTERNATIONAL_RETURN_DOCUMENT_TYPE,
    OTHER_DOCUMENT_TYPE,
    VISA_DOCUMENT_TYPE,
    document_type_label,
)
from app.infrastructure.database.email_models import EmailArtifactDocumentModel
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    DocumentUploadChunkModel,
    DocumentWhatsAppDeliveryModel,
    PassportSubmissionModel,
    UserModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.documents.distribution_capacity import (
    MAX_DISTRIBUTION_ASSIGNMENT_ROWS_PER_SCOPE,
    DocumentDistributionCapacityError,
    enforce_distribution_scope_capacity,
)
from app.infrastructure.documents.distribution_ingestion import (
    TravelDocumentFile,
    TravelDocumentIngestionService,
    automatic_passenger_matches,
)
from app.infrastructure.documents.document_matcher import (
    MAX_SUPPLEMENTAL_IDENTIFIERS_PER_PASSENGER,
    MAX_SUPPLEMENTAL_IDENTIFIERS_PER_REQUEST,
    ClassifiedDocument,
    DocumentMatcher,
    DocumentParserUnavailableError,
    MatchResult,
    PassengerIdentifier,
    UnsupportedDocumentBatchFormatError,
    classify_documents_bounded,
)
from app.infrastructure.documents.pdf_parser_sandbox import bounded_pdf_batch_timeout_seconds
from app.infrastructure.documents.storage_cleanup import (
    persist_storage_cleanup_job,
    process_storage_cleanup_job,
    stage_storage_cleanup_jobs,
)
from app.infrastructure.documents.storage_transfers import finish_cleanup_despite_cancellation
from app.infrastructure.documents.verification_staging import (
    StagedDocumentReceipt,
    VerificationReceiptBatchTooLargeError,
    VerificationReceiptError,
    VerificationReceiptExpiredError,
    VerificationReceiptScopeChangedError,
    VerificationStagingInput,
    cleanup_staged_storage_keys,
    decode_verification_receipts,
    stage_verified_documents,
    staged_document_chunk_fingerprint,
    validate_verification_receipt_token_batch,
    verification_scope_fingerprints,
)
from app.infrastructure.export.document_assignment_excel_exporter import (
    build_document_assignment_workbook,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.security.upload_security import UploadSecurityContext
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.document_chunk_uploads import (
    acquire_document_upload_advisory_lock,
    acquire_document_upload_scope_advisory_lock,
    document_chunk_fingerprint,
    new_document_chunk_receipt,
    resolve_concurrent_document_chunk_replay,
    resolve_document_chunk_metadata,
    validate_document_chunk_size,
    validate_existing_document_chunk,
    validate_next_document_chunk,
)
from app.presentation.api.v1.document_uploads import (
    MAX_DOCUMENT_BATCH_BYTES,
    read_bounded_document_uploads,
)
from app.presentation.api.v1.routes import (
    document_distribution_delivery_support as _delivery_support,
)
from app.presentation.api.v1.routes import document_distribution_review_support as _review_support
from app.presentation.api.v1.routes.document_distribution_assignments import (
    delete_distribution_documents as delete_distribution_documents,
)
from app.presentation.api.v1.routes.document_distribution_assignments import (
    router as _assignments_router,
)
from app.presentation.api.v1.routes.document_distribution_assignments import (
    unassign_distribution_documents as unassign_distribution_documents,
)
from app.presentation.api.v1.routes.document_distribution_delivery import (
    _lock_retry_document_deliveries as _lock_retry_document_deliveries,
)
from app.presentation.api.v1.routes.document_distribution_delivery import (
    get_document_delivery_tracking as get_document_delivery_tracking,
)
from app.presentation.api.v1.routes.document_distribution_delivery import (
    preview_document_whatsapp_broadcast as preview_document_whatsapp_broadcast,
)
from app.presentation.api.v1.routes.document_distribution_delivery import router as _delivery_router
from app.presentation.api.v1.routes.document_distribution_delivery import (
    send_document_whatsapp_broadcast as send_document_whatsapp_broadcast,
)
from app.presentation.api.v1.routes.document_distribution_delivery_preview import (
    _build_document_delivery_preview as _build_document_delivery_preview,
)
from app.presentation.api.v1.routes.document_distribution_groups_read import (
    _load_document_review as _load_document_review,
)
from app.presentation.api.v1.routes.document_distribution_groups_read import (
    export_document_assignments as export_document_assignments,
)
from app.presentation.api.v1.routes.document_distribution_groups_read import (
    get_document_review as get_document_review,
)
from app.presentation.api.v1.routes.document_distribution_groups_read import (
    list_document_groups as list_document_groups,
)
from app.presentation.api.v1.routes.document_distribution_groups_read import (
    router as _groups_read_router,
)
from app.presentation.api.v1.routes.document_distribution_matching import (
    _linked_document_match_identifiers as _linked_document_match_identifiers,
)
from app.presentation.api.v1.routes.document_distribution_matching import (
    _linked_whatsapp_recipients as _linked_whatsapp_recipients,
)
from app.presentation.api.v1.routes.document_distribution_matching import (
    _read_linked_document_match_source as _read_linked_document_match_source,
)
from app.presentation.api.v1.routes.document_distribution_queries import (
    _all_group_documents as _all_group_documents,
)
from app.presentation.api.v1.routes.document_distribution_queries import (
    _enforce_group_document_assignment_capacity as _enforce_group_document_assignment_capacity,
)
from app.presentation.api.v1.routes.document_distribution_queries import (
    _first_blocking_processing_upload_id as _first_blocking_processing_upload_id,
)
from app.presentation.api.v1.routes.document_distribution_queries import (
    _latest_document_batch as _latest_document_batch,
)
from app.presentation.api.v1.routes.document_distribution_queries import (
    _refresh_distribution_batches as _refresh_distribution_batches,
)
from app.presentation.api.v1.routes.document_distribution_responses import (
    _batch_response as _batch_response,
)
from app.presentation.api.v1.routes.document_distribution_responses import (
    _document_response as _document_response,
)
from app.presentation.api.v1.routes.document_distribution_reupload import (
    reupload_passenger_document as reupload_passenger_document,
)
from app.presentation.api.v1.routes.document_distribution_reupload import router as _reupload_router
from app.presentation.api.v1.routes.document_distribution_save import router as _save_router
from app.presentation.api.v1.routes.document_distribution_save import save_batch as save_batch
from app.presentation.api.v1.routes.document_distribution_scope import (
    _detach_distribution_batch_before_long_processing as _detach_distribution_batch_before_long_processing,
)
from app.presentation.api.v1.routes.document_distribution_scope import (
    _get_authorized_group as _get_authorized_group,
)
from app.presentation.api.v1.routes.document_distribution_scope import (
    _get_visible_document_batch as _get_visible_document_batch,
)
from app.presentation.api.v1.routes.document_distribution_scope import (
    _group_passengers as _group_passengers,
)
from app.presentation.api.v1.routes.document_distribution_scope import (
    _lock_active_document_scope as _lock_active_document_scope,
)
from app.presentation.api.v1.routes.document_distribution_scope import (
    _lock_and_validate_document_match_scope as _lock_and_validate_document_match_scope,
)
from app.presentation.api.v1.routes.document_distribution_scope import (
    _lock_document_passenger_roster as _lock_document_passenger_roster,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    _REQUEST_STAGING_CLEANUP_KEYS as _REQUEST_STAGING_CLEANUP_KEYS,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    _RETRYABLE_STAGING_HTTP_STATUSES as _RETRYABLE_STAGING_HTTP_STATUSES,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    DOCUMENT_DELIVERY_ACCEPTED_STATUSES as DOCUMENT_DELIVERY_ACCEPTED_STATUSES,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    DOCUMENT_DELIVERY_ACTIVE_POLL_SECONDS as DOCUMENT_DELIVERY_ACTIVE_POLL_SECONDS,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    DOCUMENT_DELIVERY_IN_PROGRESS_STATUSES as DOCUMENT_DELIVERY_IN_PROGRESS_STATUSES,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    DOCUMENT_DELIVERY_STORAGE_REQUIRED_STATUSES as DOCUMENT_DELIVERY_STORAGE_REQUIRED_STATUSES,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    DOCUMENT_DELIVERY_WEBHOOK_GRACE as DOCUMENT_DELIVERY_WEBHOOK_GRACE,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    DOCUMENT_DELIVERY_WEBHOOK_POLL_SECONDS as DOCUMENT_DELIVERY_WEBHOOK_POLL_SECONDS,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    DOCUMENT_RESPONSE_RENDER_WINDOW as DOCUMENT_RESPONSE_RENDER_WINDOW,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    SHARED_WHATSAPP_DESTINATION_REASON as SHARED_WHATSAPP_DESTINATION_REASON,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    DocumentDeliveryDecision as DocumentDeliveryDecision,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    _document_assignment_export_rows as _document_assignment_export_rows,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    _document_delivery_decision as _document_delivery_decision,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    _document_delivery_poll_after_seconds as _document_delivery_poll_after_seconds,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    _document_match_roster_snapshot as _document_match_roster_snapshot,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    _linked_document_match_source_from_models as _linked_document_match_source_from_models,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    _LinkedDocumentMatchSource as _LinkedDocumentMatchSource,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    _owner_scope_for as _owner_scope_for,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    _passenger_review_rows as _passenger_review_rows,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    _passport_number as _passport_number,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    _physical_file_accounting as _physical_file_accounting,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    _preferred_document_message_content as _preferred_document_message_content,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    _processing_batch_response as _processing_batch_response,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    _safe_filename as _safe_filename,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    _snapshot_value as _snapshot_value,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    _submitted_statuses as _submitted_statuses,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    _UploadParameters as _UploadParameters,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    _UploadResult as _UploadResult,
)
from app.presentation.api.v1.routes.document_distribution_shared import logger as logger
from app.presentation.api.v1.routes.document_distribution_storage import (
    _cleanup_distribution_storage_keys as _cleanup_distribution_storage_keys,
)
from app.presentation.api.v1.routes.document_distribution_storage import (
    _cleanup_remembered_request_staging as _cleanup_remembered_request_staging,
)
from app.presentation.api.v1.routes.document_distribution_storage import (
    _ConcurrentDocumentChunkReplay as _ConcurrentDocumentChunkReplay,
)
from app.presentation.api.v1.routes.document_distribution_storage import (
    _released_document_passenger_ids as _released_document_passenger_ids,
)
from app.presentation.api.v1.routes.document_distribution_storage import (
    _remember_request_staging_keys as _remember_request_staging_keys,
)
from app.presentation.api.v1.routes.document_distribution_storage import (
    _with_staging_cleanup as _with_staging_cleanup,
)
from app.presentation.api.v1.routes.document_distribution_upload import router as _upload_router
from app.presentation.api.v1.routes.document_distribution_upload import (
    upload_documents as upload_documents,
)
from app.presentation.api.v1.routes.document_distribution_upload_abort import (
    abort_incomplete_distribution_upload as abort_incomplete_distribution_upload,
)
from app.presentation.api.v1.routes.document_distribution_upload_abort import (
    router as _upload_abort_router,
)
from app.presentation.api.v1.routes.document_distribution_verification import (
    router as _verification_router,
)
from app.presentation.api.v1.routes.document_distribution_verification import (
    verify_documents as verify_documents,
)
from app.presentation.api.v1.schemas.document_distribution_schemas import (
    AbortDocumentUploadResponse,
    DeleteDistributionDocumentsRequest,
    DistributedDocumentResponse,
    DocumentBatchResponse,
    DocumentDeliveryPreviewRecipient,
    DocumentDeliveryPreviewResponse,
    DocumentDeliveryPreviewSummary,
    DocumentDeliveryTrackingCounts,
    DocumentDeliveryTrackingResponse,
    DocumentDeliveryTrackingRow,
    DocumentGroupResponse,
    RejectedDocumentResponse,
    SaveDocumentBatchResponse,
    SendDocumentBroadcastRequest,
    SendDocumentBroadcastResponse,
    VerifiedDocumentResponse,
    VerifyDocumentBatchResponse,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()
router.include_router(_groups_read_router)
router.include_router(_verification_router)
router.include_router(_upload_router)
router.include_router(_upload_abort_router)
router.include_router(_reupload_router)
router.include_router(_assignments_router)
router.include_router(_save_router)
router.include_router(_delivery_router)
