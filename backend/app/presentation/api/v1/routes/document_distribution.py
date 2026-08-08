"""Document distribution routes."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import wraps
from time import perf_counter
from typing import Annotated, Literal, ParamSpec, TypeVar

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.passenger_change_propagation import (
    propagate_mobile_passenger_change,
)
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
from app.domain.entities.entities import (
    PassportSubmission,
    User,
    UserRole,
)
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
from app.infrastructure.documents.pdf_parser_sandbox import (
    bounded_pdf_batch_timeout_seconds,
)
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
from app.presentation.api.v1.routes import (
    document_distribution_review_support as _review_support,
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
logger = get_logger(__name__)
DOCUMENT_RESPONSE_RENDER_WINDOW = 64

DOCUMENT_DELIVERY_ACCEPTED_STATUSES = _delivery_support.DOCUMENT_DELIVERY_ACCEPTED_STATUSES
DOCUMENT_DELIVERY_IN_PROGRESS_STATUSES = (
    _delivery_support.DOCUMENT_DELIVERY_IN_PROGRESS_STATUSES
)
DOCUMENT_DELIVERY_STORAGE_REQUIRED_STATUSES = (
    _delivery_support.DOCUMENT_DELIVERY_STORAGE_REQUIRED_STATUSES
)
DOCUMENT_DELIVERY_WEBHOOK_GRACE = _delivery_support.DOCUMENT_DELIVERY_WEBHOOK_GRACE
DOCUMENT_DELIVERY_ACTIVE_POLL_SECONDS = _delivery_support.DOCUMENT_DELIVERY_ACTIVE_POLL_SECONDS
DOCUMENT_DELIVERY_WEBHOOK_POLL_SECONDS = _delivery_support.DOCUMENT_DELIVERY_WEBHOOK_POLL_SECONDS
SHARED_WHATSAPP_DESTINATION_REASON = _delivery_support.SHARED_WHATSAPP_DESTINATION_REASON

DocumentDeliveryDecision = _delivery_support.DocumentDeliveryDecision
_document_delivery_poll_after_seconds = _delivery_support._document_delivery_poll_after_seconds
_document_delivery_decision = _delivery_support._document_delivery_decision
_preferred_document_message_content = _delivery_support._preferred_document_message_content
_processing_batch_response = _delivery_support._processing_batch_response

_LinkedDocumentMatchSource = _review_support._LinkedDocumentMatchSource
_owner_scope_for = _review_support._owner_scope_for
_submitted_statuses = _review_support._submitted_statuses
_passport_number = _review_support._passport_number
_safe_filename = _review_support._safe_filename
_snapshot_value = _review_support._snapshot_value
_linked_document_match_source_from_models = (
    _review_support._linked_document_match_source_from_models
)
_document_match_roster_snapshot = _review_support._document_match_roster_snapshot
_passenger_review_rows = _review_support._passenger_review_rows
_physical_file_accounting = _review_support._physical_file_accounting
_document_assignment_export_rows = _review_support._document_assignment_export_rows


class _ConcurrentDocumentChunkReplay(Exception):
    """Internal control flow after an exact chunk wins a persistence race."""


async def _cleanup_distribution_storage_keys(
    storage_keys: list[str],
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    document_type: str,
) -> None:
    """Best-effort pre-commit compensation that preserves the root failure."""

    if not storage_keys:
        return
    try:
        await MinioStorageRepository().delete_files(storage_keys)
    except Exception:
        logger.warning(
            "document_distribution_storage_cleanup_deferred",
            group_id=str(group_id),
            document_type=document_type,
            object_count=len(storage_keys),
        )
        try:
            await persist_storage_cleanup_job(
                agency_id=agency_id,
                source="document_distribution_compensation",
                context_id=f"{group_id}:{document_type}",
                storage_keys=storage_keys,
            )
        except Exception as exc:
            logger.error(
                "document_distribution_cleanup_tracking_failed",
                group_id=str(group_id),
                document_type=document_type,
                object_count=len(storage_keys),
                error_type=type(exc).__name__,
            )


async def _released_document_passenger_ids(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    document_ids: list[uuid.UUID],
) -> tuple[uuid.UUID, ...]:
    """Return passengers whose selected documents are currently mobile-visible."""

    if not document_ids:
        return ()
    return tuple(
        sorted(
            set(
                (
                    await session.execute(
                        select(DocumentWhatsAppDeliveryModel.passenger_id).where(
                            DocumentWhatsAppDeliveryModel.distributed_document_id.in_(
                                document_ids
                            ),
                            DocumentWhatsAppDeliveryModel.agency_id == agency_id,
                            DocumentWhatsAppDeliveryModel.group_id == group_id,
                            DocumentWhatsAppDeliveryModel.passenger_id.is_not(None),
                            DocumentWhatsAppDeliveryModel.status.in_(
                                DOCUMENT_DELIVERY_ACCEPTED_STATUSES
                            ),
                        )
                    )
                ).scalars()
            ),
            key=str,
        )
    )
_UploadParameters = ParamSpec("_UploadParameters")
_UploadResult = TypeVar("_UploadResult")
_REQUEST_STAGING_CLEANUP_KEYS: ContextVar[list[str] | None] = ContextVar(
    "document_distribution_request_staging_cleanup_keys",
    default=None,
)
_RETRYABLE_STAGING_HTTP_STATUSES = frozenset(
    {
        status.HTTP_408_REQUEST_TIMEOUT,
        status.HTTP_409_CONFLICT,
        status.HTTP_425_TOO_EARLY,
        status.HTTP_429_TOO_MANY_REQUESTS,
    }
)


def _remember_request_staging_keys(storage_keys: list[str] | tuple[str, ...]) -> None:
    remembered = _REQUEST_STAGING_CLEANUP_KEYS.get()
    if remembered is not None:
        remembered.extend(storage_keys)


async def _cleanup_remembered_request_staging() -> None:
    remembered = _REQUEST_STAGING_CLEANUP_KEYS.get()
    if not remembered:
        return
    keys = list(dict.fromkeys(remembered))
    await cleanup_staged_storage_keys(keys)
    remembered.clear()


def _with_staging_cleanup(
    handler: Callable[_UploadParameters, Awaitable[_UploadResult]],
) -> Callable[_UploadParameters, Awaitable[_UploadResult]]:
    """Clean staged objects after commit or terminal request rejection only."""

    @wraps(handler)
    async def wrapped(
        *args: _UploadParameters.args,
        **kwargs: _UploadParameters.kwargs,
    ) -> _UploadResult:
        cleanup_keys: list[str] = []
        context_token = _REQUEST_STAGING_CLEANUP_KEYS.set(cleanup_keys)
        try:
            result = await handler(*args, **kwargs)
        except HTTPException as exc:
            if (
                status.HTTP_400_BAD_REQUEST
                <= exc.status_code
                < status.HTTP_500_INTERNAL_SERVER_ERROR
                and exc.status_code not in _RETRYABLE_STAGING_HTTP_STATUSES
            ):
                await finish_cleanup_despite_cancellation(
                    _cleanup_remembered_request_staging()
                )
            raise
        else:
            await finish_cleanup_despite_cancellation(
                _cleanup_remembered_request_staging()
            )
            return result
        finally:
            _REQUEST_STAGING_CLEANUP_KEYS.reset(context_token)

    return wrapped


async def _latest_document_batch(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
    document_type: str,
) -> DocumentDistributionBatchModel | None:
    result = await session.execute(
        select(DocumentDistributionBatchModel)
        .where(
            DocumentDistributionBatchModel.group_id == group_id,
            DocumentDistributionBatchModel.agency_id == agency_id,
            DocumentDistributionBatchModel.document_type == document_type,
        )
        .order_by(DocumentDistributionBatchModel.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _all_group_documents(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
    document_type: str,
) -> list[DistributedDocumentModel]:
    result = await session.execute(
        select(DistributedDocumentModel)
        .where(
            DistributedDocumentModel.group_id == group_id,
            DistributedDocumentModel.agency_id == agency_id,
            DistributedDocumentModel.document_type == document_type,
        )
        .order_by(
            DistributedDocumentModel.created_at.desc(),
            DistributedDocumentModel.id.desc(),
        )
        .limit(MAX_DISTRIBUTION_ASSIGNMENT_ROWS_PER_SCOPE + 1)
    )
    documents = list(result.scalars().all())
    if len(documents) > MAX_DISTRIBUTION_ASSIGNMENT_ROWS_PER_SCOPE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This document list exceeds the supported "
                f"{MAX_DISTRIBUTION_ASSIGNMENT_ROWS_PER_SCOPE:,} assignment limit. "
                "Remove obsolete documents before continuing."
            ),
        )
    return documents


async def _enforce_group_document_assignment_capacity(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
    document_type: str,
    incoming_rows: int,
) -> None:
    """Fail before ORM staging when a locked distribution ledger is full."""

    result = await session.execute(
        select(func.count(DistributedDocumentModel.id)).where(
            DistributedDocumentModel.group_id == group_id,
            DistributedDocumentModel.agency_id == agency_id,
            DistributedDocumentModel.document_type == document_type,
        )
    )
    enforce_distribution_scope_capacity(
        existing_rows=int(result.scalar_one()),
        incoming_rows=incoming_rows,
    )


async def _first_blocking_processing_upload_id(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
    document_type: str,
    exclude_upload_id: uuid.UUID,
    lock: bool = False,
) -> uuid.UUID | None:
    """Find a different incomplete upload without leaking another scope."""

    statement = (
        select(DocumentDistributionBatchModel.id)
        .where(
            DocumentDistributionBatchModel.group_id == group_id,
            DocumentDistributionBatchModel.agency_id == agency_id,
            DocumentDistributionBatchModel.document_type == document_type,
            DocumentDistributionBatchModel.status == "processing",
            DocumentDistributionBatchModel.id != exclude_upload_id,
        )
        .order_by(
            DocumentDistributionBatchModel.created_at.asc(),
            DocumentDistributionBatchModel.id.asc(),
        )
        .limit(1)
    )
    if lock:
        statement = statement.with_for_update()
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def _linked_whatsapp_recipients(
    session: AsyncSession,
    *,
    group: ClientGroupModel,
    require_opt_in: bool = True,
) -> tuple[dict[uuid.UUID, str], list[WhatsAppBroadcastRecipientModel]]:
    filters = [
        ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group.id,
        ClientGroupWhatsAppBroadcastLinkModel.agency_id == group.agency_id,
        WhatsAppBroadcastGroupModel.agency_id == group.agency_id,
    ]
    if require_opt_in:
        filters.append(WhatsAppBroadcastGroupModel.recipient_opt_in_confirmed_at.is_not(None))
    linked_result = await session.execute(
        select(
            ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id,
            WhatsAppBroadcastGroupModel.name,
        )
        .join(
            WhatsAppBroadcastGroupModel,
            WhatsAppBroadcastGroupModel.id
            == ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id,
        )
        .where(*filters)
    )
    linked_broadcasts = {
        broadcast_id: broadcast_name for broadcast_id, broadcast_name in linked_result.all()
    }
    if not linked_broadcasts:
        return {}, []
    recipient_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel).where(
            WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
            WhatsAppBroadcastRecipientModel.broadcast_group_id.in_(list(linked_broadcasts)),
            WhatsAppBroadcastRecipientModel.removed_at.is_(None),
            WhatsAppBroadcastRecipientModel.suppressed_by_roster_resolution_id.is_(None),
        )
    )
    return linked_broadcasts, list(recipient_result.scalars().all())


async def _read_linked_document_match_source(
    session: AsyncSession,
    *,
    group: ClientGroupModel,
    lock: bool,
) -> _LinkedDocumentMatchSource:
    """Read matching evidence coherently, optionally under stable write locks.

    The locked path is called only after the client-group row is locked.  It
    then follows the shared order group -> broadcasts -> links -> recipients;
    the caller locks passengers last.  Parent locks also serialize child-row
    inserts through their foreign keys, preventing recipient/link phantoms.
    """

    if not lock:
        result = await session.execute(
            select(
                ClientGroupWhatsAppBroadcastLinkModel,
                WhatsAppBroadcastGroupModel,
                WhatsAppBroadcastRecipientModel,
            )
            .select_from(ClientGroupWhatsAppBroadcastLinkModel)
            .join(
                WhatsAppBroadcastGroupModel,
                WhatsAppBroadcastGroupModel.id
                == ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id,
            )
            .outerjoin(
                WhatsAppBroadcastRecipientModel,
                and_(
                    WhatsAppBroadcastRecipientModel.broadcast_group_id
                    == WhatsAppBroadcastGroupModel.id,
                    WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
                    WhatsAppBroadcastRecipientModel.removed_at.is_(None),
                ),
            )
            .where(
                ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group.id,
                ClientGroupWhatsAppBroadcastLinkModel.agency_id == group.agency_id,
                WhatsAppBroadcastGroupModel.agency_id == group.agency_id,
            )
            .order_by(
                WhatsAppBroadcastGroupModel.id,
                ClientGroupWhatsAppBroadcastLinkModel.id,
                WhatsAppBroadcastRecipientModel.id,
            )
        )
        links_by_id: dict[uuid.UUID, ClientGroupWhatsAppBroadcastLinkModel] = {}
        broadcasts_by_id: dict[uuid.UUID, WhatsAppBroadcastGroupModel] = {}
        recipients_by_id: dict[uuid.UUID, WhatsAppBroadcastRecipientModel] = {}
        for link, broadcast, recipient in result.all():
            links_by_id[link.id] = link
            broadcasts_by_id[broadcast.id] = broadcast
            if recipient is not None:
                recipients_by_id[recipient.id] = recipient
        return _linked_document_match_source_from_models(
            group=group,
            links=list(links_by_id.values()),
            broadcasts=list(broadcasts_by_id.values()),
            recipients=list(recipients_by_id.values()),
        )

    linked_id_result = await session.execute(
        select(ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id)
        .where(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group.id,
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == group.agency_id,
        )
        .order_by(ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id)
    )
    linked_ids = sorted(set(linked_id_result.scalars().all()), key=str)
    broadcasts: list[WhatsAppBroadcastGroupModel] = []
    if linked_ids:
        broadcast_result = await session.execute(
            select(WhatsAppBroadcastGroupModel)
            .where(
                WhatsAppBroadcastGroupModel.id.in_(linked_ids),
                WhatsAppBroadcastGroupModel.agency_id == group.agency_id,
            )
            .order_by(WhatsAppBroadcastGroupModel.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        broadcasts = list(broadcast_result.scalars().all())
        if {broadcast.id for broadcast in broadcasts} != set(linked_ids):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "A linked WhatsApp list changed while the PDFs were being "
                    "processed. Review and upload them again."
                ),
            )

    link_result = await session.execute(
        select(ClientGroupWhatsAppBroadcastLinkModel)
        .where(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group.id,
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == group.agency_id,
        )
        .order_by(ClientGroupWhatsAppBroadcastLinkModel.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    links = list(link_result.scalars().all())
    if {link.broadcast_group_id for link in links} != set(linked_ids):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The linked WhatsApp lists changed while the PDFs were being "
                "processed. Review and upload them again."
            ),
        )

    recipients: list[WhatsAppBroadcastRecipientModel] = []
    if linked_ids:
        recipient_result = await session.execute(
            select(WhatsAppBroadcastRecipientModel)
            .where(
                WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
                WhatsAppBroadcastRecipientModel.broadcast_group_id.in_(linked_ids),
                WhatsAppBroadcastRecipientModel.removed_at.is_(None),
            )
            .order_by(WhatsAppBroadcastRecipientModel.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        recipients = list(recipient_result.scalars().all())
    return _linked_document_match_source_from_models(
        group=group,
        links=links,
        broadcasts=broadcasts,
        recipients=recipients,
    )


async def _linked_document_match_identifiers(
    session: AsyncSession,
    *,
    group: ClientGroupModel,
    passengers: list[PassportSubmission],
    matcher: DocumentMatcher,
    source: _LinkedDocumentMatchSource | None = None,
) -> tuple[PassengerIdentifier, ...]:
    """Attach linked WhatsApp-Excel codes only after an unambiguous roster match."""

    if source is None:
        linked_broadcasts, recipients = await _linked_whatsapp_recipients(
            session,
            group=group,
            require_opt_in=False,
        )
    else:
        linked_broadcasts = source.linked_broadcasts
        recipients = list(source.recipients)
    scoped_recipients = [
        recipient
        for recipient in recipients
        if recipient.agency_id == group.agency_id
        and recipient.broadcast_group_id in linked_broadcasts
    ]
    scoped_passengers = [
        passenger
        for passenger in passengers
        if passenger.agency_id == group.agency_id and passenger.group_id == group.id
    ]
    if not scoped_recipients or not scoped_passengers:
        return ()
    comparison_recipients = [
        RecipientForComparison(
            id=recipient.id,
            broadcast_id=recipient.broadcast_group_id,
            broadcast_name=linked_broadcasts[recipient.broadcast_group_id],
            name=recipient.name,
            phone=recipient.normalized_phone_number,
            updated_at=recipient.created_at,
            imported_fields=dict(recipient.imported_fields or {}),
        )
        for recipient in scoped_recipients
    ]
    comparison_submissions = [
        SubmissionForComparison(
            id=passenger.id,
            name=passenger.client_name,
            client_phone=passenger.client_phone,
            family_head_phone=passenger.family_head_phone,
            updated_at=passenger.updated_at,
            client_email=passenger.client_email,
            family_head_email=passenger.family_head_email,
            confirmed_fields=dict(passenger.confirmed_fields or {}),
            extracted_fields=dict(passenger.extracted_fields or {}),
            staff_metadata=dict(passenger.staff_metadata or {}),
        )
        for passenger in scoped_passengers
    ]
    rows, _ = await asyncio.to_thread(
        compare_group_submissions,
        comparison_recipients,
        comparison_submissions,
    )
    identifiers: list[PassengerIdentifier] = []
    identifiers_seen: set[tuple[uuid.UUID, str, str]] = set()
    identifiers_per_passenger: dict[uuid.UUID, int] = {}
    matched_rows = sorted(
        (
            row
            for row in rows
            if row.status == "submitted" and len(row.submission_ids) == 1
        ),
        key=lambda row: (str(row.submission_ids[0]), tuple(map(str, row.recipient_ids))),
    )
    for row in matched_rows:
        if len(identifiers) >= MAX_SUPPLEMENTAL_IDENTIFIERS_PER_REQUEST:
            break
        passenger_id = row.submission_ids[0]
        for field_set in sorted(row.recipient_fields, key=lambda item: str(item.recipient_id)):
            if (
                len(identifiers) >= MAX_SUPPLEMENTAL_IDENTIFIERS_PER_REQUEST
                or identifiers_per_passenger.get(passenger_id, 0)
                >= MAX_SUPPLEMENTAL_IDENTIFIERS_PER_PASSENGER
            ):
                break
            aliases = sorted(
                matcher.stored_identifier_aliases(field_set.fields),
                key=lambda item: (item[1], item[0]),
            )
            for value, kind in aliases:
                if (
                    len(identifiers) >= MAX_SUPPLEMENTAL_IDENTIFIERS_PER_REQUEST
                    or identifiers_per_passenger.get(passenger_id, 0)
                    >= MAX_SUPPLEMENTAL_IDENTIFIERS_PER_PASSENGER
                ):
                    break
                identity = (passenger_id, kind, value)
                if identity in identifiers_seen:
                    continue
                identifiers_seen.add(identity)
                identifiers.append(
                    PassengerIdentifier(
                        passenger_id=passenger_id,
                        agency_id=group.agency_id,
                        group_id=group.id,
                        kind=kind,
                        value=value,
                        source="linked WhatsApp Excel",
                    )
                )
                identifiers_per_passenger[passenger_id] = (
                    identifiers_per_passenger.get(passenger_id, 0) + 1
                )
    return tuple(identifiers)


async def _build_document_delivery_preview(
    session: AsyncSession,
    *,
    group: ClientGroupModel,
    batch: DocumentDistributionBatchModel,
    passengers: list[PassportSubmission],
) -> DocumentDeliveryPreviewResponse:
    message_content_1, message_content_2 = default_document_message_content(batch.document_type)
    linked_broadcasts, recipient_models = await _linked_whatsapp_recipients(
        session,
        group=group,
    )
    recipients_for_comparison = [
        RecipientForComparison(
            id=recipient.id,
            broadcast_id=recipient.broadcast_group_id,
            broadcast_name=linked_broadcasts[recipient.broadcast_group_id],
            name=recipient.name,
            phone=recipient.normalized_phone_number,
            updated_at=recipient.created_at,
            imported_fields=dict(recipient.imported_fields or {}),
        )
        for recipient in recipient_models
    ]
    passenger_ids = [passenger.id for passenger in passengers]
    submission_models: list[PassportSubmissionModel] = []
    if passenger_ids:
        submission_result = await session.execute(
            select(PassportSubmissionModel).where(
                PassportSubmissionModel.id.in_(passenger_ids),
                PassportSubmissionModel.group_id == group.id,
                PassportSubmissionModel.agency_id == group.agency_id,
            )
        )
        submission_models = list(submission_result.scalars().all())
    submissions_for_comparison = [
        SubmissionForComparison(
            id=submission.id,
            name=submission.client_name,
            client_phone=submission.client_phone,
            family_head_phone=submission.family_head_phone,
            updated_at=submission.updated_at,
            client_email=submission.client_email,
            family_head_email=submission.family_head_email,
            confirmed_fields=dict(submission.confirmed_fields or {}),
            extracted_fields=dict(submission.extracted_fields or {}),
            staff_metadata=dict(submission.staff_metadata or {}),
        )
        for submission in submission_models
    ]
    match_rows, _ = await asyncio.to_thread(
        compare_group_submissions,
        recipients_for_comparison,
        submissions_for_comparison,
    )
    recipients_by_id = {recipient.id: recipient for recipient in recipient_models}
    recipient_by_submission: dict[
        uuid.UUID,
        tuple[WhatsAppBroadcastRecipientModel, str],
    ] = {}
    ambiguous_submission_ids: set[uuid.UUID] = set()
    for row in match_rows:
        if row.status == "multiple_submissions":
            ambiguous_submission_ids.update(row.submission_ids)
            continue
        if row.status != "submitted":
            continue
        candidates = sorted(
            (
                recipients_by_id[recipient_id]
                for recipient_id in row.recipient_ids
                if recipient_id in recipients_by_id
            ),
            key=lambda recipient: (
                linked_broadcasts.get(recipient.broadcast_group_id, "").casefold(),
                str(recipient.id),
            ),
        )
        if not candidates:
            continue
        selected_recipient = candidates[0]
        for submission_id in row.submission_ids:
            recipient_by_submission[submission_id] = (
                selected_recipient,
                linked_broadcasts[selected_recipient.broadcast_group_id],
            )

    documents_result = await session.execute(
        select(DistributedDocumentModel, DocumentDistributionBatchModel.status)
        .join(
            DocumentDistributionBatchModel,
            DocumentDistributionBatchModel.id == DistributedDocumentModel.batch_id,
        )
        .where(
            DistributedDocumentModel.group_id == group.id,
            DistributedDocumentModel.agency_id == group.agency_id,
            DistributedDocumentModel.document_type == batch.document_type,
            DistributedDocumentModel.match_status != "duplicate_document",
            DocumentDistributionBatchModel.group_id == group.id,
            DocumentDistributionBatchModel.agency_id == group.agency_id,
            DocumentDistributionBatchModel.document_type == batch.document_type,
        )
        .order_by(
            DistributedDocumentModel.created_at.desc(),
            DistributedDocumentModel.id.desc(),
        )
    )
    document_rows = list(documents_result.all())
    documents = [row[0] for row in document_rows]
    saved_document_ids = {
        document.id for document, batch_status in document_rows if batch_status == "saved"
    }
    documents_by_passenger: dict[uuid.UUID, list[DistributedDocumentModel]] = {}
    for document in documents:
        if document.passenger_id:
            documents_by_passenger.setdefault(document.passenger_id, []).append(document)

    document_ids = [document.id for document in documents]
    deliveries_by_document: dict[
        uuid.UUID,
        list[DocumentWhatsAppDeliveryModel],
    ] = {}
    if document_ids:
        delivery_result = await session.execute(
            select(DocumentWhatsAppDeliveryModel)
            .where(
                DocumentWhatsAppDeliveryModel.distributed_document_id.in_(document_ids),
                DocumentWhatsAppDeliveryModel.agency_id == group.agency_id,
                DocumentWhatsAppDeliveryModel.group_id == group.id,
            )
            .order_by(
                DocumentWhatsAppDeliveryModel.created_at.desc(),
                DocumentWhatsAppDeliveryModel.status_updated_at.desc(),
            )
        )
        delivery_models = list(delivery_result.scalars().all())
        message_content_1, message_content_2 = _preferred_document_message_content(
            delivery_models,
            fallback_content_1=message_content_1,
            fallback_content_2=message_content_2,
        )
        for delivery in delivery_models:
            if delivery.distributed_document_id:
                deliveries_by_document.setdefault(
                    delivery.distributed_document_id,
                    [],
                ).append(delivery)

    preview_rows: list[DocumentDeliveryPreviewRecipient] = []
    summary = DocumentDeliveryPreviewSummary(total_passengers=len(passengers))
    for passenger in passengers:
        passenger_documents = documents_by_passenger.get(passenger.id, [])
        matched_recipient = recipient_by_submission.get(passenger.id)
        recipient_model = matched_recipient[0] if matched_recipient else None
        broadcast_name = matched_recipient[1] if matched_recipient else None
        if not passenger_documents:
            summary.blocked += 1
            preview_rows.append(
                DocumentDeliveryPreviewRecipient(
                    passenger_id=passenger.id,
                    passenger_name=passenger.client_name,
                    passport_number=_passport_number(passenger),
                    document_type=batch.document_type,
                    recipient_id=recipient_model.id if recipient_model else None,
                    broadcast_group_id=(
                        recipient_model.broadcast_group_id if recipient_model else None
                    ),
                    broadcast_name=broadcast_name,
                    phone_number=(
                        recipient_model.normalized_phone_number if recipient_model else None
                    ),
                    delivery_status="blocked",
                    reason="No saved document is matched to this passenger.",
                )
            )
            continue

        for document in passenger_documents:
            delivery_history = deliveries_by_document.get(document.id, [])
            latest_delivery = delivery_history[0] if delivery_history else None
            if passenger.id in ambiguous_submission_ids:
                decision = DocumentDeliveryDecision(
                    status="blocked",
                    eligible=False,
                    resend_allowed=False,
                    reason=SHARED_WHATSAPP_DESTINATION_REASON,
                )
            else:
                decision = _document_delivery_decision(
                    saved=document.id in saved_document_ids,
                    match_status=document.match_status,
                    recipient_available=matched_recipient is not None,
                    delivery_history=delivery_history,
                )
            if decision.status == "ready":
                summary.ready += 1
            elif decision.status == "retryable":
                summary.retryable += 1
            elif decision.status == "already_sent":
                summary.already_sent += 1
            elif decision.status in DOCUMENT_DELIVERY_IN_PROGRESS_STATUSES:
                summary.in_progress += 1
            else:
                summary.blocked += 1

            preview_rows.append(
                DocumentDeliveryPreviewRecipient(
                    passenger_id=passenger.id,
                    passenger_name=passenger.client_name,
                    passport_number=_passport_number(passenger),
                    document_id=document.id,
                    document_filename=document.original_filename,
                    document_type=document.document_type,
                    recipient_id=recipient_model.id if recipient_model else None,
                    broadcast_group_id=(
                        recipient_model.broadcast_group_id if recipient_model else None
                    ),
                    broadcast_name=broadcast_name,
                    phone_number=(
                        recipient_model.normalized_phone_number if recipient_model else None
                    ),
                    delivery_id=latest_delivery.id if latest_delivery else None,
                    delivery_status=decision.status,
                    eligible=decision.eligible,
                    resend_allowed=decision.resend_allowed,
                    reason=decision.reason,
                    error_message=decision.error_message,
                    message_preview=(
                        render_document_message(
                            message_content_1=message_content_1,
                            message_content_2=message_content_2,
                        )
                        if matched_recipient
                        else None
                    ),
                )
            )

    settings = get_settings()
    template_name = settings.whatsapp_document_template_name.strip()
    provider_configured = bool(
        template_name and settings.whatsapp_access_token and settings.whatsapp_phone_number_id
    )
    configuration_error: str | None = None
    if not linked_broadcasts:
        configuration_error = "Link at least one opted-in WhatsApp broadcast to this group first."
    elif not provider_configured:
        configuration_error = (
            "The WhatsApp document template or Cloud API credentials are not configured."
        )
    elif summary.ready + summary.retryable + summary.already_sent == 0:
        configuration_error = "There are no saved documents available to send."

    return DocumentDeliveryPreviewResponse(
        group_id=group.id,
        batch_id=batch.id,
        document_type=batch.document_type,
        template_name=template_name or None,
        template_configured=provider_configured,
        linked_broadcast_count=len(linked_broadcasts),
        can_send=configuration_error is None,
        configuration_error=configuration_error,
        message_content_1=message_content_1,
        message_content_2=message_content_2,
        summary=summary,
        recipients=preview_rows,
    )


async def _get_authorized_group(
    group_id: uuid.UUID,
    *,
    current_user: User,
    session: AsyncSession,
) -> ClientGroupModel:
    if not current_user.agency_id or current_user.role == UserRole.AGENCY_COORDINATOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )
    statement = select(ClientGroupModel).where(
        ClientGroupModel.id == group_id,
        ClientGroupModel.agency_id == current_user.agency_id,
    )
    statement = AuthorizationPolicy.apply_group_visibility_scope(statement, current_user)
    result = await session.execute(statement)
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client group was not found",
        )
    try:
        await AuthorizationPolicy(session).require_export_data(current_user, group)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message)
    return group


async def _get_visible_document_batch(
    session: AsyncSession,
    *,
    batch_id: uuid.UUID,
    current_user: User,
) -> DocumentDistributionBatchModel | None:
    """Resolve a batch only through the caller's tenant and group visibility."""

    if not current_user.agency_id or current_user.role == UserRole.AGENCY_COORDINATOR:
        return None
    statement = (
        select(DocumentDistributionBatchModel)
        .join(
            ClientGroupModel,
            ClientGroupModel.id == DocumentDistributionBatchModel.group_id,
        )
        .where(
            DocumentDistributionBatchModel.id == batch_id,
            DocumentDistributionBatchModel.agency_id == current_user.agency_id,
            ClientGroupModel.agency_id == current_user.agency_id,
        )
    )
    statement = AuthorizationPolicy.apply_group_visibility_scope(statement, current_user)
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def _lock_active_document_scope(
    session: AsyncSession,
    *,
    current_user: User,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
) -> tuple[UserModel, ClientGroupModel]:
    """Re-fetch and lock the active actor, agency, and group before DB writes."""

    result = await session.execute(
        select(UserModel, ClientGroupModel)
        .select_from(UserModel)
        .join(AgencyModel, AgencyModel.id == UserModel.agency_id)
        .join(ClientGroupModel, ClientGroupModel.agency_id == AgencyModel.id)
        .where(
            UserModel.id == current_user.id,
            UserModel.agency_id == agency_id,
            UserModel.role == current_user.role.value,
            UserModel.is_active.is_(True),
            UserModel.deleted_at.is_(None),
            AgencyModel.id == agency_id,
            AgencyModel.is_active.is_(True),
            ClientGroupModel.id == group_id,
            ClientGroupModel.agency_id == agency_id,
        )
        .with_for_update(of=(UserModel, AgencyModel, ClientGroupModel))
        .execution_options(populate_existing=True)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account, agency, or group is no longer authorized for this upload.",
        )
    actor, group = row
    try:
        # Authorize with the row that was just re-read under lock, not the
        # request-scoped principal snapshot created before PDF processing.
        await AuthorizationPolicy(session).require_export_data(actor, group)
    except AuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.message,
        ) from exc
    return actor, group


