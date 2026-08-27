"""WhatsApp broadcast management routes."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from io import BytesIO
from itertools import islice
from typing import Any, Literal
from zipfile import BadZipFile

import httpx
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import PlainTextResponse
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.passenger_change_propagation import (
    propagate_mobile_passenger_change,
    reconcile_mobile_passenger_access_for_broadcast,
    reconcile_mobile_passenger_access_for_group,
)
from app.application.use_cases.whatsapp.message_templates import (
    WhatsAppMessageType,
)
from app.application.use_cases.whatsapp.recipient_capacity import (
    MAX_WHATSAPP_RECIPIENTS,
    WhatsAppRecipientCapacityExceeded,
    require_whatsapp_recipient_capacity,
)
from app.core.config.settings import get_settings
from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import ImageValidationError
from app.infrastructure.database.gc_mobile_models import MobileOTPChallengeModel
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    DocumentWhatsAppDeliveryModel,
    PassengerQrWhatsAppDeliveryModel,
    PassportRosterResolutionModel,
    PassportSubmissionModel,
    UserModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastRejectedContactModel,
    WhatsAppBroadcastSupportContactModel,
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.passport_roster_resolution_repository import (
    active_replacement_resolution_id_for_recipient,
    suppress_active_replacement_recipients,
)
from app.infrastructure.repositories.passport_whatsapp_matching_repository import (
    load_unresolved_passport_whatsapp_match_context,
)
from app.infrastructure.repositories.whatsapp_recipient_capacity_repository import (
    require_locked_broadcast_recipient_capacity,
)
from app.infrastructure.security.upload_security import (
    UploadSecurityContext,
    UploadSecurityEvidenceError,
    UploadSecurityService,
)
from app.infrastructure.security.upload_validator import MalwareScannerUnavailableError
from app.infrastructure.whatsapp.cloud_api_provider import (
    WhatsAppCloudApiError,
    upload_whatsapp_image,
)
from app.infrastructure.whatsapp.document_delivery_runtime import (
    ACCEPTED_STATUSES as DOCUMENT_DELIVERY_ACCEPTED_STATUSES,
)
from app.infrastructure.whatsapp.document_delivery_runtime import (
    apply_document_provider_status,
)
from app.infrastructure.whatsapp.private_delivery_policy import (
    PrivateDeliveryMutationBlocked,
    prepare_private_delivery_identity_mutation,
)
from app.infrastructure.whatsapp.qr_delivery_runtime import (
    apply_qr_provider_status,
)
from app.presentation.api.v1.routes import (
    whatsapp_composer_support as _composer_support,
)
from app.presentation.api.v1.routes import (
    whatsapp_contact_support as _contact_support,
)
from app.presentation.api.v1.routes import (
    whatsapp_delivery_support as _delivery_support,
)
from app.presentation.api.v1.routes import (
    whatsapp_roster_support as _roster_support,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (  # noqa: F401
    WhatsAppBatchSummaryResponse,
    WhatsAppBroadcastGroupDetailResponse,
    WhatsAppBroadcastGroupResponse,
    WhatsAppContactPreviewRecipient,
    WhatsAppContactPreviewRejectedRow,
    WhatsAppContactPreviewResponse,
    WhatsAppContactRejectionCode,
    WhatsAppPreviewRequest,
    WhatsAppPreviewResponse,
    WhatsAppRecipientInput,
    WhatsAppRecipientMessageStatusResponse,
    WhatsAppRecipientPhoneUpdateRequest,
    WhatsAppRecipientResponse,
    WhatsAppRecipientRosterCountsResponse,
    WhatsAppRecipientRosterItemResponse,
    WhatsAppRecipientRosterResponse,
    WhatsAppRejectedContactInput,
    WhatsAppRejectedContactListResponse,
    WhatsAppRejectedContactResolveRequest,
    WhatsAppRejectedContactResponse,
    WhatsAppReplacedRecipientResponse,
    WhatsAppResendRequest,
    WhatsAppSendRequest,
    WhatsAppSendResponse,
    WhatsAppSendResult,
    WhatsAppSupportContactInput,
    WhatsAppSupportContactResponse,
    WhatsAppUnidentifiedUploadResponse,
    WhatsAppWebhookAck,
    WhatsAppWelcomeMediaResponse,
)
from app.presentation.dependencies.auth import (
    WHATSAPP_BROADCAST_ROLES,
    require_role,
)
from app.presentation.dependencies.csrf import require_cookie_csrf
from app.presentation.security.client_ip import trusted_client_ip

router = APIRouter()
logger = logging.getLogger(__name__)

WHATSAPP_ROLES = [*WHATSAPP_BROADCAST_ROLES]
PHONE_RE = _contact_support.PHONE_RE
WHATSAPP_ACCEPTED_STATUSES = _delivery_support.WHATSAPP_ACCEPTED_STATUSES
WHATSAPP_ACCEPTED_STATUS_RANK = _delivery_support.WHATSAPP_ACCEPTED_STATUS_RANK
WHATSAPP_WEBHOOK_STATUSES = _delivery_support.WHATSAPP_WEBHOOK_STATUSES
WHATSAPP_IN_PROGRESS_STATUSES = _delivery_support.WHATSAPP_IN_PROGRESS_STATUSES
WHATSAPP_UNCERTAIN_STATUSES = _delivery_support.WHATSAPP_UNCERTAIN_STATUSES
WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES = (
    _delivery_support.WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES
)
WHATSAPP_SUPPRESSED_STATUSES = _delivery_support.WHATSAPP_SUPPRESSED_STATUSES
WHATSAPP_STALE_CLAIM_AGE = _delivery_support.WHATSAPP_STALE_CLAIM_AGE
MAX_WHATSAPP_CONTACT_FILE_BYTES = 5 * 1024 * 1024
MAX_WHATSAPP_WELCOME_IMAGE_BYTES = 5 * 1024 * 1024
MAX_WHATSAPP_EXCEL_UNCOMPRESSED_BYTES = (
    _contact_support.MAX_WHATSAPP_EXCEL_UNCOMPRESSED_BYTES
)
MAX_WHATSAPP_EXCEL_ARCHIVE_MEMBERS = _contact_support.MAX_WHATSAPP_EXCEL_ARCHIVE_MEMBERS
MAX_WHATSAPP_EXCEL_COMPRESSION_RATIO = _contact_support.MAX_WHATSAPP_EXCEL_COMPRESSION_RATIO
MAX_WHATSAPP_EXCEL_HEADER_SCAN_ROWS = _contact_support.MAX_WHATSAPP_EXCEL_HEADER_SCAN_ROWS
MAX_WHATSAPP_EXCEL_SHEETS = 50
MAX_WHATSAPP_EXCEL_ROWS = 2_000
MAX_WHATSAPP_REJECTED_ROWS = 500
MAX_WHATSAPP_REJECTED_CONTACTS_PER_GROUP = (
    _contact_support.MAX_WHATSAPP_REJECTED_CONTACTS_PER_GROUP
)
MAX_WHATSAPP_IMPORTED_FIELDS = _contact_support.MAX_WHATSAPP_IMPORTED_FIELDS
MAX_WHATSAPP_IMPORTED_FIELD_KEY_LENGTH = (
    _contact_support.MAX_WHATSAPP_IMPORTED_FIELD_KEY_LENGTH
)
MAX_WHATSAPP_IMPORTED_FIELD_VALUE_LENGTH = (
    _contact_support.MAX_WHATSAPP_IMPORTED_FIELD_VALUE_LENGTH
)
MAX_WHATSAPP_IMPORTED_FIELDS_BYTES = _contact_support.MAX_WHATSAPP_IMPORTED_FIELDS_BYTES
WHATSAPP_UPLOAD_READ_CHUNK_BYTES = _contact_support.WHATSAPP_UPLOAD_READ_CHUNK_BYTES
WHATSAPP_ROSTER_SOURCE_FIELDS = _contact_support.WHATSAPP_ROSTER_SOURCE_FIELDS

_WhatsAppExcelContactParseResult = _contact_support._WhatsAppExcelContactParseResult
_WhatsAppComposerSnapshot = _composer_support._WhatsAppComposerSnapshot

_iter_webhook_values = _delivery_support._iter_webhook_values
_extract_status_error = _delivery_support._extract_status_error
_parse_provider_status_at = _delivery_support._parse_provider_status_at
_is_stale_provider_status = _delivery_support._is_stale_provider_status
_apply_provider_status_to_delivery_state = (
    _delivery_support._apply_provider_status_to_delivery_state
)
_apply_provider_status_to_message_log = _delivery_support._apply_provider_status_to_message_log
_provider_status_state_predicates = _delivery_support._provider_status_state_predicates
_agency_filter = _delivery_support._agency_filter
_broadcast_batch_summary_statement = _delivery_support._broadcast_batch_summary_statement

_normalize_phone = _contact_support._normalize_phone
_clean_name = _contact_support._clean_name
_clean_required_name = _contact_support._clean_required_name
_validate_excel_archive = _contact_support._validate_excel_archive
_excel_cell_text = _contact_support._excel_cell_text
_excel_header_label = _contact_support._excel_header_label
_EXCEL_FIELD_ALIASES = _contact_support._EXCEL_FIELD_ALIASES
_EMPTY_EXCEL_VALUES = _contact_support._EMPTY_EXCEL_VALUES
_excel_field_key = _contact_support._excel_field_key
_safe_imported_fields = _contact_support._safe_imported_fields
_is_excel_phone_header = _contact_support._is_excel_phone_header
_is_excel_name_header = _contact_support._is_excel_name_header
_excel_header_columns = _contact_support._excel_header_columns
_find_excel_contact_header = _contact_support._find_excel_contact_header
_excel_name_from_row = _contact_support._excel_name_from_row
_excel_raw_name_from_row = _contact_support._excel_raw_name_from_row
_bounded_excel_raw_value = _contact_support._bounded_excel_raw_value
_is_repeated_excel_header = _contact_support._is_repeated_excel_header
_row_has_contact_identity = _contact_support._row_has_contact_identity
_WHATSAPP_CONTACT_REJECTION_REASONS = (
    _contact_support._WHATSAPP_CONTACT_REJECTION_REASONS
)
_excel_fields_from_row = _contact_support._excel_fields_from_row
_merge_recipient_inputs = _contact_support._merge_recipient_inputs
_excel_contact_preview_response = _contact_support._excel_contact_preview_response
_parse_manual_contacts = _contact_support._parse_manual_contacts
_rejected_contact_fingerprint = _contact_support._rejected_contact_fingerprint
_parse_rejected_contacts = _contact_support._parse_rejected_contacts
_positive_int = _contact_support._positive_int
_roster_source_sort_key = _contact_support._roster_source_sort_key
_new_roster_display_orders = _contact_support._new_roster_display_orders
_next_roster_display_order = _contact_support._next_roster_display_order
_add_rejected_contact_models = _contact_support._add_rejected_contact_models
_normalized_recipient_inputs = _contact_support._normalized_recipient_inputs
_activate_recipient_models = _contact_support._activate_recipient_models
_parse_support_contacts = _contact_support._parse_support_contacts
_recipient_response = _contact_support._recipient_response
_rejected_contact_response = _contact_support._rejected_contact_response
_support_contact_response = _contact_support._support_contact_response

_support_contacts_for_group = _roster_support._support_contacts_for_group
_recipient_delivery_state_maps = _roster_support._recipient_delivery_state_maps
_group_detail = _roster_support._group_detail
_group_recipients = _roster_support._group_recipients
_select_group_recipients = _roster_support._select_group_recipients
_select_support_contacts = _roster_support._select_support_contacts
_recipient_delivery_counts = _roster_support._recipient_delivery_counts

_as_message_type = _composer_support._as_message_type
_resolve_message_content = _composer_support._resolve_message_content
_resolve_send_message_content = _composer_support._resolve_send_message_content
_resolve_passport_intro = _composer_support._resolve_passport_intro
_resolve_send_passport_intro = _composer_support._resolve_send_passport_intro
_resolve_send_header_image = _composer_support._resolve_send_header_image
_validate_passport_link = _composer_support._validate_passport_link
_message_values = _composer_support._message_values
_split_rendered_support_block = _composer_support._split_rendered_support_block
_decode_legacy_template_snapshot = _composer_support._decode_legacy_template_snapshot
_template_snapshot_from_log = _composer_support._template_snapshot_from_log
_composer_snapshot_from_log = _composer_support._composer_snapshot_from_log
_latest_composer_snapshot = _composer_support._latest_composer_snapshot
_merge_composer_snapshot = _composer_support._merge_composer_snapshot


def _verify_meta_signature(raw_body: bytes, signature_header: str | None) -> bool:
    settings = get_settings()
    app_secret = (settings.whatsapp_app_secret or "").strip()
    if not app_secret:
        return getattr(settings, "app_env", "development") == "development"
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    received_signature = signature_header.removeprefix("sha256=").strip()
    expected_signature = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(received_signature, expected_signature)


@router.get("/webhook", response_class=PlainTextResponse)
async def verify_whatsapp_webhook(
    mode: str | None = Query(default=None, alias="hub.mode"),
    verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> PlainTextResponse:
    settings = get_settings()
    expected_token = (settings.whatsapp_webhook_verify_token or "").strip()
    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp webhook verify token is not configured",
        )
    if (
        mode == "subscribe"
        and challenge
        and hmac.compare_digest(verify_token or "", expected_token)
    ):
        return PlainTextResponse(challenge, status_code=status.HTTP_200_OK)
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="WhatsApp webhook verification failed"
    )


@router.post("/webhook", response_model=WhatsAppWebhookAck)
async def receive_whatsapp_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppWebhookAck:
    raw_body = await request.body()
    if not _verify_meta_signature(raw_body, x_hub_signature_256):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid WhatsApp webhook signature"
        )
    try:
        payload = json.loads(raw_body.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid WhatsApp webhook JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid WhatsApp webhook payload"
        )

    provider_statuses: list[tuple[str, str, str | None, datetime | None]] = []
    received_messages = 0
    for value in _iter_webhook_values(payload):
        for status_payload in (
            value.get("statuses", []) if isinstance(value.get("statuses"), list) else []
        ):
            if not isinstance(status_payload, dict):
                continue
            provider_id = status_payload.get("id")
            provider_status = status_payload.get("status")
            if provider_id and provider_status:
                normalized_status = str(provider_status)[:32]
                if normalized_status not in WHATSAPP_WEBHOOK_STATUSES:
                    logger.warning(
                        "Ignoring unknown WhatsApp provider status %s",
                        normalized_status,
                    )
                    continue
                provider_statuses.append(
                    (
                        str(provider_id),
                        normalized_status,
                        _extract_status_error(status_payload),
                        _parse_provider_status_at(status_payload.get("timestamp")),
                    )
                )
        messages = value.get("messages")
        if isinstance(messages, list):
            received_messages += len(messages)

    processed_statuses = 0
    released_document_changes: dict[
        tuple[uuid.UUID, uuid.UUID], tuple[set[uuid.UUID], set[str]]
    ] = {}
    provider_statuses.sort(key=lambda item: item[3] or datetime.min.replace(tzinfo=UTC))
    for (
        provider_id,
        provider_status,
        error_message,
        provider_status_at,
    ) in provider_statuses:
        processed_before = processed_statuses
        result = await session.execute(
            select(WhatsAppMessageLogModel).where(
                WhatsAppMessageLogModel.provider_message_id == provider_id
            )
        )
        message_logs = list(result.scalars().all())
        for log in message_logs:
            now = datetime.now(tz=UTC)
            _apply_provider_status_to_message_log(
                log,
                provider_status=provider_status,
                error_message=error_message,
                provider_status_at=provider_status_at,
                now=now,
            )
            if not getattr(log, "is_explicit_resend", False):
                state_result = await session.execute(
                    select(WhatsAppRecipientMessageStateModel)
                    .where(
                        *_provider_status_state_predicates(
                            log,
                            provider_status=provider_status,
                        )
                    )
                    .with_for_update()
                )
                delivery_state = state_result.scalar_one_or_none()
                if delivery_state:
                    _apply_provider_status_to_delivery_state(
                        delivery_state,
                        provider_status=provider_status,
                        provider_status_at=provider_status_at,
                        now=now,
                    )
            processed_statuses += 1
        if not message_logs:
            document_result = await session.execute(
                select(DocumentWhatsAppDeliveryModel).where(
                    DocumentWhatsAppDeliveryModel.provider_message_id == provider_id
                ).with_for_update()
            )
            document_deliveries = document_result.scalars().all()
            for delivery in document_deliveries:
                if not isinstance(delivery, DocumentWhatsAppDeliveryModel):
                    continue
                was_released = delivery.status in DOCUMENT_DELIVERY_ACCEPTED_STATUSES
                apply_document_provider_status(
                    delivery,
                    provider_status=provider_status,
                    error_message=error_message,
                    provider_status_at=provider_status_at,
                    now=datetime.now(tz=UTC),
                )
                if (
                    not was_released
                    and delivery.status in DOCUMENT_DELIVERY_ACCEPTED_STATUSES
                    and delivery.passenger_id is not None
                ):
                    passenger_ids, provider_ids = released_document_changes.setdefault(
                        (delivery.agency_id, delivery.group_id), (set(), set())
                    )
                    passenger_ids.add(delivery.passenger_id)
                    provider_ids.add(provider_id)
                processed_statuses += 1
            if not document_deliveries:
                qr_result = await session.execute(
                    select(PassengerQrWhatsAppDeliveryModel).where(
                        PassengerQrWhatsAppDeliveryModel.provider_message_id == provider_id
                    )
                )
                for qr_delivery in qr_result.scalars().all():
                    if not isinstance(qr_delivery, PassengerQrWhatsAppDeliveryModel):
                        continue
                    apply_qr_provider_status(
                        qr_delivery,
                        provider_status=provider_status,
                        error_message=error_message,
                        provider_status_at=provider_status_at,
                        now=datetime.now(tz=UTC),
                    )
                    processed_statuses += 1
        if processed_statuses == processed_before:
            otp_result = await session.execute(
                select(MobileOTPChallengeModel).where(
                    MobileOTPChallengeModel.provider_reference == provider_id
                )
            )
            challenge = otp_result.scalar_one_or_none()
            if challenge is not None:
                now = datetime.now(tz=UTC)
                if provider_status == "failed" and challenge.status == "pending":
                    challenge.status = "cancelled"
                challenge.updated_at = now
                await AuditLogRepository(session).record(
                    action="mobile.otp_delivery_status",
                    entity_type="mobile_otp_challenge",
                    agency_id=challenge.agency_id,
                    entity_id=str(challenge.id),
                    metadata={
                        "provider": challenge.provider,
                        "delivery_status": provider_status,
                        "provider_error": error_message,
                    },
                )
                if provider_status == "failed":
                    logger.warning(
                        "mobile_otp_provider_delivery_failed",
                        extra={"provider_error": error_message},
                    )
                processed_statuses += 1
    for (agency_id, group_id), (
        passenger_ids,
        provider_ids,
    ) in sorted(
        released_document_changes.items(),
        key=lambda item: (str(item[0][0]), str(item[0][1])),
    ):
        receipt_digest = hashlib.sha256(
            "|".join(sorted(provider_ids)).encode("utf-8")
        ).hexdigest()
        await propagate_mobile_passenger_change(
            session,
            agency_id=agency_id,
            group_id=group_id,
            passenger_submission_ids=passenger_ids,
            actor_user_id=None,
            change_kind="documents",
            reconcile_identities=False,
            propagation_key=f"document-delivery-receipt:{receipt_digest}",
        )
    if processed_statuses:
        await session.commit()

    if received_messages:
        logger.info("Received %s WhatsApp inbound message webhook event(s)", received_messages)
    return WhatsAppWebhookAck(
        processed_statuses=processed_statuses, received_messages=received_messages
    )


async def _prepare_private_recipient_mutation(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    broadcast_group_id: uuid.UUID,
    recipient_id: uuid.UUID | None = None,
    cancellation_reason: str,
) -> None:
    """Cancel queued private sends and block indeterminate provider states."""

    try:
        await prepare_private_delivery_identity_mutation(
            session,
            agency_id=agency_id,
            broadcast_group_ids={broadcast_group_id},
            recipient_ids={recipient_id} if recipient_id else None,
            cancel_queued=True,
            cancellation_reason=cancellation_reason,
        )
    except PrivateDeliveryMutationBlocked as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


async def _lock_active_whatsapp_actor(
    session: AsyncSession,
    *,
    current_user: User,
    require_agency: bool,
) -> UserModel:
    """Re-authorize the actor after untrusted workbook parsing.

    Authentication and role dependencies read the user before the route starts,
    which opens a database transaction. Workbook bytes must be read and parsed
    only after that transaction is released. The write transaction therefore
    re-fetches and locks the actor (and their agency when agency scope is
    required) so deactivation, role changes, reassignment, or agency suspension
    during parsing fail closed before any roster mutation.
    """

    expected_agency_id = current_user.agency_id
    expected_role = current_user.role.value
    predicates = [
        UserModel.id == current_user.id,
        UserModel.role == expected_role,
        UserModel.is_active.is_(True),
        UserModel.deleted_at.is_(None),
    ]
    statement = select(UserModel).where(*predicates)
    if require_agency:
        if expected_agency_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account is no longer authorized for WhatsApp broadcasts.",
            )
        statement = (
            select(UserModel)
            .join(AgencyModel, AgencyModel.id == UserModel.agency_id)
            .where(
                *predicates,
                UserModel.agency_id == expected_agency_id,
                AgencyModel.is_active.is_(True),
            )
            .with_for_update()
        )
    else:
        statement = statement.with_for_update(of=UserModel)

    result = await session.execute(statement.execution_options(populate_existing=True))
    actor = result.scalar_one_or_none()
    if actor is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is no longer authorized for WhatsApp broadcasts.",
        )
    return actor


async def _release_auth_transaction(
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """End the read-only authentication transaction before CPU/file work."""

    await session.rollback()


def _configured_template_name(message_type: WhatsAppMessageType) -> str:
    settings = get_settings()
    if message_type == "welcome":
        return settings.whatsapp_welcome_template_name
    if message_type == "reminder":
        return settings.whatsapp_reminder_template_name
    return settings.whatsapp_passport_link_template_name


def _append_excel_contact_rejection(
    rejected_rows: list[WhatsAppContactPreviewRejectedRow],
    rejected_counts: dict[WhatsAppContactRejectionCode, int],
    *,
    sheet_name: str,
    row_number: int,
    raw_name: str | None,
    raw_phone_number: str | None,
    imported_fields: dict[str, str],
    reason_code: WhatsAppContactRejectionCode,
) -> None:
    rejected_counts[reason_code] = rejected_counts.get(reason_code, 0) + 1
    if len(rejected_rows) >= MAX_WHATSAPP_REJECTED_ROWS:
        return
    rejected_rows.append(
        WhatsAppContactPreviewRejectedRow(
            sheet_name=sheet_name,
            row_number=row_number,
            raw_name=raw_name,
            raw_phone_number=raw_phone_number,
            imported_fields=_safe_imported_fields(imported_fields),
            reason_code=reason_code,
            reason=_WHATSAPP_CONTACT_REJECTION_REASONS[reason_code],
        )
    )


def _parse_excel_contact_bytes(
    payload: bytes,
    *,
    filename: str,
) -> _WhatsAppExcelContactParseResult:
    source_file_name = (
        filename.replace("\\", "/").rsplit("/", maxsplit=1)[-1].strip() or "contacts.xlsx"
    )
    suffix = source_file_name.rsplit(".", maxsplit=1)[-1].lower()
    suffix = f".{suffix}" if "." in filename else ".xlsx"
    if suffix not in {".xlsx", ".xlsm"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload an .xlsx or .xlsm contact file",
        )

    workbook = None
    try:
        _validate_excel_archive(payload)
        workbook = load_workbook(
            BytesIO(payload),
            read_only=True,
            data_only=True,
        )
        worksheets = workbook.worksheets
        if len(worksheets) > MAX_WHATSAPP_EXCEL_SHEETS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "The Excel contact file contains too many worksheets; "
                    f"use at most {MAX_WHATSAPP_EXCEL_SHEETS}"
                ),
            )
        sheet_rows: list[tuple[str, list[tuple[Any, ...]]]] = []
        total_rows = 0
        for sheet in worksheets:
            remaining_rows = MAX_WHATSAPP_EXCEL_ROWS - total_rows
            rows = list(
                islice(
                    sheet.iter_rows(values_only=True),
                    remaining_rows + 1,
                )
            )
            total_rows += len(rows)
            if total_rows > MAX_WHATSAPP_EXCEL_ROWS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "The Excel contact file can contain at most "
                        f"{MAX_WHATSAPP_EXCEL_ROWS} rows across all worksheets"
                    ),
                )
            sheet_rows.append((sheet.title, rows))
    except HTTPException:
        raise
    except (BadZipFile, InvalidFileException, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded Excel contact file could not be read",
        ) from exc
    except Exception as exc:
        logger.error(
            "whatsapp_excel_contact_file_read_failed",
            extra={"error_type": type(exc).__name__},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded Excel contact file could not be read",
        ) from exc
    finally:
        if workbook is not None:
            workbook.close()

    if not any(rows for _, rows in sheet_rows):
        return _WhatsAppExcelContactParseResult(
            contacts=[],
            rejected_rows=[],
            rejected_counts={},
        )

    contacts_by_phone: dict[str, WhatsAppRecipientInput] = {}
    rejected_rows: list[WhatsAppContactPreviewRejectedRow] = []
    rejected_counts: dict[WhatsAppContactRejectionCode, int] = {}
    source_order = 0
    for sheet_index, (sheet_name, rows) in enumerate(sheet_rows):
        if not rows:
            continue
        header_match = _find_excel_contact_header(rows)
        if header_match:
            (
                header_row_index,
                phone_columns,
                name_columns,
                given_name_columns,
                surname_columns,
            ) = header_match
            header_row = rows[header_row_index]
            data_rows = rows[header_row_index + 1 :]
            first_data_row_number = header_row_index + 2
        elif sheet_index == 0:
            header_row = ()
            phone_columns = []
            name_columns = []
            given_name_columns = []
            surname_columns = []
            data_rows = rows
            first_data_row_number = 1
        else:
            # A multi-sheet workbook often contains notes or lookup sheets.
            # Never scan those heuristically for phone-like numbers.
            continue

        for row_number, row in enumerate(
            data_rows,
            start=first_data_row_number,
        ):
            row_values = list(row)
            if header_row and _is_repeated_excel_header(row_values, header_row):
                continue
            source_order += 1
            candidates: list[tuple[str | None, str, dict[str, str]]] = []
            imported_fields = (
                _excel_fields_from_row(
                    header_row=header_row,
                    row_values=row_values,
                    sheet_name=sheet_name,
                    source_file_name=source_file_name,
                    row_number=row_number,
                    source_order=source_order,
                )
                if header_row
                else _safe_imported_fields(
                    {
                        "source_file": source_file_name,
                        "source_order": str(source_order),
                        "source_sheet": sheet_name,
                        "source_row": str(row_number),
                    }
                )
            )
            name = _excel_name_from_row(
                row_values,
                name_columns=name_columns,
                given_name_columns=given_name_columns,
                surname_columns=surname_columns,
                phone_columns=phone_columns,
            )
            raw_name = _excel_raw_name_from_row(
                row_values,
                name_columns=name_columns,
                given_name_columns=given_name_columns,
                surname_columns=surname_columns,
                phone_columns=phone_columns,
            )
            if phone_columns:
                phone_values: list[str] = []
                for index in phone_columns:
                    if index >= len(row_values):
                        continue
                    phone = _bounded_excel_raw_value(
                        row_values[index],
                        max_length=64,
                    )
                    if phone:
                        phone_values.append(phone)
                if not phone_values:
                    if _row_has_contact_identity(
                        name=name,
                        imported_fields=imported_fields,
                    ):
                        _append_excel_contact_rejection(
                            rejected_rows,
                            rejected_counts,
                            sheet_name=sheet_name,
                            row_number=row_number,
                            raw_name=raw_name,
                            raw_phone_number=None,
                            imported_fields=imported_fields,
                            reason_code="missing_phone",
                        )
                    continue
                candidates.extend((name, phone, imported_fields) for phone in phone_values)
            else:
                row_text = " ".join(text for cell in row_values if (text := _excel_cell_text(cell)))
                for match in PHONE_RE.findall(row_text):
                    candidates.append((name, match, imported_fields))

            for name, phone, fields in candidates:
                normalized = _normalize_phone(phone)
                if not normalized:
                    _append_excel_contact_rejection(
                        rejected_rows,
                        rejected_counts,
                        sheet_name=sheet_name,
                        row_number=row_number,
                        raw_name=raw_name,
                        raw_phone_number=phone,
                        imported_fields=fields,
                        reason_code="invalid_phone",
                    )
                    continue
                incoming = WhatsAppRecipientInput(
                    name=name,
                    phone_number=phone,
                    imported_fields=fields,
                )
                existing = contacts_by_phone.get(normalized)
                if not name:
                    if existing:
                        contacts_by_phone[normalized] = _merge_recipient_inputs(
                            existing,
                            incoming,
                        )
                    _append_excel_contact_rejection(
                        rejected_rows,
                        rejected_counts,
                        sheet_name=sheet_name,
                        row_number=row_number,
                        raw_name=raw_name,
                        raw_phone_number=phone,
                        imported_fields=fields,
                        reason_code="missing_name",
                    )
                    continue
                if existing:
                    contacts_by_phone[normalized] = _merge_recipient_inputs(
                        existing,
                        incoming,
                    )
                    _append_excel_contact_rejection(
                        rejected_rows,
                        rejected_counts,
                        sheet_name=sheet_name,
                        row_number=row_number,
                        raw_name=raw_name,
                        raw_phone_number=phone,
                        imported_fields=fields,
                        reason_code="duplicate_phone",
                    )
                    continue
                contacts_by_phone[normalized] = incoming
                try:
                    require_whatsapp_recipient_capacity(
                        active_count=0,
                        activating_count=len(contacts_by_phone),
                    )
                except WhatsAppRecipientCapacityExceeded as exc:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            "The Excel contact file can contain at most "
                            f"{MAX_WHATSAPP_RECIPIENTS} recipients"
                        ),
                    ) from exc
    return _WhatsAppExcelContactParseResult(
        contacts=list(contacts_by_phone.values()),
        rejected_rows=rejected_rows,
        rejected_counts=rejected_counts,
    )


async def _parse_excel_contact_preview(
    upload: UploadFile,
) -> _WhatsAppExcelContactParseResult:
    payload = bytearray()
    while chunk := await upload.read(WHATSAPP_UPLOAD_READ_CHUNK_BYTES):
        payload.extend(chunk)
        if len(payload) > MAX_WHATSAPP_CONTACT_FILE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=(
                    "The Excel contact file must be "
                    f"{MAX_WHATSAPP_CONTACT_FILE_BYTES // (1024 * 1024)} MB or smaller"
                ),
            )
    filename = upload.filename or "contacts.xlsx"
    return await asyncio.to_thread(
        _parse_excel_contact_bytes,
        bytes(payload),
        filename=filename,
    )


async def _parse_excel_contacts(
    upload: UploadFile,
) -> list[WhatsAppRecipientInput]:
    result = await _parse_excel_contact_preview(upload)
    blocking_rejection_count = sum(
        count
        for reason_code, count in result.rejected_counts.items()
        if reason_code != "duplicate_phone"
    )
    if blocking_rejection_count:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"The Excel contact file contains {blocking_rejection_count} "
                "invalid contact row(s). Preview the file, correct the rejected "
                "rows, and upload it again."
            ),
        )
    return result.contacts


@router.post(
    "/contacts/preview",
    response_model=WhatsAppContactPreviewResponse,
)
async def preview_excel_contacts(
    contacts_file: UploadFile = File(...),
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    _auth_transaction_released: None = Depends(_release_auth_transaction),
) -> WhatsAppContactPreviewResponse:
    del current_user, _auth_transaction_released
    result = await _parse_excel_contact_preview(contacts_file)
    return _excel_contact_preview_response(
        result.contacts,
        result.rejected_rows,
        rejected_count=result.rejected_count,
    )


@router.get("/groups", response_model=list[WhatsAppBroadcastGroupResponse])
async def list_broadcast_groups(
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[WhatsAppBroadcastGroupResponse]:
    rejected_contact_count = (
        select(func.count(WhatsAppBroadcastRejectedContactModel.id))
        .where(
            WhatsAppBroadcastRejectedContactModel.broadcast_group_id
            == WhatsAppBroadcastGroupModel.id,
        )
        .correlate(WhatsAppBroadcastGroupModel)
        .scalar_subquery()
    )
    result = await session.execute(
        select(
            WhatsAppBroadcastGroupModel,
            func.count(WhatsAppBroadcastRecipientModel.id).label("recipient_count"),
            rejected_contact_count.label("rejected_contact_count"),
        )
        .outerjoin(
            WhatsAppBroadcastRecipientModel,
            and_(
                WhatsAppBroadcastRecipientModel.broadcast_group_id
                == WhatsAppBroadcastGroupModel.id,
                WhatsAppBroadcastRecipientModel.removed_at.is_(None),
            ),
        )
        .where(*_agency_filter(current_user))
        .group_by(WhatsAppBroadcastGroupModel.id)
        .order_by(WhatsAppBroadcastGroupModel.created_at.desc())
    )
    return [
        WhatsAppBroadcastGroupResponse(
            id=group.id,
            name=group.name,
            organizing_company_name=group.organizing_company_name,
            recipient_count=int(recipient_count or 0),
            total_contact_count=(int(recipient_count or 0) + int(rejected_count or 0)),
            recipient_opt_in_confirmed=group.recipient_opt_in_confirmed_at is not None,
            created_at=group.created_at,
            updated_at=group.updated_at,
        )
        for group, recipient_count, rejected_count in result.all()
    ]


@router.get("/groups/{group_id}", response_model=WhatsAppBroadcastGroupDetailResponse)
async def get_broadcast_group(
    group_id: uuid.UUID,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppBroadcastGroupDetailResponse:
    result = await session.execute(
        select(WhatsAppBroadcastGroupModel).where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="WhatsApp broadcast group not found"
        )
    return await _group_detail(session, group)


def _unidentified_submission_details(
    submission: PassportSubmissionModel,
) -> dict[str, Any]:
    details: dict[str, Any] = {
        "family_head_name": submission.family_head_name,
        "family_head_phone": submission.family_head_phone,
        "family_head_email": submission.family_head_email,
        "family_relation": submission.family_relation,
        "family_gender": submission.family_gender,
        "departure_city": submission.departure_city,
        "nearest_domestic_airport": submission.nearest_domestic_airport,
    }
    for fields in (
        submission.staff_metadata,
        submission.extracted_fields,
        submission.confirmed_fields,
    ):
        details.update(dict(fields or {}))
    return {str(key): value for key, value in details.items() if value is not None and value != ""}


async def _unidentified_uploads_for_broadcast(
    session: AsyncSession,
    *,
    broadcast_group_id: uuid.UUID,
    agency_id: uuid.UUID,
) -> list[WhatsAppUnidentifiedUploadResponse]:
    linked_group_result = await session.execute(
        select(ClientGroupModel)
        .join(
            ClientGroupWhatsAppBroadcastLinkModel,
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == ClientGroupModel.id,
        )
        .where(
            ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id == broadcast_group_id,
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == agency_id,
            ClientGroupModel.agency_id == agency_id,
            ClientGroupModel.deleted_at.is_(None),
        )
        .order_by(ClientGroupModel.name.asc(), ClientGroupModel.id.asc())
    )
    linked_client_groups = list(linked_group_result.scalars().all())
    unidentified: list[WhatsAppUnidentifiedUploadResponse] = []
    seen_submission_ids: set[uuid.UUID] = set()

    for client_group in linked_client_groups:
        (
            _linked_broadcasts,
            _recipients,
            submissions,
            rows,
        ) = await load_unresolved_passport_whatsapp_match_context(
            session,
            group_id=client_group.id,
            agency_id=agency_id,
            broadcast_group_ids=[broadcast_group_id],
        )
        submission_by_id = {submission.id: submission for submission in submissions}
        unmatched_submission_ids = {
            submission_id
            for row in rows
            if row.status == "unmatched_submission"
            for submission_id in row.submission_ids
        }
        for submission_id in unmatched_submission_ids:
            if submission_id in seen_submission_ids:
                continue
            submission = submission_by_id.get(submission_id)
            if submission is None:
                continue
            seen_submission_ids.add(submission_id)
            unidentified.append(
                WhatsAppUnidentifiedUploadResponse(
                    submission_id=submission.id,
                    client_group_id=client_group.id,
                    client_group_name=client_group.name,
                    name=submission.client_name,
                    phone_number=(submission.client_phone or submission.family_head_phone),
                    email=submission.client_email or submission.family_head_email,
                    details=_unidentified_submission_details(submission),
                    updated_at=submission.updated_at,
                )
            )

    unidentified.sort(
        key=lambda upload: (
            upload.client_group_name.casefold(),
            upload.name.casefold(),
            upload.updated_at,
            str(upload.submission_id),
        )
    )
    return unidentified


@router.get(
    "/groups/{group_id}/recipient-roster",
    response_model=WhatsAppRecipientRosterResponse,
)
async def get_broadcast_recipient_roster(
    group_id: uuid.UUID,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppRecipientRosterResponse:
    group_result = await session.execute(
        select(WhatsAppBroadcastGroupModel).where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
    )
    group = group_result.scalar_one_or_none()
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp broadcast group not found",
        )

    recipients_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel)
        .where(
            WhatsAppBroadcastRecipientModel.broadcast_group_id == group_id,
            WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
            WhatsAppBroadcastRecipientModel.removed_at.is_(None),
        )
        .order_by(
            WhatsAppBroadcastRecipientModel.display_order.asc().nullslast(),
            WhatsAppBroadcastRecipientModel.created_at.asc(),
            WhatsAppBroadcastRecipientModel.id.asc(),
        )
    )
    recipients = list(recipients_result.scalars().all())
    rejected_result = await session.execute(
        select(WhatsAppBroadcastRejectedContactModel)
        .where(
            WhatsAppBroadcastRejectedContactModel.broadcast_group_id == group_id,
            WhatsAppBroadcastRejectedContactModel.agency_id == group.agency_id,
        )
        .order_by(
            WhatsAppBroadcastRejectedContactModel.display_order.asc().nullslast(),
            WhatsAppBroadcastRejectedContactModel.created_at.asc(),
            WhatsAppBroadcastRejectedContactModel.id.asc(),
        )
    )
    rejected_contacts = list(rejected_result.scalars().all())
    replaced_result = await session.execute(
        select(
            WhatsAppBroadcastRecipientModel,
            PassportRosterResolutionModel,
            ClientGroupModel,
            PassportSubmissionModel,
        )
        .join(
            PassportRosterResolutionModel,
            WhatsAppBroadcastRecipientModel.suppressed_by_roster_resolution_id
            == PassportRosterResolutionModel.id,
        )
        .join(
            ClientGroupModel,
            PassportRosterResolutionModel.client_group_id == ClientGroupModel.id,
        )
        .join(
            PassportSubmissionModel,
            PassportRosterResolutionModel.submission_id == PassportSubmissionModel.id,
        )
        .where(
            WhatsAppBroadcastRecipientModel.broadcast_group_id == group_id,
            WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
            WhatsAppBroadcastRecipientModel.removed_at.is_not(None),
            WhatsAppBroadcastRecipientModel.suppressed_by_roster_resolution_id.is_not(None),
            PassportRosterResolutionModel.agency_id == group.agency_id,
            PassportRosterResolutionModel.status == "active",
            PassportRosterResolutionModel.resolution_type == "replacement",
            ClientGroupModel.agency_id == group.agency_id,
            PassportSubmissionModel.agency_id == group.agency_id,
        )
        .order_by(
            WhatsAppBroadcastRecipientModel.display_order.asc().nullslast(),
            PassportRosterResolutionModel.created_at.asc(),
            WhatsAppBroadcastRecipientModel.id.asc(),
        )
    )
    replaced_rows = list(replaced_result.all())
    states_by_recipient, resend_statuses_by_recipient = await _recipient_delivery_state_maps(
        session, recipients
    )
    unidentified_uploads = await _unidentified_uploads_for_broadcast(
        session,
        broadcast_group_id=group_id,
        agency_id=group.agency_id,
    )

    roster_models: list[
        tuple[
            Literal["recipient", "rejected", "replaced"],
            WhatsAppBroadcastRecipientModel | WhatsAppBroadcastRejectedContactModel,
        ]
    ] = (
        [("recipient", recipient) for recipient in recipients]
        + [("rejected", rejected_contact) for rejected_contact in rejected_contacts]
        + [
            ("replaced", recipient)
            for recipient, _resolution, _client_group, _submission in replaced_rows
        ]
    )
    replaced_by_recipient_id = {
        recipient.id: (resolution, client_group, submission)
        for recipient, resolution, client_group, submission in replaced_rows
    }
    roster_models.sort(
        key=lambda item: (
            item[1].display_order is None,
            item[1].display_order or 0,
            item[1].created_at,
            item[0],
            str(item[1].id),
        )
    )
    next_fallback_order = (
        max(
            (model.display_order or 0 for _, model in roster_models),
            default=0,
        )
        + 1
    )
    items: list[WhatsAppRecipientRosterItemResponse] = []
    for kind, model in roster_models:
        display_order = model.display_order
        if display_order is None:
            display_order = next_fallback_order
            next_fallback_order += 1
        if kind == "recipient":
            recipient = model
            assert isinstance(recipient, WhatsAppBroadcastRecipientModel)
            items.append(
                WhatsAppRecipientRosterItemResponse(
                    kind="recipient",
                    display_order=display_order,
                    recipient=_recipient_response(
                        recipient,
                        states_by_recipient.get(recipient.id, []),
                        resend_statuses_by_recipient.get(recipient.id, {}),
                    ),
                )
            )
        elif kind == "rejected":
            rejected_contact = model
            assert isinstance(
                rejected_contact,
                WhatsAppBroadcastRejectedContactModel,
            )
            items.append(
                WhatsAppRecipientRosterItemResponse(
                    kind="rejected",
                    display_order=display_order,
                    rejected_contact=_rejected_contact_response(rejected_contact),
                )
            )
        else:
            recipient = model
            assert isinstance(recipient, WhatsAppBroadcastRecipientModel)
            resolution, client_group, submission = replaced_by_recipient_id[recipient.id]
            items.append(
                WhatsAppRecipientRosterItemResponse(
                    kind="replaced",
                    display_order=display_order,
                    replaced_recipient=WhatsAppReplacedRecipientResponse(
                        recipient_id=recipient.id,
                        resolution_id=resolution.id,
                        client_group_id=client_group.id,
                        client_group_name=client_group.name,
                        name=resolution.original_recipient_name,
                        phone_number=resolution.original_recipient_phone,
                        normalized_phone_number=(resolution.replaced_recipient_normalized_phone),
                        imported_fields=dict(resolution.original_recipient_imported_fields),
                        replacement_submission_id=submission.id,
                        replacement_name=submission.client_name,
                        replacement_phone=submission.client_phone,
                        replaced_at=resolution.created_at,
                    ),
                )
            )

    for upload in unidentified_uploads:
        items.append(
            WhatsAppRecipientRosterItemResponse(
                kind="unidentified",
                display_order=next_fallback_order,
                unidentified_upload=upload,
            )
        )
        next_fallback_order += 1

    sent_count = 0
    failed_count = 0
    for recipient in recipients:
        recipient_states = states_by_recipient.get(recipient.id, [])
        resend_statuses = resend_statuses_by_recipient.get(recipient.id, {})
        if any(state.status in WHATSAPP_ACCEPTED_STATUSES for state in recipient_states):
            sent_count += 1
        if (
            any(state.status == "failed" for state in recipient_states)
            or "failed" in resend_statuses.values()
        ):
            failed_count += 1

    return WhatsAppRecipientRosterResponse(
        items=items,
        counts=WhatsAppRecipientRosterCountsResponse(
            all=len(recipients) + len(rejected_contacts),
            sent=sent_count,
            failed=failed_count,
            rejected=len(rejected_contacts),
            replaced=len(replaced_rows),
            unidentified=len(unidentified_uploads),
        ),
    )


@router.get(
    "/groups/{group_id}/rejected-contacts",
    response_model=WhatsAppRejectedContactListResponse,
)
async def list_broadcast_rejected_contacts(
    group_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppRejectedContactListResponse:
    group_result = await session.execute(
        select(WhatsAppBroadcastGroupModel.id).where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
    )
    if group_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp broadcast group not found",
        )

    total_result = await session.execute(
        select(func.count())
        .select_from(WhatsAppBroadcastRejectedContactModel)
        .where(
            WhatsAppBroadcastRejectedContactModel.broadcast_group_id == group_id,
        )
    )
    total = int(total_result.scalar_one())
    items_result = await session.execute(
        select(WhatsAppBroadcastRejectedContactModel)
        .where(
            WhatsAppBroadcastRejectedContactModel.broadcast_group_id == group_id,
        )
        .order_by(
            WhatsAppBroadcastRejectedContactModel.created_at.desc(),
            WhatsAppBroadcastRejectedContactModel.source_file_name.asc(),
            WhatsAppBroadcastRejectedContactModel.sheet_name.asc(),
            WhatsAppBroadcastRejectedContactModel.row_number.asc(),
            WhatsAppBroadcastRejectedContactModel.id.asc(),
        )
        .limit(limit)
        .offset(offset)
    )
    return WhatsAppRejectedContactListResponse(
        items=[_rejected_contact_response(model) for model in items_result.scalars().all()],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/groups/{group_id}/rejected-contacts/{rejected_contact_id}/resolve",
    response_model=WhatsAppBroadcastGroupDetailResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def resolve_broadcast_rejected_contact(
    group_id: uuid.UUID,
    rejected_contact_id: uuid.UUID,
    body: WhatsAppRejectedContactResolveRequest,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppBroadcastGroupDetailResponse:
    group_result = await session.execute(
        select(WhatsAppBroadcastGroupModel)
        .where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
        .with_for_update()
    )
    group = group_result.scalar_one_or_none()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp broadcast group not found",
        )

    rejected_result = await session.execute(
        select(WhatsAppBroadcastRejectedContactModel)
        .where(
            WhatsAppBroadcastRejectedContactModel.id == rejected_contact_id,
            WhatsAppBroadcastRejectedContactModel.broadcast_group_id == group.id,
        )
        .with_for_update()
    )
    rejected_contact = rejected_result.scalar_one_or_none()
    if not rejected_contact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rejected WhatsApp contact not found",
        )

    name = _clean_name(body.name)
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Recipient name is required",
        )
    normalized_phone = _normalize_phone(body.phone_number)
    if not normalized_phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Use a 10-digit Indian mobile number, or an international number "
                "of 8 to 15 digits with its country code"
            ),
        )
    if not body.recipient_opt_in_confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirm this recipient agreed to receive WhatsApp updates",
        )

    existing_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel)
        .where(
            WhatsAppBroadcastRecipientModel.broadcast_group_id == group.id,
            WhatsAppBroadcastRecipientModel.normalized_phone_number == normalized_phone,
        )
        .with_for_update()
    )
    existing_recipient = existing_result.scalar_one_or_none()
    if existing_recipient and existing_recipient.removed_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That WhatsApp number is already in the valid recipient list",
        )
    if existing_recipient and existing_recipient.suppressed_by_roster_resolution_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This recipient is currently marked as replaced in a "
                "linked passport group. Restore that replacement from "
                "the group before adding them back."
            ),
        )
    try:
        await require_locked_broadcast_recipient_capacity(
            session,
            agency_id=group.agency_id,
            locked_broadcast_ids=[group.id],
            activating_by_broadcast={group.id: 1},
        )
    except WhatsAppRecipientCapacityExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "This WhatsApp list already contains the maximum of "
                f"{MAX_WHATSAPP_RECIPIENTS} valid recipients"
            ),
        ) from exc

    await _prepare_private_recipient_mutation(
        session,
        agency_id=group.agency_id,
        broadcast_group_id=group.id,
        cancellation_reason=(
            "WhatsApp recipients changed before private document or QR delivery"
        ),
    )
    now = datetime.now(tz=UTC)
    imported_fields = dict(rejected_contact.imported_fields or {})
    imported_fields.setdefault("source_file", rejected_contact.source_file_name)
    imported_fields.setdefault("source_sheet", rejected_contact.sheet_name)
    imported_fields.setdefault("source_row", str(rejected_contact.row_number))
    imported_fields = _safe_imported_fields(imported_fields)
    resolved_display_order = rejected_contact.display_order
    if resolved_display_order is None:
        resolved_display_order = await _next_roster_display_order(session, group.id)
    if existing_recipient:
        existing_recipient.name = name
        existing_recipient.phone_number = body.phone_number.strip()
        existing_recipient.imported_fields = imported_fields
        if existing_recipient.display_order is None:
            existing_recipient.display_order = resolved_display_order
        existing_recipient.removed_at = None
        await session.execute(
            delete(WhatsAppRecipientMessageStateModel).where(
                WhatsAppRecipientMessageStateModel.recipient_id == existing_recipient.id,
            )
        )
    else:
        session.add(
            WhatsAppBroadcastRecipientModel(
                broadcast_group_id=group.id,
                agency_id=group.agency_id,
                name=name,
                phone_number=body.phone_number.strip(),
                normalized_phone_number=normalized_phone,
                imported_fields=imported_fields,
                display_order=resolved_display_order,
                created_at=now,
            )
        )

    await session.execute(
        delete(WhatsAppBroadcastRejectedContactModel).where(
            WhatsAppBroadcastRejectedContactModel.id == rejected_contact.id,
        )
    )
    group.recipient_opt_in_confirmed_at = group.recipient_opt_in_confirmed_at or now
    group.updated_at = now
    await session.flush()
    await suppress_active_replacement_recipients(
        session,
        agency_id=group.agency_id,
        broadcast_group_ids=[group.id],
        now=now,
    )
    await session.flush()
    await reconcile_mobile_passenger_access_for_broadcast(
        session,
        agency_id=group.agency_id,
        broadcast_group_id=group.id,
        actor_user_id=current_user.id,
    )
    return await _group_detail(session, group)


@router.post(
    "/groups/{group_id}/welcome-media",
    response_model=WhatsAppWelcomeMediaResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def upload_welcome_media(
    group_id: uuid.UUID,
    image: UploadFile = File(...),
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppWelcomeMediaResponse:
    result = await session.execute(
        select(WhatsAppBroadcastGroupModel.agency_id).where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
    )
    group_agency_id = result.scalar_one_or_none()
    if group_agency_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp broadcast group not found",
        )
    if image.content_type not in {"image/jpeg", "image/png"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use a JPEG or PNG image for the Welcome message",
        )

    payload = bytearray()
    try:
        while chunk := await image.read(WHATSAPP_UPLOAD_READ_CHUNK_BYTES):
            payload.extend(chunk)
            if len(payload) > MAX_WHATSAPP_WELCOME_IMAGE_BYTES:
                try:
                    await UploadSecurityService().validate_image(
                        content=bytes(payload),
                        filename=image.filename,
                        declared_content_type=image.content_type,
                        context=UploadSecurityContext(
                            ingestion_flow="whatsapp_welcome_image",
                            agency_id=group_agency_id,
                            user_id=current_user.id,
                        ),
                        max_bytes=MAX_WHATSAPP_WELCOME_IMAGE_BYTES,
                    )
                except ImageValidationError:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail="The Welcome image must be 5 MB or smaller",
                    ) from None
    finally:
        try:
            await image.close()
        except Exception:
            pass
    try:
        validated = await UploadSecurityService().validate_image(
            content=bytes(payload),
            filename=image.filename,
            declared_content_type=image.content_type,
            context=UploadSecurityContext(
                ingestion_flow="whatsapp_welcome_image",
                agency_id=group_agency_id,
                user_id=current_user.id,
            ),
            max_bytes=MAX_WHATSAPP_WELCOME_IMAGE_BYTES,
        )
    except (MalwareScannerUnavailableError, UploadSecurityEvidenceError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document security scanning is temporarily unavailable",
            headers={"Retry-After": "30"},
        ) from exc
    except ImageValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
            media_id = await upload_whatsapp_image(
                client=client,
                settings=settings,
                file_name=validated.filename,
                file_content=validated.content,
                content_type=validated.content_type,
            )
    except WhatsAppCloudApiError as exc:
        response_status = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if exc.transient or exc.code == "WHATSAPP_PROVIDER_NOT_CONFIGURED"
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(
            status_code=response_status,
            detail=str(exc),
        ) from exc

    return WhatsAppWelcomeMediaResponse(
        media_id=media_id,
        file_name=validated.filename,
        content_type=validated.content_type,
    )


@router.post("/groups/{group_id}/preview", response_model=WhatsAppPreviewResponse)
async def preview_broadcast_message(
    group_id: uuid.UUID,
    body: WhatsAppPreviewRequest,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppPreviewResponse:
    result = await session.execute(
        select(WhatsAppBroadcastGroupModel).where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp broadcast group not found",
        )

    all_recipients = await _group_recipients(session, group.id)
    if not all_recipients:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This WhatsApp list has no recipients",
        )
    if body.recipient_id and body.resend_recipient_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose either a preview recipient or a resend recipient, not both",
        )
    recipients = _select_group_recipients(all_recipients, body.recipient_ids)
    if (
        body.resend_recipient_id
        and body.recipient_ids is not None
        and (len(recipients) != 1 or recipients[0].id != body.resend_recipient_id)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A resend preview can only target its selected recipient",
        )
    recipient = recipients[0]
    selected_recipient_id = body.resend_recipient_id or body.recipient_id
    if selected_recipient_id:
        selected = next(
            (item for item in recipients if item.id == selected_recipient_id),
            None,
        )
        if not selected:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Preview recipient not found in this WhatsApp list",
            )
        recipient = selected

    message_type = _as_message_type(body.message_type)
    snapshot: _WhatsAppComposerSnapshot | None = None
    content_source: Literal["default", "latest_group", "latest_recipient"] = "default"
    if body.resend_recipient_id:
        state_result = await session.execute(
            select(WhatsAppRecipientMessageStateModel).where(
                WhatsAppRecipientMessageStateModel.recipient_id == body.resend_recipient_id,
                WhatsAppRecipientMessageStateModel.message_type == message_type,
            )
        )
        target_state = state_result.scalar_one_or_none()
        if not target_state or (
            target_state.status not in WHATSAPP_ACCEPTED_STATUSES
            and target_state.status != "failed"
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only a sent or failed WhatsApp message can be opened here",
            )
        snapshot = await _latest_composer_snapshot(
            session,
            group_id=group.id,
            recipient_id=body.resend_recipient_id,
            message_type=message_type,
            accepted_only=target_state.status in WHATSAPP_ACCEPTED_STATUSES,
            include_failed=target_state.status == "failed",
            include_explicit_resends=True,
        )
        if snapshot:
            content_source = "latest_recipient"
    if snapshot is None and body.resend_recipient_id is None:
        snapshot = await _latest_composer_snapshot(
            session,
            group_id=group.id,
            message_type=message_type,
            accepted_only=True,
        )
        if snapshot:
            content_source = "latest_group"
    if body.resend_recipient_id is not None and snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No saved message is available to resend or retry for this recipient",
        )
    resolved_body = _merge_composer_snapshot(body, snapshot)
    support_contacts = _select_support_contacts(
        await _support_contacts_for_group(session, group.id),
        resolved_body.support_contact_ids,
        message_type=message_type,
    )
    (
        message_type,
        passport_intro,
        passport_link,
        message_content,
        recipient_name,
        rendered,
        header_parameters,
        parameters,
    ) = _message_values(
        group=group,
        recipient=recipient,
        support_contacts=support_contacts,
        body=resolved_body,
        preview=True,
    )
    if body.resend_recipient_id is not None:
        recipient_count = 1
        eligible_count = 1
        already_sent_count = (
            1
            if target_state is not None
            and target_state.status in WHATSAPP_ACCEPTED_STATUSES
            else 0
        )
        in_progress_count = 0
        uncertain_count = 0
    else:
        recipient_count = len(recipients)
        (
            eligible_count,
            already_sent_count,
            in_progress_count,
            uncertain_count,
        ) = await _recipient_delivery_counts(
            session,
            recipients=recipients,
            message_type=message_type,
        )
    template_name = _configured_template_name(message_type)
    return WhatsAppPreviewResponse(
        message_type=message_type,
        template_name=template_name,
        recipient_id=recipient.id,
        recipient_name=recipient_name,
        recipient_count=recipient_count,
        eligible_recipient_count=eligible_count,
        already_sent_count=already_sent_count,
        in_progress_count=in_progress_count,
        uncertain_recipient_count=uncertain_count,
        passport_intro=passport_intro,
        passport_link=(resolved_body.passport_link or "").strip() or None,
        message_content=message_content,
        header_image_id=(resolved_body.header_image_id or "").strip() or None,
        content_source=content_source,
        rendered_message=rendered,
        header_parameter_values=header_parameters,
        parameter_values=parameters,
    )


@router.post(
    "/groups",
    response_model=WhatsAppBroadcastGroupDetailResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_cookie_csrf)],
)
async def create_broadcast_group(
    name: str = Form(...),
    organizing_company_name: str | None = Form(None),
    contacts_json: str = Form("[]"),
    rejected_contacts_json: str = Form("[]"),
    support_contacts_json: str = Form("[]"),
    recipient_opt_in_confirmed: bool = Form(...),
    contacts_file: UploadFile | None = File(None),
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppBroadcastGroupDetailResponse:
    if not current_user.agency_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="User is not assigned to an agency"
        )
    # The authentication dependency has already performed a database read.
    # Release that transaction before parsing request JSON or workbook bytes.
    await session.rollback()
    group_name = name.strip()
    if not group_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Group name is required"
        )
    if len(group_name) > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Group name must be 100 characters or fewer",
        )
    company_name = _clean_name(organizing_company_name) or ""
    if len(company_name) > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organising company name must be 100 characters or fewer",
        )
    try:
        manual_contacts = [
            WhatsAppRecipientInput(**item) for item in json.loads(contacts_json or "[]")
        ]
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid manual contact list"
        ) from exc
    rejected_contacts = _parse_rejected_contacts(rejected_contacts_json)

    try:
        support_contacts = [
            WhatsAppSupportContactInput(**item)
            for item in json.loads(support_contacts_json or "[]")
        ]
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid customer support contact list",
        ) from exc
    if not support_contacts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add at least one customer support contact",
        )

    excel_contacts = await _parse_excel_contacts(contacts_file) if contacts_file else []
    contacts = manual_contacts + excel_contacts
    normalized_contacts = _normalized_recipient_inputs(contacts) if contacts else {}
    if not normalized_contacts and not rejected_contacts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add at least one valid or rejected WhatsApp contact",
        )
    if normalized_contacts and not recipient_opt_in_confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirm recipient WhatsApp opt-in before saving this list",
        )
    try:
        require_whatsapp_recipient_capacity(
            active_count=0,
            activating_count=len(normalized_contacts),
        )
    except WhatsAppRecipientCapacityExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"A WhatsApp list can contain at most {MAX_WHATSAPP_RECIPIENTS} recipients"),
        ) from exc
    unnamed_numbers = [
        contact.phone_number
        for contact in normalized_contacts.values()
        if not _clean_name(contact.name)
    ]
    if unnamed_numbers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Every recipient needs a name for personalised messages. "
                f"Missing names for {len(unnamed_numbers)} contact(s)."
            ),
        )
    long_names = [
        contact.phone_number
        for contact in normalized_contacts.values()
        if len(_clean_name(contact.name) or "") > 100
    ]
    if long_names:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Recipient names must be 100 characters or fewer",
        )

    normalized_support_contacts: dict[str, WhatsAppSupportContactInput] = {}
    for support_contact in support_contacts:
        normalized = _normalize_phone(support_contact.phone_number)
        if not normalized:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid WhatsApp number for support contact {support_contact.name}",
            )
        if normalized not in normalized_support_contacts:
            normalized_support_contacts[normalized] = support_contact
    if len(normalized_support_contacts) > 3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add no more than three customer support contacts",
        )

    actor = await _lock_active_whatsapp_actor(
        session,
        current_user=current_user,
        require_agency=True,
    )
    agency_id = actor.agency_id
    if agency_id is None:  # Defensive; the locked query requires an agency.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is no longer authorized for WhatsApp broadcasts.",
        )
    now = datetime.now(tz=UTC)
    group = WhatsAppBroadcastGroupModel(
        agency_id=agency_id,
        name=group_name,
        organizing_company_name=company_name,
        recipient_opt_in_confirmed_at=now if normalized_contacts else None,
        created_by_user_id=actor.id,
        created_at=now,
        updated_at=now,
    )
    session.add(group)
    await session.flush()
    recipient_display_orders, rejected_display_orders = _new_roster_display_orders(
        normalized_contacts=normalized_contacts,
        rejected_contacts=rejected_contacts,
        existing_by_phone={},
        existing_by_fingerprint={},
        start_order=1,
    )
    for normalized, contact in normalized_contacts.items():
        session.add(
            WhatsAppBroadcastRecipientModel(
                broadcast_group_id=group.id,
                agency_id=agency_id,
                name=_clean_name(contact.name),
                phone_number=contact.phone_number.strip(),
                normalized_phone_number=normalized,
                imported_fields=contact.imported_fields,
                display_order=recipient_display_orders[normalized],
                created_at=now,
            )
        )
    _add_rejected_contact_models(
        session=session,
        group=group,
        contacts=rejected_contacts,
        existing_by_fingerprint={},
        now=now,
        display_orders_by_fingerprint=rejected_display_orders,
    )
    for sort_order, (normalized, support_contact) in enumerate(normalized_support_contacts.items()):
        session.add(
            WhatsAppBroadcastSupportContactModel(
                broadcast_group_id=group.id,
                agency_id=agency_id,
                name=_clean_required_name(support_contact.name, "Customer support name"),
                phone_number=support_contact.phone_number.strip(),
                normalized_phone_number=normalized,
                sort_order=sort_order,
                created_at=now,
            )
        )
    await session.flush()
    return await _group_detail(session, group)


@router.patch(
    "/groups/{group_id}",
    response_model=WhatsAppBroadcastGroupDetailResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def update_broadcast_group(
    group_id: uuid.UUID,
    name: str | None = Form(None),
    organizing_company_name: str | None = Form(None),
    support_contacts_json: str | None = Form(None),
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppBroadcastGroupDetailResponse:
    result = await session.execute(
        select(WhatsAppBroadcastGroupModel)
        .where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
        .with_for_update()
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp broadcast group not found",
        )

    if name is not None:
        group_name = name.strip()
        if not group_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Group name is required",
            )
        if len(group_name) > 100:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Group name must be 100 characters or fewer",
            )
        group.name = group_name

    if organizing_company_name is not None:
        company_name = _clean_required_name(
            organizing_company_name,
            "Organising company name",
        )
        if len(company_name) > 100:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Organising company name must be 100 characters or fewer",
            )
        group.organizing_company_name = company_name

    if support_contacts_json is not None:
        support_contacts = _parse_support_contacts(support_contacts_json)
        await session.execute(
            delete(WhatsAppBroadcastSupportContactModel).where(
                WhatsAppBroadcastSupportContactModel.broadcast_group_id == group.id
            )
        )
        await session.flush()
        for sort_order, support_contact in enumerate(support_contacts):
            normalized = _normalize_phone(support_contact.phone_number)
            if not normalized:  # Defensive; _parse_support_contacts already validates.
                continue
            session.add(
                WhatsAppBroadcastSupportContactModel(
                    broadcast_group_id=group.id,
                    agency_id=group.agency_id,
                    name=_clean_required_name(
                        support_contact.name,
                        "Customer support name",
                    ),
                    phone_number=support_contact.phone_number.strip(),
                    normalized_phone_number=normalized,
                    sort_order=sort_order,
                    created_at=datetime.now(tz=UTC),
                )
            )

    group.updated_at = datetime.now(tz=UTC)
    await session.flush()
    return await _group_detail(session, group)


@router.post(
    "/groups/{group_id}/recipients",
    response_model=WhatsAppBroadcastGroupDetailResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def add_broadcast_recipients(
    group_id: uuid.UUID,
    contacts_json: str = Form("[]"),
    rejected_contacts_json: str = Form("[]"),
    recipient_opt_in_confirmed: bool = Form(...),
    contacts_file: UploadFile | None = File(None),
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppBroadcastGroupDetailResponse:
    # Do not retain the authentication transaction (or a group row lock)
    # while reading and parsing an untrusted workbook.
    await session.rollback()
    manual_contacts = _parse_manual_contacts(contacts_json)
    rejected_contacts = _parse_rejected_contacts(rejected_contacts_json)
    excel_contacts = await _parse_excel_contacts(contacts_file) if contacts_file else []
    contacts = manual_contacts + excel_contacts
    normalized_contacts = _normalized_recipient_inputs(contacts) if contacts else {}
    if not normalized_contacts and not rejected_contacts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add at least one valid or rejected WhatsApp contact",
        )
    if normalized_contacts and not recipient_opt_in_confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirm recipient WhatsApp opt-in before adding contacts",
        )

    actor = await _lock_active_whatsapp_actor(
        session,
        current_user=current_user,
        require_agency=current_user.role != UserRole.SUPER_ADMIN,
    )
    group_predicates = [WhatsAppBroadcastGroupModel.id == group_id]
    if actor.role != UserRole.SUPER_ADMIN.value:
        group_predicates.append(WhatsAppBroadcastGroupModel.agency_id == actor.agency_id)
    group_result = await session.execute(
        select(WhatsAppBroadcastGroupModel)
        .join(AgencyModel, AgencyModel.id == WhatsAppBroadcastGroupModel.agency_id)
        .where(*group_predicates, AgencyModel.is_active.is_(True))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    group = group_result.scalar_one_or_none()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp broadcast group not found",
        )

    existing_by_phone: dict[str, WhatsAppBroadcastRecipientModel] = {}
    if normalized_contacts:
        existing_result = await session.execute(
            select(WhatsAppBroadcastRecipientModel).where(
                WhatsAppBroadcastRecipientModel.broadcast_group_id == group.id
            )
        )
        existing_by_phone = {
            recipient.normalized_phone_number: recipient
            for recipient in existing_result.scalars().all()
        }
        active_count = sum(
            1 for recipient in existing_by_phone.values() if recipient.removed_at is None
        )
        activating_count = sum(
            1
            for normalized in normalized_contacts
            if normalized not in existing_by_phone
            or existing_by_phone[normalized].removed_at is not None
        )
        try:
            require_whatsapp_recipient_capacity(
                active_count=active_count,
                activating_count=activating_count,
                broadcast_group_id=group.id,
            )
        except WhatsAppRecipientCapacityExceeded as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"A WhatsApp list can contain at most {MAX_WHATSAPP_RECIPIENTS} recipients"
                ),
            ) from exc

    if normalized_contacts:
        await _prepare_private_recipient_mutation(
            session,
            agency_id=group.agency_id,
            broadcast_group_id=group.id,
            cancellation_reason=(
                "WhatsApp recipients changed before private document or QR delivery"
            ),
        )
    existing_rejected_by_fingerprint: dict[
        str,
        WhatsAppBroadcastRejectedContactModel,
    ] = {}
    if rejected_contacts:
        existing_rejected_result = await session.execute(
            select(WhatsAppBroadcastRejectedContactModel).where(
                WhatsAppBroadcastRejectedContactModel.broadcast_group_id == group.id,
            )
        )
        existing_rejected_contacts = list(existing_rejected_result.scalars().all())
        existing_rejected_by_fingerprint = {
            contact.fingerprint: contact for contact in existing_rejected_contacts
        }

    new_roster_count = sum(
        1 for normalized in normalized_contacts if normalized not in existing_by_phone
    ) + sum(
        1
        for contact in rejected_contacts
        if _rejected_contact_fingerprint(contact) not in existing_rejected_by_fingerprint
    )
    start_order = await _next_roster_display_order(session, group.id) if new_roster_count else 1
    recipient_display_orders, rejected_display_orders = _new_roster_display_orders(
        normalized_contacts=normalized_contacts,
        rejected_contacts=rejected_contacts,
        existing_by_phone=existing_by_phone,
        existing_by_fingerprint=existing_rejected_by_fingerprint,
        start_order=start_order,
    )

    now = datetime.now(tz=UTC)
    _activate_recipient_models(
        session=session,
        group=group,
        existing_by_phone=existing_by_phone,
        normalized_contacts=normalized_contacts,
        now=now,
        display_orders_by_phone=recipient_display_orders,
    )
    if rejected_contacts:
        _add_rejected_contact_models(
            session=session,
            group=group,
            contacts=rejected_contacts,
            existing_by_fingerprint=existing_rejected_by_fingerprint,
            now=now,
            display_orders_by_fingerprint=rejected_display_orders,
        )

    if normalized_contacts:
        group.recipient_opt_in_confirmed_at = group.recipient_opt_in_confirmed_at or now
    group.updated_at = now
    await session.flush()
    if normalized_contacts:
        await suppress_active_replacement_recipients(
            session,
            agency_id=group.agency_id,
            broadcast_group_ids=[group.id],
            now=now,
        )
        await session.flush()
        await reconcile_mobile_passenger_access_for_broadcast(
            session,
            agency_id=group.agency_id,
            broadcast_group_id=group.id,
            actor_user_id=current_user.id,
        )
    return await _group_detail(session, group)


@router.patch(
    "/groups/{group_id}/recipients/{recipient_id}",
    response_model=WhatsAppBroadcastGroupDetailResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def update_broadcast_recipient_phone(
    group_id: uuid.UUID,
    recipient_id: uuid.UUID,
    body: WhatsAppRecipientPhoneUpdateRequest,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppBroadcastGroupDetailResponse:
    group_result = await session.execute(
        select(WhatsAppBroadcastGroupModel)
        .where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
        .with_for_update()
    )
    group = group_result.scalar_one_or_none()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp broadcast group not found",
        )
    recipient_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel)
        .where(
            WhatsAppBroadcastRecipientModel.id == recipient_id,
            WhatsAppBroadcastRecipientModel.broadcast_group_id == group.id,
            WhatsAppBroadcastRecipientModel.removed_at.is_(None),
        )
        .with_for_update()
    )
    recipient = recipient_result.scalar_one_or_none()
    if not recipient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp recipient not found",
        )
    normalized_phone = _normalize_phone(body.phone_number)
    if not normalized_phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use 8 to 15 digits with an optional country code",
        )
    duplicate_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel.id).where(
            WhatsAppBroadcastRecipientModel.broadcast_group_id == group.id,
            WhatsAppBroadcastRecipientModel.normalized_phone_number == normalized_phone,
            WhatsAppBroadcastRecipientModel.id != recipient.id,
        )
    )
    if duplicate_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That WhatsApp number already belongs to another recipient in this list",
        )
    active_state_result = await session.execute(
        select(WhatsAppRecipientMessageStateModel.id).where(
            WhatsAppRecipientMessageStateModel.recipient_id == recipient.id,
            WhatsAppRecipientMessageStateModel.status.in_(
                WHATSAPP_IN_PROGRESS_STATUSES | WHATSAPP_UNCERTAIN_STATUSES
            ),
        )
    )
    if active_state_result.first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Wait until the current delivery finishes, or review its unknown "
                "outcome, before changing this number"
            ),
        )
    active_resend_result = await session.execute(
        select(WhatsAppMessageLogModel.id).where(
            WhatsAppMessageLogModel.recipient_id == recipient.id,
            WhatsAppMessageLogModel.is_explicit_resend.is_(True),
            WhatsAppMessageLogModel.status.in_(WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES),
        )
    )
    if active_resend_result.first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Wait until the current resend finishes, or review its unknown "
                "outcome, before changing this number"
            ),
        )
    if normalized_phone == recipient.normalized_phone_number:
        return await _group_detail(session, group)

    await _prepare_private_recipient_mutation(
        session,
        agency_id=group.agency_id,
        broadcast_group_id=group.id,
        recipient_id=recipient.id,
        cancellation_reason=(
            "WhatsApp recipient details changed before private document or QR delivery"
        ),
    )
    now = datetime.now(tz=UTC)
    recipient.phone_number = body.phone_number.strip()
    recipient.normalized_phone_number = normalized_phone
    await session.execute(
        update(WhatsAppRecipientMessageStateModel)
        .where(WhatsAppRecipientMessageStateModel.recipient_id == recipient.id)
        .values(
            status="failed",
            batch_id=None,
            submitted_at=None,
            provider_status_at=None,
            status_updated_at=now,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    group.updated_at = now
    await session.flush()
    await suppress_active_replacement_recipients(
        session,
        agency_id=group.agency_id,
        broadcast_group_ids=[group.id],
        now=now,
    )
    await session.flush()
    await reconcile_mobile_passenger_access_for_broadcast(
        session,
        agency_id=group.agency_id,
        broadcast_group_id=group.id,
        actor_user_id=current_user.id,
    )
    return await _group_detail(session, group)


async def _lock_removable_broadcast_recipient(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    recipient_id: uuid.UUID,
    current_user: User,
) -> tuple[WhatsAppBroadcastGroupModel, WhatsAppBroadcastRecipientModel]:
    """Lock a tenant-owned broadcast parent before its recipient child."""

    group_result = await session.execute(
        select(WhatsAppBroadcastGroupModel)
        .where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
        .with_for_update()
    )
    group = group_result.scalar_one_or_none()
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp recipient not found",
        )

    recipient_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel)
        .where(
            WhatsAppBroadcastRecipientModel.id == recipient_id,
            WhatsAppBroadcastRecipientModel.broadcast_group_id == group.id,
            WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
            WhatsAppBroadcastRecipientModel.removed_at.is_(None),
        )
        .with_for_update()
    )
    recipient = recipient_result.scalar_one_or_none()
    if recipient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp recipient not found",
        )
    return group, recipient


@router.delete(
    "/groups/{group_id}/recipients/{recipient_id}",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_cookie_csrf)],
)
async def remove_broadcast_recipient(
    group_id: uuid.UUID,
    recipient_id: uuid.UUID,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, bool]:
    group, recipient = await _lock_removable_broadcast_recipient(
        session,
        group_id=group_id,
        recipient_id=recipient_id,
        current_user=current_user,
    )

    await _prepare_private_recipient_mutation(
        session,
        agency_id=group.agency_id,
        broadcast_group_id=group.id,
        recipient_id=recipient.id,
        cancellation_reason=(
            "WhatsApp recipient was removed before private document or QR delivery"
        ),
    )
    now = datetime.now(tz=UTC)
    recipient.removed_at = now
    await session.execute(
        update(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.recipient_id == recipient.id,
            WhatsAppMessageLogModel.status == "queued",
        )
        .values(
            status="failed",
            status_updated_at=now,
            error_message="Recipient removed from WhatsApp broadcast before delivery",
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(WhatsAppRecipientMessageStateModel)
        .where(
            WhatsAppRecipientMessageStateModel.recipient_id == recipient.id,
            WhatsAppRecipientMessageStateModel.status == "queued",
        )
        .values(
            status="failed",
            batch_id=None,
            status_updated_at=now,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    group.updated_at = now
    await reconcile_mobile_passenger_access_for_broadcast(
        session,
        agency_id=group.agency_id,
        broadcast_group_id=group.id,
        actor_user_id=current_user.id,
    )
    return {"deleted": True}


@router.post(
    "/groups/{group_id}/recipients/{recipient_id}/resend",
    response_model=WhatsAppSendResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def resend_recipient_message(
    group_id: uuid.UUID,
    recipient_id: uuid.UUID,
    body: WhatsAppResendRequest,
    request: Request,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppSendResponse:
    group_result = await session.execute(
        select(WhatsAppBroadcastGroupModel)
        .where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
        .with_for_update()
    )
    group = group_result.scalar_one_or_none()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp broadcast group not found",
        )
    if group.recipient_opt_in_confirmed_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Recipient WhatsApp opt-in has not been confirmed for this list",
        )

    recipient_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel)
        .where(
            WhatsAppBroadcastRecipientModel.id == recipient_id,
            WhatsAppBroadcastRecipientModel.broadcast_group_id == group.id,
            WhatsAppBroadcastRecipientModel.removed_at.is_(None),
        )
        .with_for_update()
    )
    recipient = recipient_result.scalar_one_or_none()
    if not recipient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp recipient not found",
        )
    if await active_replacement_resolution_id_for_recipient(
        session,
        recipient=recipient,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This recipient is marked as replaced in a linked passport "
                "group. Restore that replacement before sending to them."
            ),
        )
    if body.recipient_ids is not None and set(body.recipient_ids) != {recipient.id}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A resend can only target its selected recipient",
        )

    message_type = _as_message_type(body.message_type)
    state_result = await session.execute(
        select(WhatsAppRecipientMessageStateModel)
        .where(
            WhatsAppRecipientMessageStateModel.recipient_id == recipient.id,
            WhatsAppRecipientMessageStateModel.message_type == message_type,
        )
        .with_for_update()
    )
    delivery_state = state_result.scalar_one_or_none()
    is_retry = bool(delivery_state and delivery_state.status == "failed")
    if not delivery_state or (
        delivery_state.status not in WHATSAPP_ACCEPTED_STATUSES and not is_retry
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Only a successfully submitted message can be resent, and only a "
                "failed message can be retried."
            ),
        )

    now = datetime.now(tz=UTC)
    stale_cutoff = now - WHATSAPP_STALE_CLAIM_AGE
    await session.execute(
        update(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.recipient_id == recipient.id,
            WhatsAppMessageLogModel.message_type == message_type,
            WhatsAppMessageLogModel.is_explicit_resend.is_(True),
            WhatsAppMessageLogModel.status == "queued",
            WhatsAppMessageLogModel.status_updated_at < stale_cutoff,
        )
        .values(
            status="failed",
            status_updated_at=now,
            error_message="Explicit resend claim expired before provider submission",
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.recipient_id == recipient.id,
            WhatsAppMessageLogModel.message_type == message_type,
            WhatsAppMessageLogModel.is_explicit_resend.is_(True),
            WhatsAppMessageLogModel.status == "processing",
            WhatsAppMessageLogModel.status_updated_at < stale_cutoff,
        )
        .values(
            status="delivery_unknown",
            status_updated_at=now,
            error_message=(
                "Explicit resend outcome is unknown after a worker interruption; "
                "another resend is blocked"
            ),
        )
        .execution_options(synchronize_session=False)
    )
    active_resend_result = await session.execute(
        select(WhatsAppMessageLogModel).where(
            WhatsAppMessageLogModel.recipient_id == recipient.id,
            WhatsAppMessageLogModel.message_type == message_type,
            WhatsAppMessageLogModel.is_explicit_resend.is_(True),
            WhatsAppMessageLogModel.status.in_(WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES),
        )
    )
    active_resend = active_resend_result.scalar_one_or_none()
    if active_resend:
        detail = (
            "The previous resend has an unknown delivery outcome. "
            "Verify it with the recipient before attempting another resend."
            if active_resend.status == "delivery_unknown"
            else "A resend of this message is already in progress for this recipient."
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
        )

    source_result = await session.execute(
        select(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.broadcast_group_id == group.id,
            WhatsAppMessageLogModel.recipient_id == recipient.id,
            WhatsAppMessageLogModel.message_type == message_type,
            WhatsAppMessageLogModel.status.in_(
                WHATSAPP_ACCEPTED_STATUSES | ({"failed"} if is_retry else set())
            ),
        )
        .order_by(
            WhatsAppMessageLogModel.created_at.desc(),
            WhatsAppMessageLogModel.status_updated_at.desc(),
        )
        .limit(1)
    )
    source_log = source_result.scalar_one_or_none()
    if not source_log:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The previously saved WhatsApp message could not be found",
        )
    try:
        source_snapshot = _composer_snapshot_from_log(source_log)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This older WhatsApp message cannot be safely reconstructed for resend. "
                "Send a fresh message from the normal preview instead."
            ),
        ) from exc

    settings = get_settings()
    if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp Cloud API credentials are incomplete",
        )
    configured_template_name = _configured_template_name(message_type)
    merged_body = _merge_composer_snapshot(body, source_snapshot)
    header_image_id = _resolve_send_header_image(
        message_type,
        merged_body.header_image_id,
        resend=True,
    )
    support_contacts = _select_support_contacts(
        await _support_contacts_for_group(session, group.id),
        merged_body.support_contact_ids,
        message_type=message_type,
    )
    if message_type == "passport_link" and not support_contacts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add customer support contacts before resending this message",
        )
    message_content = _resolve_send_message_content(
        message_type,
        merged_body.message_content,
        group_name=group.name,
    )
    passport_intro = (
        _resolve_send_passport_intro(
            merged_body.passport_intro,
            group_name=group.name,
        )
        if message_type == "passport_link"
        else None
    )
    passport_link = (
        _validate_passport_link(merged_body.passport_link)
        if message_type == "passport_link"
        else None
    )
    resolved_body = WhatsAppSendRequest(
        message_type=message_type,
        passport_intro=passport_intro,
        passport_link=passport_link,
        message_content=message_content,
        header_image_id=header_image_id,
        recipient_ids=merged_body.recipient_ids,
        support_contact_ids=merged_body.support_contact_ids,
    )
    (
        _,
        _,
        _,
        _,
        _,
        rendered_message,
        header_parameters,
        parameters,
    ) = _message_values(
        group=group,
        recipient=recipient,
        support_contacts=support_contacts,
        body=resolved_body,
    )
    template_name = configured_template_name.strip()
    if not template_name:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"WhatsApp {message_type} template name is not configured",
        )

    batch_id = uuid.uuid4()
    resend_log = WhatsAppMessageLogModel(
        batch_id=batch_id,
        broadcast_group_id=group.id,
        recipient_id=recipient.id,
        agency_id=recipient.agency_id,
        message_type=message_type,
        status="queued",
        status_updated_at=now,
        provider_message_id=None,
        error_message=None,
        template_name=template_name,
        rendered_message=rendered_message,
        header_parameter_values=header_parameters,
        template_parameter_values=parameters,
        is_explicit_resend=not is_retry,
        created_at=now,
    )
    session.add(resend_log)
    if is_retry:
        delivery_state.status = "queued"
        delivery_state.batch_id = batch_id
        delivery_state.submitted_at = None
        delivery_state.provider_status_at = None
        delivery_state.status_updated_at = now
        delivery_state.updated_at = now
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A resend of this message is already active for this recipient.",
        ) from exc

    await AuditLogRepository(session).record(
        action=(
            "whatsapp_recipient_message_retry_requested"
            if is_retry
            else "whatsapp_recipient_message_resend_requested"
        ),
        entity_type="whatsapp_broadcast_recipient",
        entity_id=str(recipient.id),
        agency_id=group.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=trusted_client_ip(request),
        metadata={
            "broadcast_group_id": str(group.id),
            "message_type": message_type,
            "source_message_log_id": str(source_log.id),
            "resend_batch_id": str(batch_id),
            "source_status": source_log.status,
        },
    )
    await session.commit()

    from app.infrastructure.whatsapp.tasks import process_whatsapp_broadcast

    try:
        process_whatsapp_broadcast.apply_async(
            kwargs={
                "batch_id": str(batch_id),
                "message_type": message_type,
                "message_content": (
                    parameters[0] if message_type in {"welcome", "reminder"} else parameters[2]
                ),
                "passport_intro": parameters[0] if message_type == "passport_link" else None,
                "passport_link": parameters[1] if message_type == "passport_link" else None,
                "header_image_id": (header_parameters[0] if header_parameters else None),
            },
            queue="whatsapp",
        )
    except Exception as exc:  # noqa: BLE001 - broker failure is surfaced and persisted.
        logger.error(
            "whatsapp_resend_queue_unavailable",
            extra={
                "batch_id": str(batch_id),
                "recipient_id": str(recipient.id),
                "error_type": type(exc).__name__,
            },
        )
        resend_log.status = "failed"
        resend_log.status_updated_at = datetime.now(tz=UTC)
        resend_log.error_message = (
            "WHATSAPP_QUEUE_UNAVAILABLE: WhatsApp delivery queue is temporarily unavailable"
        )
        if is_retry:
            delivery_state.status = "failed"
            delivery_state.batch_id = None
            delivery_state.status_updated_at = resend_log.status_updated_at
            delivery_state.updated_at = resend_log.status_updated_at
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp delivery queue is unavailable",
        ) from exc

    return WhatsAppSendResponse(
        batch_id=batch_id,
        queued=1,
        sent=0,
        failed=0,
        results=[
            WhatsAppSendResult(
                recipient_id=recipient.id,
                phone_number=recipient.normalized_phone_number,
                status="queued",
            )
        ],
    )


@router.delete(
    "/groups/{group_id}",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_cookie_csrf)],
)
async def delete_broadcast_group(
    group_id: uuid.UUID,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, bool]:
    result = await session.execute(
        select(WhatsAppBroadcastGroupModel)
        .where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
        .with_for_update()
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="WhatsApp broadcast group not found"
        )
    active_replacement_result = await session.execute(
        select(PassportRosterResolutionModel.id)
        .join(
            WhatsAppBroadcastRecipientModel,
            WhatsAppBroadcastRecipientModel.suppressed_by_roster_resolution_id
            == PassportRosterResolutionModel.id,
        )
        .where(
            WhatsAppBroadcastRecipientModel.broadcast_group_id == group.id,
            PassportRosterResolutionModel.status == "active",
            PassportRosterResolutionModel.resolution_type == "replacement",
        )
        .limit(1)
    )
    if active_replacement_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This broadcast contains a person marked as replaced in a "
                "linked passport group. Restore that replacement before "
                "deleting the broadcast."
            ),
        )
    processing_result = await session.execute(
        select(func.count())
        .select_from(WhatsAppRecipientMessageStateModel)
        .where(
            WhatsAppRecipientMessageStateModel.broadcast_group_id == group.id,
            WhatsAppRecipientMessageStateModel.status == "processing",
        )
    )
    explicit_processing_result = await session.execute(
        select(func.count())
        .select_from(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.broadcast_group_id == group.id,
            WhatsAppMessageLogModel.is_explicit_resend.is_(True),
            WhatsAppMessageLogModel.status == "processing",
        )
    )
    if int(processing_result.scalar_one()) > 0 or int(explicit_processing_result.scalar_one()) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A WhatsApp provider request is currently in progress. "
                "Wait for it to finish before deleting this broadcast."
            ),
        )
    await _prepare_private_recipient_mutation(
        session,
        agency_id=group.agency_id,
        broadcast_group_id=group.id,
        cancellation_reason=(
            "WhatsApp broadcast was deleted before private document or QR delivery"
        ),
    )
    now = datetime.now(tz=UTC)
    await session.execute(
        update(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.broadcast_group_id == group.id,
            WhatsAppMessageLogModel.status == "queued",
        )
        .values(
            status="failed",
            status_updated_at=now,
            error_message="WhatsApp broadcast deleted before delivery",
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(WhatsAppRecipientMessageStateModel)
        .where(
            WhatsAppRecipientMessageStateModel.broadcast_group_id == group.id,
            WhatsAppRecipientMessageStateModel.status == "queued",
        )
        .values(
            status="failed",
            batch_id=None,
            status_updated_at=now,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    linked_client_group_ids = tuple(
        sorted(
            set(
                (
                    await session.execute(
                        select(
                            ClientGroupWhatsAppBroadcastLinkModel.client_group_id
                        ).where(
                            ClientGroupWhatsAppBroadcastLinkModel.agency_id
                            == group.agency_id,
                            ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id
                            == group.id,
                        )
                    )
                ).scalars()
            ),
            key=str,
        )
    )
    await session.execute(
        delete(WhatsAppBroadcastGroupModel).where(WhatsAppBroadcastGroupModel.id == group.id)
    )
    await session.flush()
    for linked_client_group_id in linked_client_group_ids:
        await reconcile_mobile_passenger_access_for_group(
            session,
            agency_id=group.agency_id,
            group_id=linked_client_group_id,
            actor_user_id=current_user.id,
        )
    return {"deleted": True}


@router.post(
    "/groups/{group_id}/send",
    response_model=WhatsAppSendResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def send_broadcast_message(
    group_id: uuid.UUID,
    body: WhatsAppSendRequest,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppSendResponse:
    result = await session.execute(
        select(WhatsAppBroadcastGroupModel)
        .where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
        .with_for_update()
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="WhatsApp broadcast group not found"
        )
    if group.recipient_opt_in_confirmed_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Recipient WhatsApp opt-in has not been confirmed for this list",
        )

    all_recipients = await _group_recipients(session, group.id)
    if not all_recipients:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This WhatsApp list has no recipients",
        )
    try:
        require_whatsapp_recipient_capacity(
            active_count=len(all_recipients),
            activating_count=0,
        )
    except WhatsAppRecipientCapacityExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "This WhatsApp list exceeds the maximum of "
                f"{MAX_WHATSAPP_RECIPIENTS} recipients. Remove extra recipients before sending."
            ),
        ) from exc
    message_type = _as_message_type(body.message_type)
    recipients = _select_group_recipients(all_recipients, body.recipient_ids)
    support_contacts = await _support_contacts_for_group(session, group.id)
    snapshot = await _latest_composer_snapshot(
        session,
        group_id=group.id,
        message_type=message_type,
        accepted_only=True,
    )
    merged_body = _merge_composer_snapshot(body, snapshot)
    support_contacts = _select_support_contacts(
        support_contacts,
        merged_body.support_contact_ids,
        message_type=message_type,
    )
    if message_type == "passport_link" and not support_contacts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add customer support contacts before sending this message",
        )
    header_image_id = _resolve_send_header_image(
        message_type,
        merged_body.header_image_id,
    )
    message_content = _resolve_send_message_content(
        message_type,
        merged_body.message_content,
        group_name=group.name,
    )
    passport_intro = (
        _resolve_send_passport_intro(
            merged_body.passport_intro,
            group_name=group.name,
        )
        if message_type == "passport_link"
        else None
    )
    settings = get_settings()
    if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp Cloud API credentials are incomplete",
        )
    template_name = _configured_template_name(message_type)
    if not template_name.strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"WhatsApp {message_type} template name is not configured",
        )

    passport_link = (
        _validate_passport_link(merged_body.passport_link)
        if message_type == "passport_link"
        else None
    )
    resolved_body = WhatsAppSendRequest(
        message_type=message_type,
        passport_intro=passport_intro,
        passport_link=passport_link,
        message_content=message_content,
        header_image_id=header_image_id,
        recipient_ids=merged_body.recipient_ids,
        support_contact_ids=merged_body.support_contact_ids,
    )
    batch_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    stale_cutoff = now - WHATSAPP_STALE_CLAIM_AGE

    # A queued task has not contacted Meta and is safe to reclaim. A stale
    # processing task may have submitted bytes before a worker interruption,
    # so it becomes delivery_unknown and remains suppressed.
    await session.execute(
        update(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.broadcast_group_id == group.id,
            WhatsAppMessageLogModel.message_type == message_type,
            WhatsAppMessageLogModel.status == "queued",
            WhatsAppMessageLogModel.status_updated_at < stale_cutoff,
        )
        .values(
            status="failed",
            status_updated_at=now,
            error_message="Delivery claim expired before provider submission",
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.broadcast_group_id == group.id,
            WhatsAppMessageLogModel.message_type == message_type,
            WhatsAppMessageLogModel.status == "processing",
            WhatsAppMessageLogModel.status_updated_at < stale_cutoff,
        )
        .values(
            status="delivery_unknown",
            status_updated_at=now,
            error_message=(
                "Delivery outcome is unknown after a worker interruption; "
                "automatic resend is suppressed"
            ),
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(WhatsAppRecipientMessageStateModel)
        .where(
            WhatsAppRecipientMessageStateModel.broadcast_group_id == group.id,
            WhatsAppRecipientMessageStateModel.message_type == message_type,
            WhatsAppRecipientMessageStateModel.status == "processing",
            WhatsAppRecipientMessageStateModel.status_updated_at < stale_cutoff,
        )
        .values(
            status="delivery_unknown",
            status_updated_at=now,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )

    claim_values = [
        {
            "id": uuid.uuid4(),
            "broadcast_group_id": group.id,
            "recipient_id": recipient.id,
            "agency_id": recipient.agency_id,
            "message_type": message_type,
            "status": "queued",
            "batch_id": batch_id,
            "submitted_at": None,
            "status_updated_at": now,
            "created_at": now,
            "updated_at": now,
        }
        for recipient in recipients
    ]
    claim_insert = pg_insert(WhatsAppRecipientMessageStateModel).values(claim_values)
    claim_statement = (
        claim_insert.on_conflict_do_update(
            constraint="uq_whatsapp_recipient_message_state",
            set_={
                "status": "queued",
                "batch_id": batch_id,
                "submitted_at": None,
                "status_updated_at": now,
                "updated_at": now,
            },
            where=or_(
                ~WhatsAppRecipientMessageStateModel.status.in_(WHATSAPP_SUPPRESSED_STATUSES),
                and_(
                    WhatsAppRecipientMessageStateModel.status == "queued",
                    WhatsAppRecipientMessageStateModel.status_updated_at < stale_cutoff,
                ),
            ),
        )
        .returning(WhatsAppRecipientMessageStateModel.recipient_id)
        .execution_options(synchronize_session=False)
    )
    claimed_result = await session.execute(claim_statement)
    claimed_recipient_ids = set(claimed_result.scalars().all())
    claimed_recipients = [
        recipient for recipient in recipients if recipient.id in claimed_recipient_ids
    ]
    unclaimed_recipient_ids = [
        recipient.id for recipient in recipients if recipient.id not in claimed_recipient_ids
    ]
    skipped_already_sent = 0
    skipped_in_progress = 0
    skipped_delivery_unknown = 0
    if unclaimed_recipient_ids:
        skipped_result = await session.execute(
            select(WhatsAppRecipientMessageStateModel.status).where(
                WhatsAppRecipientMessageStateModel.recipient_id.in_(unclaimed_recipient_ids),
                WhatsAppRecipientMessageStateModel.message_type == message_type,
            )
        )
        skipped_statuses = list(skipped_result.scalars().all())
        skipped_already_sent = sum(
            1
            for delivery_status in skipped_statuses
            if delivery_status in WHATSAPP_ACCEPTED_STATUSES
        )
        skipped_in_progress = sum(
            1
            for delivery_status in skipped_statuses
            if delivery_status in WHATSAPP_IN_PROGRESS_STATUSES
        )
        skipped_delivery_unknown = sum(
            1
            for delivery_status in skipped_statuses
            if delivery_status in WHATSAPP_UNCERTAIN_STATUSES
        )

    if not claimed_recipients:
        await session.commit()
        return WhatsAppSendResponse(
            batch_id=None,
            queued=0,
            sent=0,
            failed=0,
            skipped_already_sent=skipped_already_sent,
            skipped_in_progress=skipped_in_progress,
            skipped_delivery_unknown=skipped_delivery_unknown,
            results=[],
        )

    results: list[WhatsAppSendResult] = []
    for recipient in claimed_recipients:
        (
            _,
            _,
            _,
            _,
            _,
            rendered,
            header_parameters,
            parameters,
        ) = _message_values(
            group=group,
            recipient=recipient,
            support_contacts=support_contacts,
            body=resolved_body,
        )
        session.add(
            WhatsAppMessageLogModel(
                batch_id=batch_id,
                broadcast_group_id=group.id,
                recipient_id=recipient.id,
                agency_id=recipient.agency_id,
                message_type=message_type,
                status="queued",
                status_updated_at=now,
                provider_message_id=None,
                error_message=None,
                template_name=template_name,
                rendered_message=rendered,
                header_parameter_values=header_parameters,
                template_parameter_values=parameters,
                is_explicit_resend=False,
                created_at=now,
            )
        )
        results.append(
            WhatsAppSendResult(
                recipient_id=recipient.id,
                phone_number=recipient.normalized_phone_number,
                status="queued",
            )
        )
    await session.commit()

    from app.infrastructure.whatsapp.tasks import process_whatsapp_broadcast

    try:
        process_whatsapp_broadcast.apply_async(
            kwargs={
                "batch_id": str(batch_id),
                "message_type": message_type,
                "message_content": message_content,
                "passport_intro": passport_intro,
                "passport_link": passport_link,
                "header_image_id": resolved_body.header_image_id,
            },
            queue="whatsapp",
        )
    except Exception as exc:  # noqa: BLE001 - convert broker failures into a visible batch failure.
        logger.error(
            "whatsapp_worker_queue_unavailable",
            extra={
                "batch_id": str(batch_id),
                "error_type": type(exc).__name__,
            },
        )
        error_message = (
            "WHATSAPP_QUEUE_UNAVAILABLE: WhatsApp delivery queue is temporarily unavailable"
        )
        logs_result = await session.execute(
            select(WhatsAppMessageLogModel).where(WhatsAppMessageLogModel.batch_id == batch_id)
        )
        for log in logs_result.scalars().all():
            log.status = "failed"
            log.status_updated_at = datetime.now(tz=UTC)
            log.error_message = error_message
        failure_time = datetime.now(tz=UTC)
        await session.execute(
            update(WhatsAppRecipientMessageStateModel)
            .where(
                WhatsAppRecipientMessageStateModel.batch_id == batch_id,
                WhatsAppRecipientMessageStateModel.status.in_(WHATSAPP_IN_PROGRESS_STATUSES),
            )
            .values(
                status="failed",
                batch_id=None,
                status_updated_at=failure_time,
                updated_at=failure_time,
            )
            .execution_options(synchronize_session=False)
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp delivery queue is unavailable",
        ) from exc

    return WhatsAppSendResponse(
        batch_id=batch_id,
        queued=len(results),
        sent=0,
        failed=0,
        skipped_already_sent=skipped_already_sent,
        skipped_in_progress=skipped_in_progress,
        skipped_delivery_unknown=skipped_delivery_unknown,
        results=results,
    )


@router.get(
    "/batches/{batch_id}/summary",
    response_model=WhatsAppBatchSummaryResponse,
)
async def get_broadcast_batch_summary(
    batch_id: uuid.UUID,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppBatchSummaryResponse:
    """Return O(1)-sized progress data for a broadcast batch."""

    result = await session.execute(
        _broadcast_batch_summary_statement(
            batch_id=batch_id,
            current_user=current_user,
            stale_cutoff=datetime.now(tz=UTC) - WHATSAPP_STALE_CLAIM_AGE,
        )
    )
    summary = result.one()
    if int(summary.total) == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp broadcast batch not found",
        )
    return WhatsAppBatchSummaryResponse(
        batch_id=batch_id,
        queued=int(summary.queued),
        sent=int(summary.sent),
        failed=int(summary.failed),
        delivery_unknown=int(summary.delivery_unknown),
    )


@router.get("/batches/{batch_id}", response_model=WhatsAppSendResponse)
async def get_broadcast_batch_status(
    batch_id: uuid.UUID,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppSendResponse:
    result = await session.execute(
        select(WhatsAppMessageLogModel, WhatsAppBroadcastRecipientModel)
        .join(
            WhatsAppBroadcastRecipientModel,
            WhatsAppBroadcastRecipientModel.id == WhatsAppMessageLogModel.recipient_id,
        )
        .join(
            WhatsAppBroadcastGroupModel,
            WhatsAppBroadcastGroupModel.id == WhatsAppMessageLogModel.broadcast_group_id,
        )
        .where(
            WhatsAppMessageLogModel.batch_id == batch_id,
            *_agency_filter(current_user),
        )
        .order_by(WhatsAppMessageLogModel.created_at.asc())
    )
    rows = list(result.all())
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp broadcast batch not found",
        )

    queued_statuses = {"queued", "processing"}
    successful_statuses = {"submitted", "sent", "delivered", "read"}
    uncertain_statuses = {"delivery_unknown", "stalled"}
    stale_cutoff = datetime.now(tz=UTC) - timedelta(minutes=30)
    results: list[WhatsAppSendResult] = []
    for log, recipient in rows:
        is_stalled = log.status in queued_statuses and log.status_updated_at < stale_cutoff
        results.append(
            WhatsAppSendResult(
                recipient_id=recipient.id,
                phone_number=recipient.normalized_phone_number,
                status="stalled" if is_stalled else log.status,
                provider_message_id=log.provider_message_id,
                error_message=(
                    log.error_message
                    or (
                        "Delivery status is unknown after a worker interruption; verify before resending"
                        if is_stalled
                        else None
                    )
                ),
            )
        )
    return WhatsAppSendResponse(
        batch_id=batch_id,
        queued=sum(1 for item in results if item.status in queued_statuses),
        sent=sum(1 for item in results if item.status in successful_statuses),
        failed=sum(
            1
            for item in results
            if item.status not in queued_statuses | successful_statuses | uncertain_statuses
        ),
        delivery_unknown=sum(1 for item in results if item.status in uncertain_statuses),
        results=results,
    )
