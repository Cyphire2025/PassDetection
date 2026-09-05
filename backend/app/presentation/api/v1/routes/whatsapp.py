"""Whatsapp router and backwards-compatible exports."""

# ruff: noqa: F401
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
from app.application.use_cases.whatsapp.message_templates import WhatsAppMessageType
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
from app.infrastructure.whatsapp.document_delivery_runtime import apply_document_provider_status
from app.infrastructure.whatsapp.private_delivery_policy import (
    PrivateDeliveryMutationBlocked,
    prepare_private_delivery_identity_mutation,
)
from app.infrastructure.whatsapp.qr_delivery_runtime import apply_qr_provider_status
from app.presentation.api.v1.routes import whatsapp_composer_support as _composer_support
from app.presentation.api.v1.routes import whatsapp_contact_support as _contact_support
from app.presentation.api.v1.routes import whatsapp_delivery_support as _delivery_support
from app.presentation.api.v1.routes import whatsapp_roster_support as _roster_support
from app.presentation.api.v1.routes.whatsapp_batch_status import (
    get_broadcast_batch_status as get_broadcast_batch_status,
)
from app.presentation.api.v1.routes.whatsapp_batch_status import (
    get_broadcast_batch_summary as get_broadcast_batch_summary,
)
from app.presentation.api.v1.routes.whatsapp_batch_status import router as _batch_status_router
from app.presentation.api.v1.routes.whatsapp_composer import (
    preview_broadcast_message as preview_broadcast_message,
)
from app.presentation.api.v1.routes.whatsapp_composer import router as _composer_router
from app.presentation.api.v1.routes.whatsapp_composer import (
    upload_welcome_media as upload_welcome_media,
)
from app.presentation.api.v1.routes.whatsapp_contact_import import (
    _append_excel_contact_rejection as _append_excel_contact_rejection,
)
from app.presentation.api.v1.routes.whatsapp_contact_import import (
    _parse_excel_contact_bytes as _parse_excel_contact_bytes,
)
from app.presentation.api.v1.routes.whatsapp_contact_import import (
    _parse_excel_contact_preview as _parse_excel_contact_preview,
)
from app.presentation.api.v1.routes.whatsapp_contact_import import (
    _parse_excel_contacts as _parse_excel_contacts,
)
from app.presentation.api.v1.routes.whatsapp_contact_import import (
    preview_excel_contacts as preview_excel_contacts,
)
from app.presentation.api.v1.routes.whatsapp_contact_import import router as _contact_import_router
from app.presentation.api.v1.routes.whatsapp_groups_delete import (
    delete_broadcast_group as delete_broadcast_group,
)
from app.presentation.api.v1.routes.whatsapp_groups_delete import router as _groups_delete_router
from app.presentation.api.v1.routes.whatsapp_groups_manage import (
    create_broadcast_group as create_broadcast_group,
)
from app.presentation.api.v1.routes.whatsapp_groups_manage import router as _groups_manage_router
from app.presentation.api.v1.routes.whatsapp_groups_manage import (
    update_broadcast_group as update_broadcast_group,
)
from app.presentation.api.v1.routes.whatsapp_groups_read import (
    get_broadcast_group as get_broadcast_group,
)
from app.presentation.api.v1.routes.whatsapp_groups_read import (
    list_broadcast_groups as list_broadcast_groups,
)
from app.presentation.api.v1.routes.whatsapp_groups_read import router as _groups_read_router
from app.presentation.api.v1.routes.whatsapp_recipient_roster import (
    _unidentified_submission_details as _unidentified_submission_details,
)
from app.presentation.api.v1.routes.whatsapp_recipient_roster import (
    _unidentified_uploads_for_broadcast as _unidentified_uploads_for_broadcast,
)
from app.presentation.api.v1.routes.whatsapp_recipient_roster import (
    get_broadcast_recipient_roster as get_broadcast_recipient_roster,
)
from app.presentation.api.v1.routes.whatsapp_recipient_roster import (
    router as _recipient_roster_router,
)
from app.presentation.api.v1.routes.whatsapp_recipients import (
    add_broadcast_recipients as add_broadcast_recipients,
)
from app.presentation.api.v1.routes.whatsapp_recipients import (
    remove_broadcast_recipient as remove_broadcast_recipient,
)
from app.presentation.api.v1.routes.whatsapp_recipients import router as _recipients_router
from app.presentation.api.v1.routes.whatsapp_recipients import (
    update_broadcast_recipient_phone as update_broadcast_recipient_phone,
)
from app.presentation.api.v1.routes.whatsapp_rejected_contacts import (
    list_broadcast_rejected_contacts as list_broadcast_rejected_contacts,
)
from app.presentation.api.v1.routes.whatsapp_rejected_contacts import (
    resolve_broadcast_rejected_contact as resolve_broadcast_rejected_contact,
)
from app.presentation.api.v1.routes.whatsapp_rejected_contacts import (
    router as _rejected_contacts_router,
)
from app.presentation.api.v1.routes.whatsapp_resend import (
    resend_recipient_message as resend_recipient_message,
)
from app.presentation.api.v1.routes.whatsapp_resend import router as _resend_router
from app.presentation.api.v1.routes.whatsapp_scope import (
    _configured_template_name as _configured_template_name,
)
from app.presentation.api.v1.routes.whatsapp_scope import (
    _lock_active_whatsapp_actor as _lock_active_whatsapp_actor,
)
from app.presentation.api.v1.routes.whatsapp_scope import (
    _lock_removable_broadcast_recipient as _lock_removable_broadcast_recipient,
)
from app.presentation.api.v1.routes.whatsapp_scope import (
    _prepare_private_recipient_mutation as _prepare_private_recipient_mutation,
)
from app.presentation.api.v1.routes.whatsapp_scope import (
    _release_auth_transaction as _release_auth_transaction,
)
from app.presentation.api.v1.routes.whatsapp_send import router as _send_router
from app.presentation.api.v1.routes.whatsapp_send import (
    send_broadcast_message as send_broadcast_message,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _EMPTY_EXCEL_VALUES as _EMPTY_EXCEL_VALUES,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _EXCEL_FIELD_ALIASES as _EXCEL_FIELD_ALIASES,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _WHATSAPP_CONTACT_REJECTION_REASONS as _WHATSAPP_CONTACT_REJECTION_REASONS,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    MAX_WHATSAPP_CONTACT_FILE_BYTES as MAX_WHATSAPP_CONTACT_FILE_BYTES,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    MAX_WHATSAPP_EXCEL_ARCHIVE_MEMBERS as MAX_WHATSAPP_EXCEL_ARCHIVE_MEMBERS,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    MAX_WHATSAPP_EXCEL_COMPRESSION_RATIO as MAX_WHATSAPP_EXCEL_COMPRESSION_RATIO,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    MAX_WHATSAPP_EXCEL_HEADER_SCAN_ROWS as MAX_WHATSAPP_EXCEL_HEADER_SCAN_ROWS,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    MAX_WHATSAPP_EXCEL_ROWS as MAX_WHATSAPP_EXCEL_ROWS,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    MAX_WHATSAPP_EXCEL_SHEETS as MAX_WHATSAPP_EXCEL_SHEETS,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    MAX_WHATSAPP_EXCEL_UNCOMPRESSED_BYTES as MAX_WHATSAPP_EXCEL_UNCOMPRESSED_BYTES,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    MAX_WHATSAPP_IMPORTED_FIELD_KEY_LENGTH as MAX_WHATSAPP_IMPORTED_FIELD_KEY_LENGTH,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    MAX_WHATSAPP_IMPORTED_FIELD_VALUE_LENGTH as MAX_WHATSAPP_IMPORTED_FIELD_VALUE_LENGTH,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    MAX_WHATSAPP_IMPORTED_FIELDS as MAX_WHATSAPP_IMPORTED_FIELDS,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    MAX_WHATSAPP_IMPORTED_FIELDS_BYTES as MAX_WHATSAPP_IMPORTED_FIELDS_BYTES,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    MAX_WHATSAPP_REJECTED_CONTACTS_PER_GROUP as MAX_WHATSAPP_REJECTED_CONTACTS_PER_GROUP,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    MAX_WHATSAPP_REJECTED_ROWS as MAX_WHATSAPP_REJECTED_ROWS,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    MAX_WHATSAPP_WELCOME_IMAGE_BYTES as MAX_WHATSAPP_WELCOME_IMAGE_BYTES,
)
from app.presentation.api.v1.routes.whatsapp_shared import PHONE_RE as PHONE_RE
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_ACCEPTED_STATUS_RANK as WHATSAPP_ACCEPTED_STATUS_RANK,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_ACCEPTED_STATUSES as WHATSAPP_ACCEPTED_STATUSES,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES as WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_IN_PROGRESS_STATUSES as WHATSAPP_IN_PROGRESS_STATUSES,
)
from app.presentation.api.v1.routes.whatsapp_shared import WHATSAPP_ROLES as WHATSAPP_ROLES
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_ROSTER_SOURCE_FIELDS as WHATSAPP_ROSTER_SOURCE_FIELDS,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_STALE_CLAIM_AGE as WHATSAPP_STALE_CLAIM_AGE,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_SUPPRESSED_STATUSES as WHATSAPP_SUPPRESSED_STATUSES,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_UNCERTAIN_STATUSES as WHATSAPP_UNCERTAIN_STATUSES,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_UPLOAD_READ_CHUNK_BYTES as WHATSAPP_UPLOAD_READ_CHUNK_BYTES,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_WEBHOOK_STATUSES as WHATSAPP_WEBHOOK_STATUSES,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _activate_recipient_models as _activate_recipient_models,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _add_rejected_contact_models as _add_rejected_contact_models,
)
from app.presentation.api.v1.routes.whatsapp_shared import _agency_filter as _agency_filter
from app.presentation.api.v1.routes.whatsapp_shared import (
    _apply_provider_status_to_delivery_state as _apply_provider_status_to_delivery_state,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _apply_provider_status_to_message_log as _apply_provider_status_to_message_log,
)
from app.presentation.api.v1.routes.whatsapp_shared import _as_message_type as _as_message_type
from app.presentation.api.v1.routes.whatsapp_shared import (
    _bounded_excel_raw_value as _bounded_excel_raw_value,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _broadcast_batch_summary_statement as _broadcast_batch_summary_statement,
)
from app.presentation.api.v1.routes.whatsapp_shared import _clean_name as _clean_name
from app.presentation.api.v1.routes.whatsapp_shared import (
    _clean_required_name as _clean_required_name,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _composer_snapshot_from_log as _composer_snapshot_from_log,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _decode_legacy_template_snapshot as _decode_legacy_template_snapshot,
)
from app.presentation.api.v1.routes.whatsapp_shared import _excel_cell_text as _excel_cell_text
from app.presentation.api.v1.routes.whatsapp_shared import (
    _excel_contact_preview_response as _excel_contact_preview_response,
)
from app.presentation.api.v1.routes.whatsapp_shared import _excel_field_key as _excel_field_key
from app.presentation.api.v1.routes.whatsapp_shared import (
    _excel_fields_from_row as _excel_fields_from_row,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _excel_header_columns as _excel_header_columns,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _excel_header_label as _excel_header_label,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _excel_name_from_row as _excel_name_from_row,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _excel_raw_name_from_row as _excel_raw_name_from_row,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _extract_status_error as _extract_status_error,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _find_excel_contact_header as _find_excel_contact_header,
)
from app.presentation.api.v1.routes.whatsapp_shared import _group_detail as _group_detail
from app.presentation.api.v1.routes.whatsapp_shared import _group_recipients as _group_recipients
from app.presentation.api.v1.routes.whatsapp_shared import (
    _is_excel_name_header as _is_excel_name_header,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _is_excel_phone_header as _is_excel_phone_header,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _is_repeated_excel_header as _is_repeated_excel_header,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _is_stale_provider_status as _is_stale_provider_status,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _iter_webhook_values as _iter_webhook_values,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _latest_composer_snapshot as _latest_composer_snapshot,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _merge_composer_snapshot as _merge_composer_snapshot,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _merge_recipient_inputs as _merge_recipient_inputs,
)
from app.presentation.api.v1.routes.whatsapp_shared import _message_values as _message_values
from app.presentation.api.v1.routes.whatsapp_shared import (
    _new_roster_display_orders as _new_roster_display_orders,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _next_roster_display_order as _next_roster_display_order,
)
from app.presentation.api.v1.routes.whatsapp_shared import _normalize_phone as _normalize_phone
from app.presentation.api.v1.routes.whatsapp_shared import (
    _normalized_recipient_inputs as _normalized_recipient_inputs,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _parse_manual_contacts as _parse_manual_contacts,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _parse_provider_status_at as _parse_provider_status_at,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _parse_rejected_contacts as _parse_rejected_contacts,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _parse_support_contacts as _parse_support_contacts,
)
from app.presentation.api.v1.routes.whatsapp_shared import _positive_int as _positive_int
from app.presentation.api.v1.routes.whatsapp_shared import (
    _provider_status_state_predicates as _provider_status_state_predicates,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _recipient_delivery_counts as _recipient_delivery_counts,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _recipient_delivery_state_maps as _recipient_delivery_state_maps,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _recipient_response as _recipient_response,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _rejected_contact_fingerprint as _rejected_contact_fingerprint,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _rejected_contact_response as _rejected_contact_response,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _resolve_message_content as _resolve_message_content,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _resolve_passport_intro as _resolve_passport_intro,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _resolve_send_header_image as _resolve_send_header_image,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _resolve_send_message_content as _resolve_send_message_content,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _resolve_send_passport_intro as _resolve_send_passport_intro,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _roster_source_sort_key as _roster_source_sort_key,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _row_has_contact_identity as _row_has_contact_identity,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _safe_imported_fields as _safe_imported_fields,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _select_group_recipients as _select_group_recipients,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _select_support_contacts as _select_support_contacts,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _split_rendered_support_block as _split_rendered_support_block,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _support_contact_response as _support_contact_response,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _support_contacts_for_group as _support_contacts_for_group,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _template_snapshot_from_log as _template_snapshot_from_log,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _validate_excel_archive as _validate_excel_archive,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _validate_passport_link as _validate_passport_link,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _WhatsAppComposerSnapshot as _WhatsAppComposerSnapshot,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _WhatsAppExcelContactParseResult as _WhatsAppExcelContactParseResult,
)
from app.presentation.api.v1.routes.whatsapp_shared import logger as logger
from app.presentation.api.v1.routes.whatsapp_webhook import (
    _verify_meta_signature as _verify_meta_signature,
)
from app.presentation.api.v1.routes.whatsapp_webhook import (
    receive_whatsapp_webhook as receive_whatsapp_webhook,
)
from app.presentation.api.v1.routes.whatsapp_webhook import router as _webhook_router
from app.presentation.api.v1.routes.whatsapp_webhook import (
    verify_whatsapp_webhook as verify_whatsapp_webhook,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
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
from app.presentation.dependencies.auth import WHATSAPP_BROADCAST_ROLES, require_role
from app.presentation.dependencies.csrf import require_cookie_csrf
from app.presentation.security.client_ip import trusted_client_ip

router = APIRouter()
router.include_router(_webhook_router)
router.include_router(_contact_import_router)
router.include_router(_groups_read_router)
router.include_router(_recipient_roster_router)
router.include_router(_rejected_contacts_router)
router.include_router(_composer_router)
router.include_router(_groups_manage_router)
router.include_router(_recipients_router)
router.include_router(_resend_router)
router.include_router(_groups_delete_router)
router.include_router(_send_router)
router.include_router(_batch_status_router)