async def _lock_document_passenger_roster(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
) -> None:
    """Lock the complete tenant-scoped roster in a deterministic order.

    The parent group is already locked by ``_lock_active_document_scope``.  Its
    row lock serializes new roster inserts through the foreign key, while these
    row locks serialize edits and removals of existing passengers until the
    document-assignment transaction commits.
    """

    await session.execute(
        select(PassportSubmissionModel.id)
        .where(
            PassportSubmissionModel.agency_id == agency_id,
            PassportSubmissionModel.group_id == group_id,
        )
        .order_by(PassportSubmissionModel.id)
        .with_for_update()
    )


def _detach_distribution_batch_before_long_processing(
    session: AsyncSession,
    batch: DocumentDistributionBatchModel,
) -> None:
    """Retain loaded counters across rollback without keeping a transaction open."""

    session.sync_session.expunge(batch)


async def _lock_and_validate_document_match_scope(
    session: AsyncSession,
    *,
    current_user: User,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
    matcher: DocumentMatcher,
    expected_roster_snapshot: tuple[tuple[str, ...], ...],
    expected_source_snapshot: tuple[tuple[str, ...], ...],
    expected_supplemental_identifiers: tuple[PassengerIdentifier, ...] | None,
    required_passenger_id: uuid.UUID | None = None,
) -> tuple[UserModel, list[PassportSubmission]]:
    """Lock and revalidate every mutable row that influenced assignment."""

    actor, locked_group = await _lock_active_document_scope(
        session,
        current_user=current_user,
        group_id=group_id,
        agency_id=agency_id,
    )
    current_source = await _read_linked_document_match_source(
        session,
        group=locked_group,
        lock=True,
    )
    await _lock_document_passenger_roster(
        session,
        agency_id=agency_id,
        group_id=group_id,
    )
    current_passengers = await _group_passengers(
        group_id,
        current_user=current_user,
        session=session,
    )
    source_changed = current_source.snapshot != expected_source_snapshot
    roster_changed = (
        _document_match_roster_snapshot(current_passengers) != expected_roster_snapshot
    )
    required_passenger_missing = required_passenger_id is not None and all(
        passenger.id != required_passenger_id for passenger in current_passengers
    )
    identifiers_changed = False
    if not source_changed and not roster_changed and expected_supplemental_identifiers is not None:
        current_identifiers = await _linked_document_match_identifiers(
            session,
            group=locked_group,
            passengers=current_passengers,
            matcher=matcher,
            source=current_source,
        )
        identifiers_changed = current_identifiers != expected_supplemental_identifiers
    if source_changed or roster_changed or required_passenger_missing or identifiers_changed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This group's passenger or linked WhatsApp details changed while "
                "the PDFs were being processed. Review and upload them again."
            ),
        )
    return actor, current_passengers


