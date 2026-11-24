"""Pure private QR-delivery eligibility and explicit preview counter updates."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.infrastructure.database.models import (
    PassengerQRTokenModel,
    PassengerQrWhatsAppDeliveryModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.whatsapp.phone_welcome import welcome_required_reason
from app.presentation.api.v1.schemas.tour_operations_schemas import QrDeliveryPreviewSummary

from .tour_operations_qr_delivery_policy import (
    ACCEPTED_STATUSES,
    AMBIGUOUS_PRIVATE_DESTINATION_REASON,
    IN_PROGRESS_STATUSES,
)


@dataclass(frozen=True, slots=True)
class QrDeliveryEligibility:
    delivery_status: str
    eligible: bool
    reason: str
    ambiguous: bool = False


def qr_delivery_eligibility(
    *,
    token: PassengerQRTokenModel | None,
    token_status: str,
    matched_recipient: tuple[WhatsAppBroadcastRecipientModel, str] | None,
    existing_delivery: PassengerQrWhatsAppDeliveryModel | None,
    ambiguous: bool,
    welcome_states: Mapping[str, str],
) -> QrDeliveryEligibility:
    if token is None:
        return QrDeliveryEligibility(
            "blocked", False, "Generate an active QR code for this passenger first."
        )
    if token_status != "active":
        return QrDeliveryEligibility(
            "blocked",
            False,
            "Only an active QR code can be sent. Activate or regenerate this passenger's QR first.",
        )
    if not token.qr_payload:
        return QrDeliveryEligibility(
            "blocked", False, "The active QR image cannot be reconstructed; regenerate it first."
        )
    if ambiguous:
        return QrDeliveryEligibility(
            "blocked", False, AMBIGUOUS_PRIVATE_DESTINATION_REASON, ambiguous=True
        )
    if matched_recipient is None:
        return QrDeliveryEligibility(
            "blocked",
            False,
            "No confirmed WhatsApp recipient could be matched to this passenger "
            "from the linked broadcasts.",
        )
    welcome_reason = welcome_required_reason(
        welcome_states.get(matched_recipient[0].normalized_phone_number)
    )
    if welcome_reason:
        return QrDeliveryEligibility("blocked", False, welcome_reason)
    if existing_delivery and existing_delivery.status in ACCEPTED_STATUSES:
        return QrDeliveryEligibility(
            "already_sent", False, "This QR version was already accepted by WhatsApp."
        )
    if existing_delivery and existing_delivery.status in IN_PROGRESS_STATUSES:
        return QrDeliveryEligibility(
            existing_delivery.status,
            False,
            "Delivery is already in progress."
            if existing_delivery.status != "delivery_unknown"
            else "The previous delivery outcome is uncertain; automatic resend is suppressed.",
        )
    if existing_delivery and existing_delivery.status == "failed":
        return QrDeliveryEligibility(
            "retryable", True, "The previous attempt failed and can be retried safely."
        )
    return QrDeliveryEligibility("ready", True, "Ready to send this passenger's individual QR.")


def record_preview_eligibility(
    summary: QrDeliveryPreviewSummary, decision: QrDeliveryEligibility
) -> None:
    if decision.ambiguous:
        summary.ambiguous_recipients += 1
    if decision.delivery_status == "blocked":
        summary.blocked += 1
    elif decision.delivery_status == "already_sent":
        summary.already_sent += 1
    elif decision.delivery_status in IN_PROGRESS_STATUSES:
        summary.in_progress += 1
    elif decision.delivery_status == "retryable":
        summary.retryable += 1
    elif decision.delivery_status == "ready":
        summary.ready += 1
