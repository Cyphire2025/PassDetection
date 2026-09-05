"""Document distribution: shared."""

from __future__ import annotations

from contextvars import ContextVar
from typing import ParamSpec, TypeVar

from fastapi import status

from app.core.logging.logger import get_logger
from app.presentation.api.v1.routes import (
    document_distribution_delivery_support as _delivery_support,
)
from app.presentation.api.v1.routes import document_distribution_review_support as _review_support

logger = get_logger("app.presentation.api.v1.routes.document_distribution")

DOCUMENT_RESPONSE_RENDER_WINDOW = 64

DOCUMENT_DELIVERY_ACCEPTED_STATUSES = _delivery_support.DOCUMENT_DELIVERY_ACCEPTED_STATUSES

DOCUMENT_DELIVERY_IN_PROGRESS_STATUSES = _delivery_support.DOCUMENT_DELIVERY_IN_PROGRESS_STATUSES

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