async def _group_passengers(
    group_id: uuid.UUID,
    *,
    current_user: User,
    session: AsyncSession,
) -> list[PassportSubmission]:
    if not current_user.agency_id:
        return []
    return await PassportSubmissionRepository(session).list_by_group(
        current_user.agency_id,
        group_id,
        limit=5000,
        exclude_archived_groups=True,
        created_by_user_id=_owner_scope_for(current_user),
        visible_to_user=current_user,
    )


async def _document_response(
    document: DistributedDocumentModel,
    storage: MinioStorageRepository,
    *,
    source: str,
    deliveries: list[DocumentWhatsAppDeliveryModel],
) -> DistributedDocumentResponse:
    ordered_deliveries = sorted(
        deliveries,
        key=lambda item: (item.status_updated_at, item.created_at, str(item.id)),
        reverse=True,
    )
    latest_delivery = ordered_deliveries[0] if ordered_deliveries else None
    accepted_deliveries = [
        item for item in ordered_deliveries if item.status in DOCUMENT_DELIVERY_ACCEPTED_STATUSES
    ]
    latest_accepted = accepted_deliveries[0] if accepted_deliveries else None
    in_progress = any(
        item.status in DOCUMENT_DELIVERY_IN_PROGRESS_STATUSES for item in ordered_deliveries
    )
    if latest_accepted is not None:
        delivery_status = "sent"
    elif latest_delivery is not None:
        delivery_status = latest_delivery.status
    else:
        delivery_status = "not_sent"
    return DistributedDocumentResponse(
        id=document.id,
        original_filename=document.original_filename,
        document_type=document.document_type,
        detected_type=document.detected_type,
        match_status=document.match_status,
        match_confidence=document.match_confidence,
        match_reason=document.match_reason,
        extracted_name=document.extracted_name,
        extracted_passport_number=document.extracted_passport_number,
        extracted_reference=document.extracted_reference,
        source=source,
        delivery_status=delivery_status,
        sent_to=latest_accepted.phone_number if latest_accepted else None,
        last_sent_at=latest_accepted.status_updated_at if latest_accepted else None,
        can_resend=latest_accepted is not None and not in_progress,
        url=await storage.get_presigned_url(document.storage_key),
    )


async def _batch_response(
    *,
    session: AsyncSession,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
    document_type: str,
    passengers: list[PassportSubmission],
    batch: DocumentDistributionBatchModel | None,
    documents: list[DistributedDocumentModel],
    rejected_documents: list[RejectedDocumentResponse] | None = None,
) -> DocumentBatchResponse:
    storage = MinioStorageRepository()
    batches_result = await session.execute(
        select(DocumentDistributionBatchModel)
        .where(
            DocumentDistributionBatchModel.group_id == group_id,
            DocumentDistributionBatchModel.agency_id == agency_id,
            DocumentDistributionBatchModel.document_type == document_type,
        )
        .order_by(DocumentDistributionBatchModel.created_at.desc())
    )
    all_batches = list(batches_result.scalars().all())
    pending_batches = [item for item in all_batches if item.status != "saved"]
    processing_batches = [item for item in all_batches if item.status == "processing"]
    response_batch = (
        processing_batches[0]
        if processing_batches
        else pending_batches[0]
        if pending_batches
        else batch or (all_batches[0] if all_batches else None)
    )
    document_ids = [document.id for document in documents]
    deliveries_by_document: dict[uuid.UUID, list[DocumentWhatsAppDeliveryModel]] = {}
    email_document_ids: set[uuid.UUID] = set()
    if document_ids:
        delivery_result = await session.execute(
            select(DocumentWhatsAppDeliveryModel).where(
                DocumentWhatsAppDeliveryModel.distributed_document_id.in_(document_ids),
                DocumentWhatsAppDeliveryModel.agency_id == agency_id,
                DocumentWhatsAppDeliveryModel.group_id == group_id,
            )
        )
        for delivery in delivery_result.scalars().all():
            if delivery.distributed_document_id is not None:
                deliveries_by_document.setdefault(
                    delivery.distributed_document_id,
                    [],
                ).append(delivery)
        email_link_result = await session.execute(
            select(EmailArtifactDocumentModel.distributed_document_id).where(
                EmailArtifactDocumentModel.distributed_document_id.in_(document_ids)
            )
        )
        email_document_ids = set(email_link_result.scalars().all())

    response_documents = list(documents)
    presign_slots = asyncio.Semaphore(16)

    async def render_document(
        document: DistributedDocumentModel,
    ) -> DistributedDocumentResponse:
        async with presign_slots:
            return await _document_response(
                document,
                storage,
                source="email" if document.id in email_document_ids else "manual",
                deliveries=deliveries_by_document.get(document.id, []),
            )

    rendered_documents: list[DistributedDocumentResponse] = []
    for offset in range(0, len(response_documents), DOCUMENT_RESPONSE_RENDER_WINDOW):
        rendered_documents.extend(
            await asyncio.gather(
                *(
                    render_document(document)
                    for document in response_documents[
                        offset : offset + DOCUMENT_RESPONSE_RENDER_WINDOW
                    ]
                )
            )
        )
    persisted_rejections: list[RejectedDocumentResponse] = []
    if (
        response_batch is not None
        and getattr(response_batch, "rejected_count", 0) > 0
        and not rejected_documents
    ):
        receipts_result = await session.execute(
            select(DocumentUploadChunkModel.rejected_documents)
            .where(
                DocumentUploadChunkModel.upload_id == response_batch.id,
                DocumentUploadChunkModel.agency_id == agency_id,
                DocumentUploadChunkModel.workflow == "distribution",
                DocumentUploadChunkModel.group_id == group_id,
                DocumentUploadChunkModel.document_type == document_type,
            )
            .order_by(DocumentUploadChunkModel.chunk_index.asc())
        )
        for chunk_rejections in receipts_result.scalars().all():
            for item in chunk_rejections if isinstance(chunk_rejections, list) else []:
                if not isinstance(item, dict):
                    continue
                filename = item.get("filename")
                detected_type = item.get("detected_type")
                reason = item.get("reason")
                if not isinstance(filename, str):
                    continue
                if not isinstance(detected_type, str):
                    continue
                if not isinstance(reason, str):
                    continue
                persisted_rejections.append(
                    RejectedDocumentResponse(
                        filename=filename,
                        detected_type=detected_type,
                        reason=reason,
                    )
                )
    responses_by_document = {
        document.id: response
        for document, response in zip(response_documents, rendered_documents, strict=True)
    }

    rows, unmatched, matched_count = _passenger_review_rows(
        passengers=passengers,
        documents=documents,
        responses_by_document=responses_by_document,
    )
    physical_file_count, assigned_file_count, assigned_passenger_count, assignment_issues = (
        _physical_file_accounting(
            passengers=passengers,
            documents=documents,
            responses_by_document=responses_by_document,
        )
    )
    visible_documents = response_documents
    return DocumentBatchResponse(
        batch_id=response_batch.id if response_batch else None,
        group_id=group_id,
        document_type=document_type,
        status=response_batch.status if response_batch else "draft",
        uploaded_count=len(visible_documents),
        rejected_count=response_batch.rejected_count if response_batch else 0,
        matched_count=matched_count,
        physical_file_count=physical_file_count,
        assigned_file_count=assigned_file_count,
        assigned_passenger_count=assigned_passenger_count,
        needs_assignment_count=len(assignment_issues),
        processing_upload_ids=[item.id for item in processing_batches],
        saved_at=response_batch.saved_at if response_batch else None,
        created_at=response_batch.created_at if response_batch else None,
        review_rows=rows,
        unmatched_documents=unmatched,
        assignment_issues=assignment_issues,
        rejected_documents=persisted_rejections or rejected_documents or [],
    )


