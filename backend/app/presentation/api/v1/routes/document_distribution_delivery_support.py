"""Delivery policy and response helpers for document-distribution routes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.infrastructure.database.models import (
    DocumentDistributionBatchModel,
    DocumentWhatsAppDeliveryModel,
)
from app.presentation.api.v1.schemas.document_distribution_schemas import (
    DocumentBatchResponse,
)

DOCUMENT_DELIVERY_ACCEPTED_STATUSES = frozenset({"submitted", "sent", "delivered", "read"})
DOCUMENT_DELIVERY_IN_PROGRESS_STATUSES = frozenset({"queued", "processing", "delivery_unknown"})
DOCUMENT_DELIVERY_STORAGE_REQUIRED_STATUSES = frozenset({"queued", "processing"})
DOCUMENT_DELIVERY_WEBHOOK_GRACE = timedelta(minutes=5)
DOCUMENT_DELIVERY_ACTIVE_POLL_SECONDS = 5
DOCUMENT_DELIVERY_WEBHOOK_POLL_SECONDS = 10
SHARED_WHATSAPP_DESTINATION_REASON = (
    "A WhatsApp destination is shared by multiple passengers. Correct the recipient "
    "numbers before sending private documents."
)


def _document_delivery_poll_after_seconds(
    *,
    status_counts: dict[str, int],
    latest_status_updates: dict[str, datetime],
    now: datetime,
) -> int | None:
    if any(status_counts.get(value, 0) for value in ("queued", "processing")):
        return DOCUMENT_DELIVERY_ACTIVE_POLL_SECONDS
    awaiting_receipt_updates = [
        latest_status_updates[value]
        for value in ("submitted", "sent")
        if value in latest_status_updates
    ]
    if not awaiting_receipt_updates:
        return None
    latest_update = max(awaiting_receipt_updates)
    if latest_update.tzinfo is None:
        latest_update = latest_update.replace(tzinfo=UTC)
    if latest_update + DOCUMENT_DELIVERY_WEBHOOK_GRACE > now:
        return DOCUMENT_DELIVERY_WEBHOOK_POLL_SECONDS
    return None


@dataclass(frozen=True)
class DocumentDeliveryDecision:
    status: str
    eligible: bool
    resend_allowed: bool
    reason: str
    error_message: str | None = None


def _document_delivery_decision(
    *,
    saved: bool,
    match_status: str,
    recipient_available: bool,
    delivery_history: list[DocumentWhatsAppDeliveryModel],
) -> DocumentDeliveryDecision:
    if not saved:
        return DocumentDeliveryDecision(
            status="blocked",
            eligible=False,
            resend_allowed=False,
            reason="Save this document list before sending this document.",
        )
    if match_status != "matched":
        return DocumentDeliveryDecision(
            status="blocked",
            eligible=False,
            resend_allowed=False,
            reason="The document still needs manual matching review.",
        )
    if not recipient_available:
        return DocumentDeliveryDecision(
            status="blocked",
            eligible=False,
            resend_allowed=False,
            reason=(
                "No confirmed WhatsApp recipient could be matched to this passenger "
                "from the linked broadcasts."
            ),
        )

    in_progress = next(
        (
            item
            for item in delivery_history
            if item.status in DOCUMENT_DELIVERY_IN_PROGRESS_STATUSES
        ),
        None,
    )
    if in_progress:
        return DocumentDeliveryDecision(
            status=in_progress.status,
            eligible=False,
            resend_allowed=False,
            reason=(
                "Delivery is already in progress."
                if in_progress.status != "delivery_unknown"
                else "The previous delivery outcome is uncertain; resend is suppressed."
            ),
        )

    accepted = next(
        (item for item in delivery_history if item.status in DOCUMENT_DELIVERY_ACCEPTED_STATUSES),
        None,
    )
    if accepted:
        return DocumentDeliveryDecision(
            status="already_sent",
            eligible=False,
            resend_allowed=True,
            reason=(
                f"Already sent to {accepted.phone_number}. "
                "Choose Resend explicitly to send it again."
            ),
        )

    latest = delivery_history[0] if delivery_history else None
    if latest and latest.status == "failed":
        return DocumentDeliveryDecision(
            status="retryable",
            eligible=True,
            resend_allowed=False,
            reason="The previous attempt failed and can be retried safely.",
            error_message=latest.error_message,
        )
    return DocumentDeliveryDecision(
        status="ready",
        eligible=True,
        resend_allowed=False,
        reason="Ready to send.",
    )


def _preferred_document_message_content(
    deliveries: list[DocumentWhatsAppDeliveryModel],
    *,
    fallback_content_1: str,
    fallback_content_2: str,
) -> tuple[str, str]:
    """Prefer the newest complete message pair already stored in the delivery ledger."""

    for delivery in deliveries:
        values = delivery.template_parameter_values
        if not isinstance(values, list) or len(values) < 2:
            continue
        content_1 = str(values[0] or "").strip()
        content_2 = str(values[1] or "").strip()
        if content_1 and content_2:
            return content_1, content_2
    return fallback_content_1, fallback_content_2


def _processing_batch_response(
    batch: DocumentDistributionBatchModel,
) -> DocumentBatchResponse:
    """Avoid O(n-squared) roster hydration for non-final upload chunks."""

    return DocumentBatchResponse(
        batch_id=batch.id,
        group_id=batch.group_id,
        document_type=batch.document_type,
        status="processing",
        uploaded_count=batch.uploaded_count,
        rejected_count=batch.rejected_count,
        matched_count=batch.matched_count,
        processing_upload_ids=[batch.id],
        saved_at=None,
        created_at=batch.created_at,
        review_rows=[],
        unmatched_documents=[],
        rejected_documents=[],
    )