async def _refresh_distribution_batches(
    session: AsyncSession,
    *,
    batch_ids: set[uuid.UUID],
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    now: datetime,
) -> None:
    if not batch_ids:
        return
    batches_result = await session.execute(
        select(DocumentDistributionBatchModel)
        .where(
            DocumentDistributionBatchModel.id.in_(batch_ids),
            DocumentDistributionBatchModel.agency_id == agency_id,
            DocumentDistributionBatchModel.group_id == group_id,
        )
        .with_for_update()
    )
    batches = list(batches_result.scalars().all())
    if not batches:
        return
    processing_batch_ids = {batch.id for batch in batches if batch.status == "processing"}
    incomplete_processing_ids = set(processing_batch_ids)
    if processing_batch_ids:
        receipts_result = await session.execute(
            select(
                DocumentUploadChunkModel.upload_id,
                DocumentUploadChunkModel.chunk_index,
                DocumentUploadChunkModel.expected_chunk_count,
                DocumentUploadChunkModel.expected_file_count,
                DocumentUploadChunkModel.file_count,
            ).where(
                DocumentUploadChunkModel.upload_id.in_(processing_batch_ids),
                DocumentUploadChunkModel.agency_id == agency_id,
                DocumentUploadChunkModel.workflow == "distribution",
                DocumentUploadChunkModel.group_id == group_id,
            )
        )
        manifests: dict[uuid.UUID, list[tuple[int, int, int, int]]] = {}
        for upload_id, chunk_index, chunk_count, file_count, chunk_files in (
            receipts_result.all()
        ):
            manifests.setdefault(upload_id, []).append(
                (chunk_index, chunk_count, file_count, chunk_files)
            )
        for upload_id, manifest in manifests.items():
            ordered = sorted(manifest)
            expected_chunks = ordered[0][1]
            expected_files = ordered[0][2]
            complete = (
                len(ordered) == expected_chunks
                and [item[0] for item in ordered] == list(range(expected_chunks))
                and all(
                    item[1] == expected_chunks and item[2] == expected_files
                    for item in ordered
                )
                and sum(item[3] for item in ordered) == expected_files
            )
            if complete:
                incomplete_processing_ids.discard(upload_id)
    remaining_result = await session.execute(
        select(
            DistributedDocumentModel.batch_id,
            DistributedDocumentModel.match_status,
        ).where(
            DistributedDocumentModel.batch_id.in_([batch.id for batch in batches]),
            DistributedDocumentModel.agency_id == agency_id,
            DistributedDocumentModel.group_id == group_id,
        )
    )
    counts_by_batch: dict[uuid.UUID, tuple[int, int]] = {}
    for batch_id, match_status in remaining_result.all():
        uploaded_count, matched_count = counts_by_batch.get(batch_id, (0, 0))
        counts_by_batch[batch_id] = (
            uploaded_count + 1,
            matched_count + int(match_status == "matched"),
        )
    for batch in batches:
        uploaded_count, matched_count = counts_by_batch.get(batch.id, (0, 0))
        batch.status = (
            "processing" if batch.id in incomplete_processing_ids else "draft"
        )
        batch.saved_at = None
        batch.uploaded_count = uploaded_count
        batch.matched_count = matched_count
        batch.updated_at = now


@router.get("/groups", response_model=list[DocumentGroupResponse])
async def list_document_groups(
    search: Annotated[str | None, Query(max_length=160)] = None,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[DocumentGroupResponse]:
    if not current_user.agency_id or current_user.role == UserRole.AGENCY_COORDINATOR:
        return []

    stmt = select(ClientGroupModel).where(ClientGroupModel.agency_id == current_user.agency_id)
    stmt = stmt.where(ClientGroupModel.status.notin_(["archived", "deleted"]))
    stmt = AuthorizationPolicy.apply_group_visibility_scope(stmt, current_user)
    normalized_search = search.strip() if search else ""
    if normalized_search:
        passenger_group_ids = select(PassportSubmissionModel.group_id).where(
            PassportSubmissionModel.agency_id == current_user.agency_id,
            PassportSubmissionModel.status.in_(_submitted_statuses()),
            PassportSubmissionModel.client_name.icontains(
                normalized_search,
                autoescape=True,
            ),
        )
        stmt = stmt.where(
            or_(
                ClientGroupModel.name.icontains(normalized_search, autoescape=True),
                ClientGroupModel.destination.icontains(
                    normalized_search,
                    autoescape=True,
                ),
                ClientGroupModel.id.in_(passenger_group_ids),
            )
        )
    stmt = stmt.order_by(ClientGroupModel.created_at.desc())
    result = await session.execute(stmt)
    groups = result.scalars().all()

    assigned_counts: dict[tuple[uuid.UUID, str], int] = {}
    if groups:
        assigned_count_result = await session.execute(
            select(
                DistributedDocumentModel.group_id,
                DistributedDocumentModel.document_type,
                func.count(func.distinct(DistributedDocumentModel.passenger_id)),
            )
            .join(
                PassportSubmissionModel,
                PassportSubmissionModel.id == DistributedDocumentModel.passenger_id,
            )
            .where(
                DistributedDocumentModel.agency_id == current_user.agency_id,
                DistributedDocumentModel.group_id.in_([group.id for group in groups]),
                DistributedDocumentModel.document_type.in_(tuple(DOCUMENT_TYPES)),
                PassportSubmissionModel.group_id == DistributedDocumentModel.group_id,
                PassportSubmissionModel.status.in_(_submitted_statuses()),
            )
            .group_by(
                DistributedDocumentModel.group_id,
                DistributedDocumentModel.document_type,
            )
        )
        assigned_counts = {
            (group_id, document_type): int(count or 0)
            for group_id, document_type, count in assigned_count_result.all()
        }

    passenger_counts: dict[uuid.UUID, int] = {}
    if groups:
        passenger_count_result = await session.execute(
            select(
                PassportSubmissionModel.group_id,
                func.count(PassportSubmissionModel.id),
            )
            .where(
                PassportSubmissionModel.agency_id == current_user.agency_id,
                PassportSubmissionModel.group_id.in_([group.id for group in groups]),
                PassportSubmissionModel.status.in_(_submitted_statuses()),
            )
            .group_by(PassportSubmissionModel.group_id)
        )
        passenger_counts = {
            group_id: int(count or 0)
            for group_id, count in passenger_count_result.all()
        }

    responses: list[DocumentGroupResponse] = []
    for group in groups:
        responses.append(
            DocumentGroupResponse(
                group_id=group.id,
                group_name=group.name,
                group_status=group.status,
                destination=group.destination,
                travel_date=group.travel_date.isoformat() if group.travel_date else None,
                total_passengers=passenger_counts.get(group.id, 0),
                visa_assigned_count=assigned_counts.get((group.id, VISA_DOCUMENT_TYPE), 0),
                flight_ticket_assigned_count=assigned_counts.get(
                    (group.id, INTERNATIONAL_ONWARD_DOCUMENT_TYPE),
                    0,
                ),
                flight_ticket_arrival_assigned_count=assigned_counts.get(
                    (group.id, INTERNATIONAL_RETURN_DOCUMENT_TYPE),
                    0,
                ),
                flight_ticket_domestic_assigned_count=assigned_counts.get(
                    (group.id, DOMESTIC_ONWARD_DOCUMENT_TYPE),
                    0,
                ),
                flight_ticket_domestic_arrival_assigned_count=assigned_counts.get(
                    (group.id, DOMESTIC_RETURN_DOCUMENT_TYPE),
                    0,
                ),
                other_assigned_count=assigned_counts.get((group.id, OTHER_DOCUMENT_TYPE), 0),
            )
        )
    return responses


async def _load_document_review(
    group_id: uuid.UUID,
    document_type: str,
    *,
    current_user: User,
    session: AsyncSession,
) -> tuple[ClientGroupModel, DocumentBatchResponse]:
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported document type"
        )
    group = await _get_authorized_group(
        group_id,
        current_user=current_user,
        session=session,
    )
    passengers = await _group_passengers(group_id, current_user=current_user, session=session)
    result = await session.execute(
        select(DocumentDistributionBatchModel)
        .where(
            DocumentDistributionBatchModel.group_id == group_id,
            DocumentDistributionBatchModel.agency_id == group.agency_id,
            DocumentDistributionBatchModel.document_type == document_type,
        )
        .order_by(DocumentDistributionBatchModel.created_at.desc())
        .limit(1)
    )
    batch = result.scalar_one_or_none()
    documents = await _all_group_documents(
        session,
        group_id=group_id,
        agency_id=group.agency_id,
        document_type=document_type,
    )
    return (
        group,
        await _batch_response(
            session=session,
            group_id=group_id,
            agency_id=group.agency_id,
            document_type=document_type,
            passengers=passengers,
            batch=batch,
            documents=documents,
        ),
    )


@router.get("/groups/{group_id}/{document_type}", response_model=DocumentBatchResponse)
async def get_document_review(
    group_id: uuid.UUID,
    document_type: str,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> DocumentBatchResponse:
    _, review = await _load_document_review(
        group_id,
        document_type,
        current_user=current_user,
        session=session,
    )
    return review


@router.get("/groups/{group_id}/{document_type}/export.xlsx")
async def export_document_assignments(
    group_id: uuid.UUID,
    document_type: str,
    review_filter: Annotated[
        Literal["all", "assigned", "missing", "sent", "not_sent"],
        Query(alias="filter"),
    ] = "all",
    search: Annotated[str, Query(max_length=200)] = "",
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    group, review = await _load_document_review(
        group_id,
        document_type,
        current_user=current_user,
        session=session,
    )
    filter_labels = {
        "all": "All",
        "assigned": "Assigned",
        "missing": "Missing",
        "sent": "Sent",
        "not_sent": "Not sent",
    }
    rows = _document_assignment_export_rows(
        review.review_rows,
        review_filter=review_filter,
        search_query=search,
    )
    workbook = build_document_assignment_workbook(
        group_name=group.name,
        document_label=document_type_label(document_type),
        filter_label=filter_labels[review_filter],
        search_query=search,
        rows=rows,
    )
    filename = (
        _safe_filename(
            f"{group.name}-{document_type}-{review_filter}-document-assignments"
        )
        + ".xlsx"
    )
    return StreamingResponse(
        workbook,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/groups/{group_id}/{document_type}/verify",
    response_model=VerifyDocumentBatchResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def verify_documents(
    group_id: uuid.UUID,
    document_type: str,
    files: list[UploadFile] = File(...),
    upload_id: Annotated[uuid.UUID | None, Form()] = None,
    chunk_id: Annotated[uuid.UUID | None, Form()] = None,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> VerifyDocumentBatchResponse:
    started_at = perf_counter()
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported document type"
        )
    if (upload_id is None) != (chunk_id is None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document verification session metadata is incomplete",
        )
    group = await _get_authorized_group(group_id, current_user=current_user, session=session)
    passengers = await _group_passengers(group_id, current_user=current_user, session=session)
    if not passengers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This group has no passengers to match documents against",
        )

    matcher = DocumentMatcher()
    linked_source = await _read_linked_document_match_source(
        session,
        group=group,
        lock=False,
    )
    supplemental_identifiers = await _linked_document_match_identifiers(
        session,
        group=group,
        passengers=passengers,
        matcher=matcher,
        source=linked_source,
    )
    roster_fingerprint, source_fingerprint, identifiers_fingerprint = (
        verification_scope_fingerprints(
            roster_snapshot=_document_match_roster_snapshot(passengers),
            source_snapshot=linked_source.snapshot,
            identifiers=supplemental_identifiers,
        )
    )
    agency_id = group.agency_id
    await session.rollback()
    phase_started_at = perf_counter()
    uploads = await read_bounded_document_uploads(files)
    upload_read_ms = (perf_counter() - phase_started_at) * 1000
    phase_started_at = perf_counter()
    match_index = await asyncio.to_thread(
        matcher.build_index,
        passengers,
        agency_id=agency_id,
        group_id=group_id,
        supplemental_identifiers=supplemental_identifiers,
    )
    match_index_ms = (perf_counter() - phase_started_at) * 1000
    passengers_by_id = {passenger.id: passenger for passenger in passengers}
    phase_started_at = perf_counter()
    try:
        classifications = await asyncio.to_thread(
            classify_documents_bounded,
            matcher,
            [
                (upload.filename, upload.content, document_type)
                for upload in uploads
            ],
            isolate_pdf_parsing=True,
            batch_timeout_seconds=bounded_pdf_batch_timeout_seconds(len(uploads)),
            reject_common_unsupported_format=True,
        )
    except UnsupportedDocumentBatchFormatError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc
    except DocumentParserUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
            headers={"Retry-After": "1"},
        ) from exc
    classification_ms = (perf_counter() - phase_started_at) * 1000

    def match_classifications() -> list[list[MatchResult]]:
        return [
            matcher.match_all(classification, passengers, index=match_index)
            if classification.accepted
            else []
            for classification in classifications
        ]

    phase_started_at = perf_counter()
    matches_by_classification = await asyncio.to_thread(match_classifications)
    matching_ms = (perf_counter() - phase_started_at) * 1000
    allowed_passenger_ids = set(passengers_by_id)
    uploadable_matches_by_classification = [
        automatic_passenger_matches(
            matches,
            allowed_passenger_ids=allowed_passenger_ids,
        )
        for matches in matches_by_classification
    ]
    accepted_indexes = [
        index
        for index, (classification, matches) in enumerate(
            zip(
                classifications,
                uploadable_matches_by_classification,
                strict=True,
            )
        )
        if classification.accepted and matches
    ]
    # Older clients do not send upload-session metadata. They keep the
    # established raw multipart finalization path and receive no unbound
    # receipts.
    staging_tokens: list[str] | None = (
        [] if upload_id is not None and chunk_id is not None else None
    )
    phase_started_at = perf_counter()
    if accepted_indexes and upload_id is not None and chunk_id is not None:
        try:
            staging_tokens = await stage_verified_documents(
                [
                    VerificationStagingInput(
                        filename=uploads[index].filename,
                        content=uploads[index].content,
                        content_type=uploads[index].content_type,
                        classification=classifications[index],
                    )
                    for index in accepted_indexes
                ],
                agency_id=agency_id,
                actor_id=current_user.id,
                group_id=group_id,
                upload_id=upload_id,
                chunk_id=chunk_id,
                document_type=document_type,
                roster_fingerprint=roster_fingerprint,
                source_fingerprint=source_fingerprint,
                identifiers_fingerprint=identifiers_fingerprint,
            )
        except StorageError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Verified PDF staging is temporarily unavailable. Please try again.",
                headers={"Retry-After": "1"},
            ) from exc
    staging_ms = (perf_counter() - phase_started_at) * 1000
    staging_token_by_index = (
        dict(zip(accepted_indexes, staging_tokens, strict=True))
        if staging_tokens is not None
        else {}
    )

    verified: list[VerifiedDocumentResponse] = []
    for index, (upload, classification, candidate_matches, matches) in enumerate(
        zip(
            uploads,
            classifications,
            matches_by_classification,
            uploadable_matches_by_classification,
            strict=True,
        )
    ):
        matched_passengers = [
            passengers_by_id[match.passenger_id]
            for match in matches
            if match.passenger_id in passengers_by_id
        ]
        primary_match = matches[0] if matches else None
        feedback_match = primary_match or (
            candidate_matches[0] if candidate_matches else None
        )
        primary_passenger = matched_passengers[0] if matched_passengers else None
        is_uploadable = classification.accepted and bool(matches)
        rejection_reason = (
            feedback_match.reason
            if classification.accepted and not is_uploadable and feedback_match
            else "No passenger match found"
            if classification.accepted and not is_uploadable
            else classification.reason
        )
        verified.append(
            VerifiedDocumentResponse(
                filename=upload.filename,
                detected_type=classification.detected_type,
                accepted=is_uploadable,
                reason=rejection_reason,
                matched_passenger_id=primary_match.passenger_id if primary_match else None,
                matched_passenger_name=primary_passenger.client_name if primary_passenger else None,
                matched_passenger_ids=[
                    match.passenger_id for match in matches if match.passenger_id
                ],
                matched_passenger_names=[passenger.client_name for passenger in matched_passengers],
                match_confidence=feedback_match.confidence if feedback_match else 0.0,
                match_status=feedback_match.status if feedback_match else None,
                match_reason=(
                    f"Matched {len(matched_passengers)} passengers in one PDF"
                    if len(matched_passengers) > 1
                    else feedback_match.reason
                    if feedback_match
                    else None
                ),
                staging_receipt=staging_token_by_index.get(index),
            )
        )

    accepted_count = sum(1 for item in verified if item.accepted)
    response = VerifyDocumentBatchResponse(
        group_id=group_id,
        document_type=document_type,
        total_count=len(verified),
        accepted_count=accepted_count,
        rejected_count=len(verified) - accepted_count,
        files=verified,
    )
    logger.info(
        "document_distribution_verify_completed",
        document_type=document_type,
        file_count=len(verified),
        accepted_count=accepted_count,
        rejected_count=len(verified) - accepted_count,
        staging_enabled=staging_tokens is not None,
        upload_read_ms=round(upload_read_ms, 1),
        match_index_ms=round(match_index_ms, 1),
        classification_ms=round(classification_ms, 1),
        matching_ms=round(matching_ms, 1),
        staging_ms=round(staging_ms, 1),
        duration_ms=round((perf_counter() - started_at) * 1000, 1),
    )
    return response


@router.post(
    "/groups/{group_id}/{document_type}/upload",
    response_model=DocumentBatchResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_cookie_csrf)],
)
@_with_staging_cleanup
async def upload_documents(
    group_id: uuid.UUID,
    document_type: str,
    files: Annotated[list[UploadFile] | None, File()] = None,
    staging_receipts: Annotated[list[str] | None, Form()] = None,
    upload_id: Annotated[uuid.UUID | None, Form()] = None,
    chunk_id: Annotated[uuid.UUID | None, Form()] = None,
    chunk_index: Annotated[int | None, Form()] = None,
    expected_chunk_count: Annotated[int | None, Form()] = None,
    expected_file_count: Annotated[int | None, Form()] = None,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> DocumentBatchResponse:
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported document type"
        )
    if (upload_id is None) != (chunk_id is None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document verification session metadata is incomplete",
        )
    uploaded_files = files or []
    receipt_tokens = [token for token in (staging_receipts or []) if token]
    if (not uploaded_files and not receipt_tokens) or (uploaded_files and receipt_tokens):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload PDFs or verified staging receipts, but not both",
        )
    incoming_file_count = len(receipt_tokens) if receipt_tokens else len(uploaded_files)
    chunk_metadata = resolve_document_chunk_metadata(
        upload_id=upload_id,
        chunk_id=chunk_id,
        chunk_index=chunk_index,
        expected_chunk_count=expected_chunk_count,
        expected_file_count=expected_file_count,
    )
    validate_document_chunk_size(chunk_metadata, file_count=incoming_file_count)
    if receipt_tokens and chunk_metadata is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verified staging receipts require an upload session",
        )
    if receipt_tokens:
        try:
            validate_verification_receipt_token_batch(receipt_tokens)
        except VerificationReceiptBatchTooLargeError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except VerificationReceiptError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
    authorized_group = await _get_authorized_group(
        group_id,
        current_user=current_user,
        session=session,
    )
    if chunk_metadata is not None and chunk_metadata.chunk_index == 0:
        blocking_upload_id = await _first_blocking_processing_upload_id(
            session,
            group_id=group_id,
            agency_id=authorized_group.agency_id,
            document_type=document_type,
            exclude_upload_id=chunk_metadata.upload_id,
        )
        if blocking_upload_id is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Discard or resume the existing incomplete upload before "
                    "starting another one"
                ),
            )
    initial_passengers = await _group_passengers(
        group_id,
        current_user=current_user,
        session=session,
    )
    if not initial_passengers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This group has no passengers to match documents against",
        )
    matcher = DocumentMatcher()
    group = authorized_group
    passengers = initial_passengers
    linked_source = await _read_linked_document_match_source(
        session,
        group=group,
        lock=False,
    )
    supplemental_identifiers = await _linked_document_match_identifiers(
        session,
        group=group,
        passengers=passengers,
        matcher=matcher,
        source=linked_source,
    )
    agency_id = group.agency_id
    roster_fingerprint, source_fingerprint, identifiers_fingerprint = (
        verification_scope_fingerprints(
            roster_snapshot=_document_match_roster_snapshot(passengers),
            source_snapshot=linked_source.snapshot,
            identifiers=supplemental_identifiers,
        )
    )
    await session.rollback()

    staged_receipt_models: list[StagedDocumentReceipt] = []
    preclassified_documents: list[ClassifiedDocument] | None = None
    staged_storage_keys: list[str | None] | None = None
    if receipt_tokens:
        assert chunk_metadata is not None
        try:
            staged_receipt_models = decode_verification_receipts(
                receipt_tokens,
                agency_id=agency_id,
                actor_id=current_user.id,
                group_id=group_id,
                upload_id=chunk_metadata.upload_id,
                chunk_id=chunk_metadata.chunk_id,
                document_type=document_type,
                roster_fingerprint=roster_fingerprint,
                source_fingerprint=source_fingerprint,
                identifiers_fingerprint=identifiers_fingerprint,
            )
        except (VerificationReceiptExpiredError, VerificationReceiptScopeChangedError) as exc:
            _remember_request_staging_keys(exc.storage_keys)
            await finish_cleanup_despite_cancellation(
                _cleanup_remembered_request_staging()
            )
            raise HTTPException(
                status_code=(
                    status.HTTP_410_GONE
                    if isinstance(exc, VerificationReceiptExpiredError)
                    else status.HTTP_409_CONFLICT
                ),
                detail=str(exc),
            ) from exc
        except VerificationReceiptBatchTooLargeError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except VerificationReceiptError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

        chunk_byte_count = sum(receipt.byte_count for receipt in staged_receipt_models)
        _remember_request_staging_keys(
            [receipt.storage_key for receipt in staged_receipt_models]
        )
        per_file_limit = get_settings().upload_max_file_size_bytes
        if (
            chunk_byte_count > MAX_DOCUMENT_BATCH_BYTES
            or any(receipt.byte_count > per_file_limit for receipt in staged_receipt_models)
        ):
            await finish_cleanup_despite_cancellation(
                _cleanup_remembered_request_staging()
            )
            raise HTTPException(
                status_code=413,
                detail="The verified PDF upload exceeds the active size limit",
            )
        fingerprint = (
            staged_document_chunk_fingerprint(staged_receipt_models)
            if chunk_metadata
            else None
        )
        file_payloads = [
            TravelDocumentFile(
                filename=receipt.filename,
                content=b"",
                content_type=receipt.content_type,
            )
            for receipt in staged_receipt_models
        ]
        preclassified_documents = [
            receipt.classification for receipt in staged_receipt_models
        ]
        staged_storage_keys = [receipt.storage_key for receipt in staged_receipt_models]
    else:
        uploads = await read_bounded_document_uploads(uploaded_files)
        chunk_byte_count = sum(len(upload.content) for upload in uploads)
        fingerprint = document_chunk_fingerprint(uploads) if chunk_metadata else None
        file_payloads = [
            TravelDocumentFile(
                filename=upload.filename,
                content=upload.content,
                content_type=upload.content_type,
            )
            for upload in uploads
        ]

    async def cleanup_request_staging() -> None:
        await _cleanup_remembered_request_staging()
    existing_batch: DocumentDistributionBatchModel | None = None
    existing_receipts: list[DocumentUploadChunkModel] = []
    chunk_completes_upload = True
    if chunk_metadata is not None:
        batch_result = await session.execute(
            select(DocumentDistributionBatchModel).where(
                DocumentDistributionBatchModel.id == chunk_metadata.upload_id,
                DocumentDistributionBatchModel.agency_id == agency_id,
                DocumentDistributionBatchModel.group_id == group_id,
                DocumentDistributionBatchModel.document_type == document_type,
            )
        )
        existing_batch = batch_result.scalar_one_or_none()
        if existing_batch is None:
            collision_result = await session.execute(
                select(DocumentDistributionBatchModel.id).where(
                    DocumentDistributionBatchModel.id == chunk_metadata.upload_id
                )
            )
            if collision_result.scalar_one_or_none() is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="The upload session is not available to this group",
                )
        receipt_result = await session.execute(
            select(DocumentUploadChunkModel).where(
                DocumentUploadChunkModel.id == chunk_metadata.chunk_id
            )
        )
        existing_receipt = receipt_result.scalar_one_or_none()
        if existing_receipt is not None:
            assert fingerprint is not None
            validate_existing_document_chunk(
                existing_receipt,
                metadata=chunk_metadata,
                agency_id=agency_id,
                workflow="distribution",
                group_id=group_id,
                document_type=document_type,
                fingerprint=fingerprint,
                file_count=incoming_file_count,
                byte_count=chunk_byte_count,
            )
            if existing_batch is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="The upload session is not available to this group",
                )
            if existing_batch.status == "processing":
                await finish_cleanup_despite_cancellation(cleanup_request_staging())
                return _processing_batch_response(existing_batch)
            documents = await _all_group_documents(
                session,
                group_id=group_id,
                agency_id=agency_id,
                document_type=document_type,
            )
            replay_response = await _batch_response(
                session=session,
                group_id=group_id,
                agency_id=agency_id,
                document_type=document_type,
                passengers=passengers,
                batch=existing_batch,
                documents=documents,
            )
            await finish_cleanup_despite_cancellation(cleanup_request_staging())
            return replay_response
        receipts_result = await session.execute(
            select(DocumentUploadChunkModel)
            .where(
                DocumentUploadChunkModel.upload_id == chunk_metadata.upload_id,
                DocumentUploadChunkModel.agency_id == agency_id,
                DocumentUploadChunkModel.workflow == "distribution",
                DocumentUploadChunkModel.group_id == group_id,
                DocumentUploadChunkModel.document_type == document_type,
            )
            .order_by(DocumentUploadChunkModel.chunk_index.asc())
        )
        existing_receipts = list(receipts_result.scalars().all())
        if (existing_batch is None) != (len(existing_receipts) == 0):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The upload session is incomplete and requires administrator review",
            )
        if existing_batch is not None and existing_batch.status != "processing":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This upload session is already complete",
            )
        chunk_completes_upload = validate_next_document_chunk(
            existing_receipts,
            metadata=chunk_metadata,
            incoming_file_count=incoming_file_count,
            incoming_byte_count=chunk_byte_count,
        )
    roster_snapshot = _document_match_roster_snapshot(passengers)
    if existing_batch is not None:
        # Keep the already-loaded cumulative counters available without
        # retaining a database transaction during untrusted PDF parsing.
        _detach_distribution_batch_before_long_processing(session, existing_batch)
    await session.rollback()

    async def reauthorize_before_persistence() -> tuple[uuid.UUID | None, str | None]:
        actor, _ = await _lock_and_validate_document_match_scope(
            session,
            current_user=current_user,
            group_id=group_id,
            agency_id=agency_id,
            matcher=matcher,
            expected_roster_snapshot=roster_snapshot,
            expected_source_snapshot=linked_source.snapshot,
            expected_supplemental_identifiers=supplemental_identifiers,
        )
        await acquire_document_upload_scope_advisory_lock(
            session,
            agency_id=agency_id,
            group_id=group_id,
            document_type=document_type,
        )
        if chunk_metadata is not None:
            await acquire_document_upload_advisory_lock(
                session,
                workflow="distribution",
                upload_id=chunk_metadata.upload_id,
            )
            serialized_batch_result = await session.execute(
                select(DocumentDistributionBatchModel)
                .where(DocumentDistributionBatchModel.id == chunk_metadata.upload_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            serialized_batch = serialized_batch_result.scalar_one_or_none()
            if serialized_batch is not None and (
                serialized_batch.agency_id != agency_id
                or serialized_batch.group_id != group_id
                or serialized_batch.document_type != document_type
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="The upload session is not available to this group",
                )
            if (
                chunk_metadata.chunk_index == 0
                and serialized_batch is None
                and await _first_blocking_processing_upload_id(
                    session,
                    group_id=group_id,
                    agency_id=agency_id,
                    document_type=document_type,
                    exclude_upload_id=chunk_metadata.upload_id,
                    lock=True,
                )
                is not None
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Discard or resume the existing incomplete upload before "
                        "starting another one"
                    ),
                )
            locked_receipts_result = await session.execute(
                select(DocumentUploadChunkModel)
                .where(
                    DocumentUploadChunkModel.upload_id == chunk_metadata.upload_id,
                    DocumentUploadChunkModel.workflow == "distribution",
                )
                .order_by(DocumentUploadChunkModel.chunk_index.asc())
                .with_for_update()
            )
            locked_receipts = list(locked_receipts_result.scalars().all())
            assert fingerprint is not None
            if resolve_concurrent_document_chunk_replay(
                locked_receipts,
                metadata=chunk_metadata,
                agency_id=agency_id,
                workflow="distribution",
                group_id=group_id,
                document_type=document_type,
                fingerprint=fingerprint,
                file_count=incoming_file_count,
                byte_count=chunk_byte_count,
            ) is not None:
                raise _ConcurrentDocumentChunkReplay
            if serialized_batch is not None and existing_batch is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="The upload session is incomplete and requires administrator review",
                )
            if serialized_batch is None and existing_batch is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="The upload session is no longer available",
                )
            validate_next_document_chunk(
                locked_receipts,
                metadata=chunk_metadata,
                incoming_file_count=incoming_file_count,
                incoming_byte_count=chunk_byte_count,
                )
        return actor.id, actor.email

    async def enforce_capacity_before_persistence(incoming_rows: int) -> None:
        await _enforce_group_document_assignment_capacity(
            session,
            group_id=group_id,
            agency_id=agency_id,
            document_type=document_type,
            incoming_rows=incoming_rows,
        )

    try:
        ingestion = await TravelDocumentIngestionService(session, matcher=matcher).ingest(
            agency_id=agency_id,
            group_id=group_id,
            document_type=document_type,
            passengers=passengers,
            files=file_payloads,
            created_by_user_id=current_user.id,
            actor_email=current_user.email,
            existing_batch=existing_batch,
            batch_id=chunk_metadata.upload_id if chunk_metadata else None,
            supplemental_identifiers=supplemental_identifiers,
            isolate_pdf_parsing=True,
            parser_batch_timeout_seconds=(
                bounded_pdf_batch_timeout_seconds(incoming_file_count)
                if chunk_metadata is not None
                else None
            ),
            reject_common_unsupported_format=True,
            preclassified_documents=preclassified_documents,
            staged_storage_keys=staged_storage_keys,
            require_passenger_match=True,
            before_persistence=reauthorize_before_persistence,
            before_persistence_capacity=enforce_capacity_before_persistence,
        )
    except UnsupportedDocumentBatchFormatError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc
    except _ConcurrentDocumentChunkReplay:
        await finish_cleanup_despite_cancellation(cleanup_request_staging())
        assert chunk_metadata is not None
        replay_batch_result = await session.execute(
            select(DocumentDistributionBatchModel).where(
                DocumentDistributionBatchModel.id == chunk_metadata.upload_id,
                DocumentDistributionBatchModel.agency_id == agency_id,
                DocumentDistributionBatchModel.group_id == group_id,
                DocumentDistributionBatchModel.document_type == document_type,
            )
        )
        replay_batch = replay_batch_result.scalar_one_or_none()
        if replay_batch is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The committed upload session is no longer available",
            )
        if replay_batch.status == "processing":
            return _processing_batch_response(replay_batch)
        documents = await _all_group_documents(
            session,
            group_id=group_id,
            agency_id=agency_id,
            document_type=document_type,
        )
        return await _batch_response(
            session=session,
            group_id=group_id,
            agency_id=agency_id,
            document_type=document_type,
            passengers=passengers,
            batch=replay_batch,
            documents=documents,
        )
    except DocumentParserUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
            headers={"Retry-After": "1"},
        ) from exc
    except DocumentDistributionCapacityError as exc:
        await finish_cleanup_despite_cancellation(cleanup_request_staging())
        raise HTTPException(
            status_code=413,
            detail=str(exc),
        ) from exc
    if chunk_metadata is not None:
        ingestion.batch.status = "draft" if chunk_completes_upload else "processing"
        assert fingerprint is not None
        session.add(
            new_document_chunk_receipt(
                metadata=chunk_metadata,
                agency_id=agency_id,
                workflow="distribution",
                group_id=group_id,
                document_type=document_type,
                fingerprint=fingerprint,
                file_count=incoming_file_count,
                byte_count=chunk_byte_count,
                accepted_count=incoming_file_count - len(ingestion.rejected),
                rejected_count=len(ingestion.rejected),
                rejected_documents=[
                    {
                        "filename": item.filename,
                        "detected_type": item.detected_type,
                        "reason": item.reason,
                    }
                    for item in ingestion.rejected
                ],
            )
        )
        try:
            await session.flush()
        except BaseException:
            await session.rollback()
            await _cleanup_distribution_storage_keys(
                list(ingestion.created_storage_keys),
                agency_id=agency_id,
                group_id=group_id,
                document_type=document_type,
            )
            raise
    try:
        await session.commit()
    except BaseException:
        # COMMIT acknowledgement can be lost after PostgreSQL made the rows
        # durable. Keep objects that those rows may reference for safe
        # operational reconciliation; remove only proven orphaned keys.
        await session.rollback()
        logger.warning(
            "document_distribution_commit_outcome_ambiguous",
            group_id=str(group_id),
            document_type=document_type,
            object_count=len(ingestion.created_storage_keys),
        )
        raise
    await finish_cleanup_despite_cancellation(cleanup_request_staging())
    if ingestion.batch.status == "processing":
        return _processing_batch_response(ingestion.batch)
    documents = await _all_group_documents(
        session,
        group_id=group_id,
        agency_id=agency_id,
        document_type=document_type,
    )
    return await _batch_response(
        session=session,
        group_id=group_id,
        agency_id=agency_id,
        document_type=document_type,
        passengers=passengers,
        batch=ingestion.batch,
        documents=documents,
        rejected_documents=(
            [
                RejectedDocumentResponse(
                    filename=item.filename,
                    detected_type=item.detected_type,
                    reason=item.reason,
                )
                for item in ingestion.rejected
            ]
            if chunk_metadata is None
            else None
        ),
    )


@router.post(
    "/groups/{group_id}/{document_type}/uploads/{batch_id}/abort",
    response_model=AbortDocumentUploadResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def abort_incomplete_distribution_upload(
    group_id: uuid.UUID,
    document_type: str,
    batch_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> AbortDocumentUploadResponse:
    """Discard one incomplete upload without affecting any completed batch."""

    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported document type",
        )
    group = await _get_authorized_group(
        group_id,
        current_user=current_user,
        session=session,
    )
    actor, _ = await _lock_active_document_scope(
        session,
        current_user=current_user,
        group_id=group_id,
        agency_id=group.agency_id,
    )
    await acquire_document_upload_scope_advisory_lock(
        session,
        agency_id=group.agency_id,
        group_id=group_id,
        document_type=document_type,
    )
    await acquire_document_upload_advisory_lock(
        session,
        workflow="distribution",
        upload_id=batch_id,
    )

    batch_result = await session.execute(
        select(DocumentDistributionBatchModel)
        .where(
            DocumentDistributionBatchModel.id == batch_id,
            DocumentDistributionBatchModel.agency_id == group.agency_id,
            DocumentDistributionBatchModel.group_id == group_id,
            DocumentDistributionBatchModel.document_type == document_type,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    batch = batch_result.scalar_one_or_none()
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Incomplete document upload was not found",
        )
    if batch.status != "processing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only an incomplete processing upload can be discarded",
        )

    receipts_result = await session.execute(
        select(DocumentUploadChunkModel)
        .where(
            DocumentUploadChunkModel.upload_id == batch_id,
            DocumentUploadChunkModel.agency_id == group.agency_id,
            DocumentUploadChunkModel.workflow == "distribution",
            DocumentUploadChunkModel.group_id == group_id,
            DocumentUploadChunkModel.document_type == document_type,
        )
        .order_by(
            DocumentUploadChunkModel.chunk_index.asc(),
            DocumentUploadChunkModel.id.asc(),
        )
        .with_for_update()
    )
    receipts = list(receipts_result.scalars().all())
    documents_result = await session.execute(
        select(DistributedDocumentModel)
        .where(
            DistributedDocumentModel.batch_id == batch_id,
            DistributedDocumentModel.agency_id == group.agency_id,
            DistributedDocumentModel.group_id == group_id,
            DistributedDocumentModel.document_type == document_type,
        )
        .order_by(DistributedDocumentModel.id.asc())
        .with_for_update()
    )
    documents = list(documents_result.scalars().all())

    delivery_result = await session.execute(
        select(DocumentWhatsAppDeliveryModel.id)
        .where(
            DocumentWhatsAppDeliveryModel.document_batch_id == batch_id,
            DocumentWhatsAppDeliveryModel.agency_id == group.agency_id,
            DocumentWhatsAppDeliveryModel.group_id == group_id,
            DocumentWhatsAppDeliveryModel.document_type == document_type,
        )
        .order_by(DocumentWhatsAppDeliveryModel.id.asc())
        .with_for_update()
        .limit(1)
    )
    if delivery_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This upload has delivery history and cannot be discarded",
        )

    candidate_storage_keys = sorted({document.storage_key for document in documents})
    still_used_storage_keys: set[str] = set()
    if candidate_storage_keys:
        remaining_key_result = await session.execute(
            select(DistributedDocumentModel.storage_key)
            .where(
                DistributedDocumentModel.storage_key.in_(candidate_storage_keys),
                DistributedDocumentModel.batch_id != batch_id,
            )
            .order_by(DistributedDocumentModel.storage_key.asc())
            .with_for_update()
        )
        still_used_storage_keys = set(remaining_key_result.scalars().all())
    delete_storage_keys = [
        key for key in candidate_storage_keys if key not in still_used_storage_keys
    ]
    cleanup_jobs = stage_storage_cleanup_jobs(
        session,
        agency_id=group.agency_id,
        source="document_distribution_abort",
        context_id=str(batch_id),
        storage_keys=delete_storage_keys,
    )

    await session.execute(
        delete(DistributedDocumentModel)
        .where(
            DistributedDocumentModel.batch_id == batch_id,
            DistributedDocumentModel.agency_id == group.agency_id,
            DistributedDocumentModel.group_id == group_id,
            DistributedDocumentModel.document_type == document_type,
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        delete(DocumentUploadChunkModel)
        .where(
            DocumentUploadChunkModel.upload_id == batch_id,
            DocumentUploadChunkModel.agency_id == group.agency_id,
            DocumentUploadChunkModel.workflow == "distribution",
            DocumentUploadChunkModel.group_id == group_id,
            DocumentUploadChunkModel.document_type == document_type,
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        delete(DocumentDistributionBatchModel)
        .where(
            DocumentDistributionBatchModel.id == batch_id,
            DocumentDistributionBatchModel.agency_id == group.agency_id,
            DocumentDistributionBatchModel.group_id == group_id,
            DocumentDistributionBatchModel.document_type == document_type,
            DocumentDistributionBatchModel.status == "processing",
        )
        .execution_options(synchronize_session=False)
    )
    remaining_result = await session.execute(
        select(DocumentDistributionBatchModel.id)
        .where(
            DocumentDistributionBatchModel.agency_id == group.agency_id,
            DocumentDistributionBatchModel.group_id == group_id,
            DocumentDistributionBatchModel.document_type == document_type,
            DocumentDistributionBatchModel.status == "processing",
            DocumentDistributionBatchModel.id != batch_id,
        )
        .order_by(
            DocumentDistributionBatchModel.created_at.desc(),
            DocumentDistributionBatchModel.id.desc(),
        )
        .with_for_update()
    )
    remaining_processing_upload_ids = list(remaining_result.scalars().all())
    await AuditLogRepository(session).record(
        action="document_distribution_upload_aborted",
        entity_type="document_distribution_batch",
        entity_id=str(batch_id),
        agency_id=group.agency_id,
        user_id=actor.id,
        metadata={
            "group_id": str(group_id),
            "document_type": document_type,
            "deleted_document_count": len(documents),
            "deleted_chunk_count": len(receipts),
            "deleted_storage_object_count": len(delete_storage_keys),
            "remaining_processing_upload_count": len(remaining_processing_upload_ids),
        },
    )
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    storage_cleanup_pending = False
    for cleanup_job in cleanup_jobs:
        try:
            cleanup_result = await process_storage_cleanup_job(cleanup_job.id)
            if cleanup_result is None or not cleanup_result.completed:
                storage_cleanup_pending = True
        except Exception as exc:
            storage_cleanup_pending = True
            logger.warning(
                "document_distribution_abort_cleanup_deferred",
                batch_id=str(batch_id),
                group_id=str(group_id),
                document_type=document_type,
                cleanup_job_id=str(cleanup_job.id),
                object_count=cleanup_job.object_count,
                error_type=type(exc).__name__,
            )

    return AbortDocumentUploadResponse(
        batch_id=batch_id,
        deleted_document_count=len(documents),
        deleted_chunk_count=len(receipts),
        deleted_storage_object_count=len(delete_storage_keys),
        storage_cleanup_pending=storage_cleanup_pending,
        remaining_processing_upload_ids=remaining_processing_upload_ids,
    )


@router.post(
    "/groups/{group_id}/{document_type}/passengers/{passenger_id}/reupload",
    response_model=DocumentBatchResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_cookie_csrf)],
)
async def reupload_passenger_document(
    group_id: uuid.UUID,
    document_type: str,
    passenger_id: uuid.UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> DocumentBatchResponse:
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported document type"
        )
    await _get_authorized_group(group_id, current_user=current_user, session=session)
    initial_passengers = await _group_passengers(
        group_id,
        current_user=current_user,
        session=session,
    )
    if all(item.id != passenger_id for item in initial_passengers):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Passenger was not found in this group"
        )
    await session.rollback()
    upload = (await read_bounded_document_uploads([file]))[0]
    content = upload.content
    filename = upload.filename
    matcher = DocumentMatcher()
    try:
        classification = (
            await asyncio.to_thread(
                classify_documents_bounded,
                matcher,
                [(filename, content, document_type)],
                isolate_pdf_parsing=True,
            )
        )[0]
    except DocumentParserUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
            headers={"Retry-After": "1"},
        ) from exc
    if not classification.accepted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{filename}: {classification.reason}",
        )
    group = await _get_authorized_group(group_id, current_user=current_user, session=session)
    passengers = await _group_passengers(group_id, current_user=current_user, session=session)
    if all(item.id != passenger_id for item in passengers):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The selected passenger changed while the PDF was being prepared",
        )
    agency_id = group.agency_id
    roster_snapshot = _document_match_roster_snapshot(passengers)
    linked_source = await _read_linked_document_match_source(
        session,
        group=group,
        lock=False,
    )
    await session.rollback()

    async def reauthorize_before_persistence() -> tuple[uuid.UUID | None, str | None]:
        actor, _ = await _lock_and_validate_document_match_scope(
            session,
            current_user=current_user,
            group_id=group_id,
            agency_id=agency_id,
            matcher=matcher,
            expected_roster_snapshot=roster_snapshot,
            expected_source_snapshot=linked_source.snapshot,
            expected_supplemental_identifiers=None,
            required_passenger_id=passenger_id,
        )
        await acquire_document_upload_scope_advisory_lock(
            session,
            agency_id=agency_id,
            group_id=group_id,
            document_type=document_type,
        )
        return actor.id, actor.email

    async def enforce_capacity_before_persistence(incoming_rows: int) -> None:
        await _enforce_group_document_assignment_capacity(
            session,
            group_id=group_id,
            agency_id=agency_id,
            document_type=document_type,
            incoming_rows=incoming_rows,
        )

    ingestion = None
    try:
        ingestion = await TravelDocumentIngestionService(session).ingest(
            agency_id=agency_id,
            group_id=group_id,
            document_type=document_type,
            passengers=passengers,
            files=[
                TravelDocumentFile(
                    filename=filename,
                    content=content,
                    content_type=upload.content_type,
                )
            ],
            created_by_user_id=current_user.id,
            actor_email=current_user.email,
            forced_passenger_id=passenger_id,
            audit_source="dashboard_passenger_add",
            isolate_pdf_parsing=True,
            before_persistence=reauthorize_before_persistence,
            before_persistence_capacity=enforce_capacity_before_persistence,
        )
        await AuditLogRepository(session).record(
            action="document_distribution_passenger_document_added",
            entity_type="document_distribution_batch",
            entity_id=str(ingestion.batch.id),
            agency_id=agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            metadata={
                "group_id": str(group_id),
                "passenger_id": str(passenger_id),
                "document_type": document_type,
                "filename": filename,
            },
        )
    except DocumentDistributionCapacityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=413,
            detail=str(exc),
        ) from exc
    except Exception:
        await session.rollback()
        if ingestion is not None:
            await _cleanup_distribution_storage_keys(
                list(ingestion.created_storage_keys),
                agency_id=agency_id,
                group_id=group_id,
                document_type=document_type,
            )
        raise
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        logger.warning(
            "document_distribution_commit_outcome_ambiguous",
            group_id=str(group_id),
            document_type=document_type,
            object_count=len(ingestion.created_storage_keys),
        )
        raise
    documents = await _all_group_documents(
        session,
        group_id=group_id,
        agency_id=agency_id,
        document_type=document_type,
    )
    return await _batch_response(
        session=session,
        group_id=group_id,
        agency_id=agency_id,
        document_type=document_type,
        passengers=passengers,
        batch=ingestion.batch,
        documents=documents,
    )


@router.post(
    "/groups/{group_id}/{document_type}/documents/unassign",
    response_model=DocumentBatchResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def unassign_distribution_documents(
    group_id: uuid.UUID,
    document_type: str,
    payload: DeleteDistributionDocumentsRequest,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> DocumentBatchResponse:
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported document type"
        )
    group = await _get_authorized_group(
        group_id,
        current_user=current_user,
        session=session,
    )
    passengers = await _group_passengers(
        group_id,
        current_user=current_user,
        session=session,
    )
    document_ids = list(dict.fromkeys(payload.document_ids))
    if not document_ids:
        batch = await _latest_document_batch(
            session,
            group_id=group_id,
            agency_id=group.agency_id,
            document_type=document_type,
        )
        documents = await _all_group_documents(
            session,
            group_id=group_id,
            agency_id=group.agency_id,
            document_type=document_type,
        )
        return await _batch_response(
            session=session,
            group_id=group_id,
            agency_id=group.agency_id,
            document_type=document_type,
            passengers=passengers,
            batch=batch,
            documents=documents,
        )

    await session.execute(
        select(DocumentDistributionBatchModel.id)
        .where(
            DocumentDistributionBatchModel.group_id == group_id,
            DocumentDistributionBatchModel.agency_id == group.agency_id,
            DocumentDistributionBatchModel.document_type == document_type,
        )
        .order_by(DocumentDistributionBatchModel.id)
        .with_for_update()
    )
    documents_result = await session.execute(
        select(DistributedDocumentModel)
        .where(
            DistributedDocumentModel.id.in_(document_ids),
            DistributedDocumentModel.group_id == group_id,
            DistributedDocumentModel.agency_id == group.agency_id,
            DistributedDocumentModel.document_type == document_type,
            DistributedDocumentModel.passenger_id.is_not(None),
        )
        .with_for_update()
    )
    documents_to_unassign = list(documents_result.scalars().all())
    if not documents_to_unassign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No assigned documents were found",
        )
    released_passenger_ids = await _released_document_passenger_ids(
        session,
        agency_id=group.agency_id,
        group_id=group_id,
        document_ids=[document.id for document in documents_to_unassign],
    )

    active_delivery_result = await session.execute(
        select(DocumentWhatsAppDeliveryModel.id)
        .where(
            DocumentWhatsAppDeliveryModel.distributed_document_id.in_(
                [document.id for document in documents_to_unassign]
            ),
            DocumentWhatsAppDeliveryModel.agency_id == group.agency_id,
            DocumentWhatsAppDeliveryModel.group_id == group_id,
            DocumentWhatsAppDeliveryModel.status.in_(DOCUMENT_DELIVERY_STORAGE_REQUIRED_STATUSES),
        )
        .with_for_update()
        .limit(1)
    )
    if active_delivery_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A selected document is currently being sent through WhatsApp. "
                "Wait for delivery processing to finish before removing its assignment."
            ),
        )

    affected_batch_ids = {document.batch_id for document in documents_to_unassign}
    now = datetime.now(tz=UTC)
    for document in documents_to_unassign:
        document.passenger_id = None
        document.match_status = "needs_review"
        document.match_confidence = 0.0
        document.match_reason = "Assignment removed manually; saved PDF retained for review"
        document.updated_at = now
    await session.flush()
    await _refresh_distribution_batches(
        session,
        batch_ids=affected_batch_ids,
        agency_id=group.agency_id,
        group_id=group_id,
        now=now,
    )
    if released_passenger_ids:
        await propagate_mobile_passenger_change(
            session,
            agency_id=group.agency_id,
            group_id=group_id,
            passenger_submission_ids=released_passenger_ids,
            actor_user_id=current_user.id,
            operation="delete",
            change_kind="documents",
            reconcile_identities=False,
        )
    await AuditLogRepository(session).record(
        action="document_distribution_unassigned",
        entity_type="document_distribution_batch",
        entity_id=str(group_id),
        agency_id=group.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "group_id": str(group_id),
            "document_type": document_type,
            "unassigned_count": len(documents_to_unassign),
            "saved_files_retained": True,
        },
    )
    await session.commit()
    batch = await _latest_document_batch(
        session,
        group_id=group_id,
        agency_id=group.agency_id,
        document_type=document_type,
    )
    remaining_documents = await _all_group_documents(
        session,
        group_id=group_id,
        agency_id=group.agency_id,
        document_type=document_type,
    )
    return await _batch_response(
        session=session,
        group_id=group_id,
        agency_id=group.agency_id,
        document_type=document_type,
        passengers=passengers,
        batch=batch,
        documents=remaining_documents,
    )


@router.post(
    "/groups/{group_id}/{document_type}/documents/delete",
    response_model=DocumentBatchResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def delete_distribution_documents(
    group_id: uuid.UUID,
    document_type: str,
    payload: DeleteDistributionDocumentsRequest,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> DocumentBatchResponse:
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported document type"
        )
    group = await _get_authorized_group(group_id, current_user=current_user, session=session)
    passengers = await _group_passengers(group_id, current_user=current_user, session=session)
    document_ids = list(dict.fromkeys(payload.document_ids))
    if not document_ids:
        batch = await _latest_document_batch(
            session,
            group_id=group_id,
            agency_id=group.agency_id,
            document_type=document_type,
        )
        documents = await _all_group_documents(
            session,
            group_id=group_id,
            agency_id=group.agency_id,
            document_type=document_type,
        )
        return await _batch_response(
            session=session,
            group_id=group_id,
            agency_id=group.agency_id,
            document_type=document_type,
            passengers=passengers,
            batch=batch,
            documents=documents,
        )

    await session.execute(
        select(DocumentDistributionBatchModel.id)
        .where(
            DocumentDistributionBatchModel.group_id == group_id,
            DocumentDistributionBatchModel.agency_id == group.agency_id,
            DocumentDistributionBatchModel.document_type == document_type,
        )
        .order_by(DocumentDistributionBatchModel.id)
        .with_for_update()
    )
    docs_result = await session.execute(
        select(DistributedDocumentModel)
        .where(
            DistributedDocumentModel.id.in_(document_ids),
            DistributedDocumentModel.group_id == group_id,
            DistributedDocumentModel.agency_id == group.agency_id,
            DistributedDocumentModel.document_type == document_type,
        )
        .order_by(DistributedDocumentModel.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    documents_to_delete = list(docs_result.scalars().all())
    if not documents_to_delete:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No matching documents were found"
        )
    released_passenger_ids = await _released_document_passenger_ids(
        session,
        agency_id=group.agency_id,
        group_id=group_id,
        document_ids=[document.id for document in documents_to_delete],
    )

    active_delivery_result = await session.execute(
        select(DocumentWhatsAppDeliveryModel.id)
        .where(
            DocumentWhatsAppDeliveryModel.distributed_document_id.in_(
                [document.id for document in documents_to_delete]
            ),
            DocumentWhatsAppDeliveryModel.agency_id == group.agency_id,
            DocumentWhatsAppDeliveryModel.group_id == group_id,
            DocumentWhatsAppDeliveryModel.status.in_(DOCUMENT_DELIVERY_STORAGE_REQUIRED_STATUSES),
        )
        .with_for_update()
        .limit(1)
    )
    if active_delivery_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A selected document is currently being sent through WhatsApp. "
                "Wait for delivery processing to finish before deleting it."
            ),
        )

    affected_batch_ids = {document.batch_id for document in documents_to_delete}
    candidate_storage_keys = list({document.storage_key for document in documents_to_delete})
    remaining_key_result = await session.execute(
        select(DistributedDocumentModel.storage_key).where(
            DistributedDocumentModel.storage_key.in_(candidate_storage_keys),
            DistributedDocumentModel.id.notin_([document.id for document in documents_to_delete]),
        )
    )
    still_used_storage_keys = set(remaining_key_result.scalars().all())
    delete_storage_keys = [
        key for key in candidate_storage_keys if key not in still_used_storage_keys
    ]
    cleanup_jobs = stage_storage_cleanup_jobs(
        session,
        agency_id=group.agency_id,
        source="document_distribution_delete",
        context_id=(f"{group_id}:{document_type}:" + ",".join(sorted(map(str, document_ids)))),
        storage_keys=delete_storage_keys,
    )
    for document in documents_to_delete:
        await session.delete(document)
    await session.flush()

    now = datetime.now(tz=UTC)
    await _refresh_distribution_batches(
        session,
        batch_ids=affected_batch_ids,
        agency_id=group.agency_id,
        group_id=group_id,
        now=now,
    )
    if released_passenger_ids:
        await propagate_mobile_passenger_change(
            session,
            agency_id=group.agency_id,
            group_id=group_id,
            passenger_submission_ids=released_passenger_ids,
            actor_user_id=current_user.id,
            operation="delete",
            change_kind="documents",
            reconcile_identities=False,
        )
    await AuditLogRepository(session).record(
        action="document_distribution_deleted",
        entity_type="document_distribution_batch",
        entity_id=str(group_id),
        agency_id=group.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "group_id": str(group_id),
            "document_type": document_type,
            "deleted_count": len(documents_to_delete),
            "deleted_storage_objects": len(delete_storage_keys),
        },
    )
    await session.commit()
    for cleanup_job in cleanup_jobs:
        try:
            await process_storage_cleanup_job(cleanup_job.id)
        except Exception as exc:
            # The authoritative rows and durable cleanup job are committed.  A
            # runner outage must not turn that successful deletion into a 500.
            logger.warning(
                "document_distribution_cleanup_runner_deferred",
                cleanup_job_id=str(cleanup_job.id),
                group_id=str(group_id),
                document_type=document_type,
                object_count=cleanup_job.object_count,
                error_type=type(exc).__name__,
            )
    batch = await _latest_document_batch(
        session,
        group_id=group_id,
        agency_id=group.agency_id,
        document_type=document_type,
    )
    remaining_documents = await _all_group_documents(
        session,
        group_id=group_id,
        agency_id=group.agency_id,
        document_type=document_type,
    )
    return await _batch_response(
        session=session,
        group_id=group_id,
        agency_id=group.agency_id,
        document_type=document_type,
        passengers=passengers,
        batch=batch,
        documents=remaining_documents,
    )


@router.post(
    "/batches/{batch_id}/save",
    response_model=SaveDocumentBatchResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def save_batch(
    batch_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> SaveDocumentBatchResponse:
    batch = await _get_visible_document_batch(
        session,
        batch_id=batch_id,
        current_user=current_user,
    )
    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document batch was not found"
        )
    await _get_authorized_group(batch.group_id, current_user=current_user, session=session)
    now = datetime.now(tz=UTC)
    group_batches_result = await session.execute(
        select(DocumentDistributionBatchModel)
        .where(
            DocumentDistributionBatchModel.group_id == batch.group_id,
            DocumentDistributionBatchModel.agency_id == batch.agency_id,
            DocumentDistributionBatchModel.document_type == batch.document_type,
        )
        .order_by(DocumentDistributionBatchModel.id)
        .with_for_update()
    )
    group_batches = list(group_batches_result.scalars().all())
    if any(item.status == "processing" for item in group_batches):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Wait for the document upload to finish before saving the list",
        )
    saved_batches = [item for item in group_batches if item.status != "saved"]
    for pending_batch in saved_batches:
        pending_batch.status = "saved"
        pending_batch.saved_at = now
        pending_batch.updated_at = now
    await AuditLogRepository(session).record(
        action="document_distribution_saved",
        entity_type="document_distribution_batch",
        entity_id=str(batch.id),
        agency_id=batch.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "group_id": str(batch.group_id),
            "document_type": batch.document_type,
            "saved_batch_count": len(saved_batches),
        },
    )
    await session.commit()
    return SaveDocumentBatchResponse(batch_id=batch.id, status=batch.status, saved_at=now)


@router.get(
    "/groups/{group_id}/{document_type}/whatsapp-preview",
    response_model=DocumentDeliveryPreviewResponse,
)
async def preview_document_whatsapp_broadcast(
    group_id: uuid.UUID,
    document_type: str,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> DocumentDeliveryPreviewResponse:
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported document type",
        )
    group = await _get_authorized_group(
        group_id,
        current_user=current_user,
        session=session,
    )
    batch = await _latest_document_batch(
        session,
        group_id=group_id,
        agency_id=group.agency_id,
        document_type=document_type,
    )
    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document batch was not found",
        )
    passengers = await _group_passengers(
        group_id,
        current_user=current_user,
        session=session,
    )
    return await _build_document_delivery_preview(
        session,
        group=group,
        batch=batch,
        passengers=passengers,
    )


async def _lock_retry_document_deliveries(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    delivery_document_ids: dict[uuid.UUID, uuid.UUID],
) -> dict[uuid.UUID, DocumentWhatsAppDeliveryModel]:
    """Batch-lock retry rows and retain only exact tenant/document ownership."""

    if not delivery_document_ids:
        return {}
    result = await session.execute(
        select(DocumentWhatsAppDeliveryModel)
        .where(
            DocumentWhatsAppDeliveryModel.id.in_(list(delivery_document_ids)),
            DocumentWhatsAppDeliveryModel.agency_id == agency_id,
            DocumentWhatsAppDeliveryModel.group_id == group_id,
            DocumentWhatsAppDeliveryModel.distributed_document_id.in_(
                list(set(delivery_document_ids.values()))
            ),
        )
        .order_by(DocumentWhatsAppDeliveryModel.id)
        .with_for_update()
    )
    return {
        delivery.id: delivery
        for delivery in result.scalars().all()
        if delivery.distributed_document_id == delivery_document_ids.get(delivery.id)
    }


@router.post(
    "/batches/{batch_id}/whatsapp-send",
    response_model=SendDocumentBroadcastResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_cookie_csrf)],
)
async def send_document_whatsapp_broadcast(
    batch_id: uuid.UUID,
    payload: SendDocumentBroadcastRequest,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> SendDocumentBroadcastResponse:
    message_content_1 = payload.message_content_1.strip()
    message_content_2 = payload.message_content_2.strip()
    if not message_content_1 or not message_content_2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Both editable document message sections are required",
        )
    batch = await _get_visible_document_batch(
        session,
        batch_id=batch_id,
        current_user=current_user,
    )
    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document batch was not found",
        )
    group = await _get_authorized_group(
        batch.group_id,
        current_user=current_user,
        session=session,
    )
    # Serialize the whole group/type ledger, not just the caller's possibly
    # stale batch id. This closes the race where two clients could otherwise
    # create concurrent first-send or explicit-resend attempts.
    await session.execute(
        select(DocumentDistributionBatchModel.id)
        .where(
            DocumentDistributionBatchModel.group_id == batch.group_id,
            DocumentDistributionBatchModel.agency_id == batch.agency_id,
            DocumentDistributionBatchModel.document_type == batch.document_type,
        )
        .order_by(DocumentDistributionBatchModel.id)
        .with_for_update()
    )
    passengers = await _group_passengers(
        batch.group_id,
        current_user=current_user,
        session=session,
    )
    preview = await _build_document_delivery_preview(
        session,
        group=group,
        batch=batch,
        passengers=passengers,
    )
    if not preview.can_send:
        error_status = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if not preview.template_configured
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(
            status_code=error_status,
            detail=preview.configuration_error or "Documents are not ready to send",
        )

    requested_ids = (
        set(payload.document_ids)
        if payload.document_ids is not None
        else {row.document_id for row in preview.recipients if row.document_id and row.eligible}
    )
    resend_ids = set(payload.resend_document_ids)
    if not resend_ids.issubset(requested_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Every resend document must also be selected for sending",
        )
    resendable_ids = {
        row.document_id for row in preview.recipients if row.document_id and row.resend_allowed
    }
    invalid_resend_ids = resend_ids - resendable_ids
    if invalid_resend_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=("A selected resend is not eligible. Refresh the preview before trying again."),
        )
    eligible_rows = [
        row
        for row in preview.recipients
        if row.document_id in requested_ids and (row.eligible or row.document_id in resend_ids)
    ]
    if not eligible_rows:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Select at least one new or safely retryable document",
        )

    send_batch_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    template_name = preview.template_name or ""
    selected_document_result = await session.execute(
        select(DistributedDocumentModel).where(
            DistributedDocumentModel.id.in_(
                [row.document_id for row in eligible_rows if row.document_id]
            ),
            DistributedDocumentModel.group_id == batch.group_id,
            DistributedDocumentModel.agency_id == batch.agency_id,
        )
    )
    selected_documents = {
        document.id: document for document in selected_document_result.scalars().all()
    }
    retry_delivery_document_ids = {
        row.delivery_id: row.document_id
        for row in eligible_rows
        if row.delivery_id
        and row.document_id
        and row.document_id not in resend_ids
    }
    locked_retry_deliveries = await _lock_retry_document_deliveries(
        session,
        agency_id=batch.agency_id,
        group_id=batch.group_id,
        delivery_document_ids=retry_delivery_document_ids,
    )
    queued_count = 0
    for row in eligible_rows:
        if not (
            row.document_id
            and row.recipient_id
            and row.broadcast_group_id
            and row.phone_number
            and row.document_filename
        ):
            continue
        document = selected_documents.get(row.document_id)
        if document is None:
            continue
        explicit_resend = row.document_id in resend_ids
        delivery: DocumentWhatsAppDeliveryModel | None = None
        if row.delivery_id and not explicit_resend:
            delivery = locked_retry_deliveries.get(row.delivery_id)
        if delivery:
            if delivery.status != "failed":
                continue
            delivery.send_batch_id = send_batch_id
            delivery.broadcast_group_id = row.broadcast_group_id
            delivery.recipient_id = row.recipient_id
            delivery.phone_number = row.phone_number
            delivery.normalized_phone_number = row.phone_number
            delivery.template_name = template_name
            delivery.template_parameter_values = [
                message_content_1,
                message_content_2,
            ]
            delivery.status = "queued"
            delivery.status_updated_at = now
            delivery.provider_status_at = None
            delivery.provider_message_id = None
            delivery.provider_media_id = None
            delivery.error_message = None
            delivery.updated_at = now
        else:
            delivery = DocumentWhatsAppDeliveryModel(
                id=uuid.uuid4(),
                agency_id=batch.agency_id,
                group_id=batch.group_id,
                document_batch_id=document.batch_id,
                distributed_document_id=row.document_id,
                passenger_id=row.passenger_id,
                broadcast_group_id=row.broadcast_group_id,
                recipient_id=row.recipient_id,
                send_batch_id=send_batch_id,
                document_type=document.document_type,
                document_filename=row.document_filename,
                passenger_name=row.passenger_name,
                passport_number=row.passport_number,
                phone_number=row.phone_number,
                normalized_phone_number=row.phone_number,
                template_name=template_name,
                template_parameter_values=[
                    message_content_1,
                    message_content_2,
                ],
                status="queued",
                attempt_count=0,
                status_updated_at=now,
                created_by_user_id=current_user.id,
                created_at=now,
                updated_at=now,
            )
            session.add(delivery)
        queued_count += 1

    if not queued_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The selected documents were already claimed by another send",
        )
    await AuditLogRepository(session).record(
        action="document_whatsapp_broadcast_queued",
        entity_type="document_distribution_batch",
        entity_id=str(batch.id),
        agency_id=batch.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "group_id": str(batch.group_id),
            "document_type": batch.document_type,
            "send_batch_id": str(send_batch_id),
            "queued_count": queued_count,
            "explicit_resend_count": len(resend_ids),
            "message_content_lengths": [
                len(message_content_1),
                len(message_content_2),
            ],
        },
    )
    await session.commit()

    from app.infrastructure.whatsapp.tasks import (
        process_document_whatsapp_broadcast,
    )

    try:
        process_document_whatsapp_broadcast.apply_async(
            kwargs={"send_batch_id": str(send_batch_id)},
            queue="whatsapp",
        )
    except Exception as exc:
        failed_result = await session.execute(
            select(DocumentWhatsAppDeliveryModel).where(
                DocumentWhatsAppDeliveryModel.send_batch_id == send_batch_id,
                DocumentWhatsAppDeliveryModel.agency_id == batch.agency_id,
                DocumentWhatsAppDeliveryModel.group_id == batch.group_id,
                DocumentWhatsAppDeliveryModel.status == "queued",
            )
        )
        failure_time = datetime.now(tz=UTC)
        for delivery in failed_result.scalars().all():
            delivery.status = "failed"
            delivery.status_updated_at = failure_time
            delivery.updated_at = failure_time
            delivery.error_message = "The WhatsApp worker queue is temporarily unavailable"
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The WhatsApp worker queue is temporarily unavailable",
        ) from exc

    attempted_count = (
        len(requested_ids) if payload.document_ids is not None else len(preview.recipients)
    )
    return SendDocumentBroadcastResponse(
        send_batch_id=send_batch_id,
        queued_count=queued_count,
        skipped_count=max(0, attempted_count - queued_count),
        message=(
            f"Queued {queued_count} document{'' if queued_count == 1 else 's'} "
            "for individual WhatsApp delivery."
        ),
    )


@router.get(
    "/groups/{group_id}/whatsapp-deliveries/tracking",
    response_model=DocumentDeliveryTrackingResponse,
)
async def get_document_delivery_tracking(
    group_id: uuid.UUID,
    limit: Annotated[int, Query(ge=0, le=100)] = 100,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> DocumentDeliveryTrackingResponse:
    group = await _get_authorized_group(
        group_id,
        current_user=current_user,
        session=session,
    )
    count_result = await session.execute(
        select(
            DocumentWhatsAppDeliveryModel.status,
            func.count(DocumentWhatsAppDeliveryModel.id),
            func.max(DocumentWhatsAppDeliveryModel.status_updated_at),
        )
        .where(
            DocumentWhatsAppDeliveryModel.group_id == group.id,
            DocumentWhatsAppDeliveryModel.agency_id == group.agency_id,
        )
        .group_by(DocumentWhatsAppDeliveryModel.status)
    )
    count_rows = count_result.all()
    status_counts = {
        delivery_status: int(count)
        for delivery_status, count, _latest_update in count_rows
    }
    latest_status_updates = {
        delivery_status: latest_update
        for delivery_status, _count, latest_update in count_rows
        if latest_update is not None
    }
    deliveries: list[DocumentWhatsAppDeliveryModel] = []
    if limit:
        result = await session.execute(
            select(DocumentWhatsAppDeliveryModel)
            .where(
                DocumentWhatsAppDeliveryModel.group_id == group.id,
                DocumentWhatsAppDeliveryModel.agency_id == group.agency_id,
            )
            .order_by(DocumentWhatsAppDeliveryModel.status_updated_at.desc())
            .limit(limit)
        )
        deliveries = list(result.scalars().all())
    counts = DocumentDeliveryTrackingCounts(
        total=sum(status_counts.values()),
        queued=status_counts.get("queued", 0) + status_counts.get("processing", 0),
        sent=status_counts.get("submitted", 0) + status_counts.get("sent", 0),
        delivered=status_counts.get("delivered", 0),
        read=status_counts.get("read", 0),
        failed=status_counts.get("failed", 0),
        delivery_unknown=status_counts.get("delivery_unknown", 0),
    )
    return DocumentDeliveryTrackingResponse(
        group_id=group.id,
        counts=counts,
        poll_after_seconds=_document_delivery_poll_after_seconds(
            status_counts=status_counts,
            latest_status_updates=latest_status_updates,
            now=datetime.now(tz=UTC),
        ),
        deliveries=[
            DocumentDeliveryTrackingRow(
                delivery_id=delivery.id,
                passenger_id=delivery.passenger_id,
                passenger_name=delivery.passenger_name,
                passport_number=delivery.passport_number,
                document_type=delivery.document_type,
                document_filename=delivery.document_filename,
                phone_number=delivery.phone_number,
                status=delivery.status,
                error_message=delivery.error_message,
                status_updated_at=delivery.status_updated_at,
            )
            for delivery in deliveries
        ],
    )
