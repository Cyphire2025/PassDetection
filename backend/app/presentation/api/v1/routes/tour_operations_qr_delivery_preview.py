"""Compose scoped QR sources, eligibility rows and delivery configuration."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.qr_templates import (
    QR_DEFAULT_MESSAGE_CONTENT,
    render_qr_message,
)
from app.core.config.settings import Settings
from app.infrastructure.database.models import (
    ClientGroupModel,
    PassengerQRTokenModel,
    PassengerQrWhatsAppDeliveryModel,
    PassportSubmissionModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.whatsapp.phone_welcome import (
    welcome_states_for_phones,
)
from app.infrastructure.whatsapp.template_settings import configured_template_name
from app.presentation.api.v1.schemas.tour_operations_schemas import (
    QrDeliveryPreviewRecipient,
    QrDeliveryPreviewResponse,
    QrDeliveryPreviewSummary,
)

from .tour_operations_qr_delivery_roster import (
    _linked_recipients,
    _matched_recipients,
    _passport_number,
)
from .tour_operations_qr_eligibility import qr_delivery_eligibility, record_preview_eligibility
from .tour_operations_qr_preview_sources import load_qr_preview_sources


def _preview_recipient(
    *,
    passenger: PassportSubmissionModel,
    token: PassengerQRTokenModel | None,
    matched_recipient: tuple[WhatsAppBroadcastRecipientModel, str] | None,
    existing_delivery: PassengerQrWhatsAppDeliveryModel | None,
    ambiguous: bool,
    welcome_states: dict[str, str],
    qr_status: Callable[[PassengerQRTokenModel | None], str],
    summary: QrDeliveryPreviewSummary,
) -> QrDeliveryPreviewRecipient:
    token_status = qr_status(token)
    decision = qr_delivery_eligibility(
        token=token,
        token_status=token_status,
        matched_recipient=matched_recipient,
        existing_delivery=existing_delivery,
        ambiguous=ambiguous,
        welcome_states=welcome_states,
    )
    record_preview_eligibility(summary, decision)
    recipient = matched_recipient[0] if matched_recipient else None
    return QrDeliveryPreviewRecipient(
        passenger_id=passenger.id,
        passenger_name=passenger.client_name,
        passport_number=_passport_number(passenger),
        qr_token_id=token.id if token else None,
        qr_token_version=token.token_version if token else None,
        qr_status=token_status,
        recipient_id=recipient.id if recipient else None,
        broadcast_group_id=recipient.broadcast_group_id if recipient else None,
        broadcast_name=matched_recipient[1] if matched_recipient else None,
        phone_number=recipient.normalized_phone_number if recipient else None,
        delivery_id=existing_delivery.id if existing_delivery else None,
        delivery_status=decision.delivery_status,
        eligible=decision.eligible,
        reason=decision.reason,
        error_message=existing_delivery.error_message
        if existing_delivery and existing_delivery.status == "failed"
        else None,
        message_preview=render_qr_message(message_content=QR_DEFAULT_MESSAGE_CONTENT)
        if token and matched_recipient
        else None,
    )


async def build_qr_delivery_preview(
    session: AsyncSession,
    *,
    group: ClientGroupModel,
    get_settings: Callable[[], Settings],
    qr_status: Callable[[PassengerQRTokenModel | None], str],
) -> QrDeliveryPreviewResponse:
    passengers, latest_token_by_passenger, delivery_by_token = await load_qr_preview_sources(
        session, group=group
    )
    linked_broadcasts, matching_fields_by_broadcast, recipient_models = await _linked_recipients(
        session, group=group
    )
    recipient_by_submission, ambiguous_submission_ids = _matched_recipients(
        submissions=passengers,
        recipients=recipient_models,
        linked_broadcasts=linked_broadcasts,
        matching_fields_by_broadcast=matching_fields_by_broadcast,
    )
    welcome_states = await welcome_states_for_phones(
        session,
        agency_id=group.agency_id,
        phones=[recipient.normalized_phone_number for recipient in recipient_models],
    )
    rows: list[QrDeliveryPreviewRecipient] = []
    summary = QrDeliveryPreviewSummary(total_passengers=len(passengers))
    for passenger in passengers:
        token = latest_token_by_passenger.get(passenger.id)
        matched_recipient = recipient_by_submission.get(passenger.id)
        existing_delivery = delivery_by_token.get(token.id) if token else None
        rows.append(
            _preview_recipient(
                passenger=passenger,
                token=token,
                matched_recipient=matched_recipient,
                existing_delivery=existing_delivery,
                ambiguous=passenger.id in ambiguous_submission_ids,
                welcome_states=welcome_states,
                qr_status=qr_status,
                summary=summary,
            )
        )
    settings = get_settings()
    template_name = await configured_template_name(session, "qr")
    provider_configured = bool(
        template_name and settings.whatsapp_access_token and settings.whatsapp_phone_number_id
    )
    configuration_error: str | None = None
    if not linked_broadcasts:
        configuration_error = "Link at least one opted-in WhatsApp broadcast to this group first."
    elif not provider_configured:
        configuration_error = (
            "The WhatsApp QR template or Cloud API credentials are not configured."
        )
    elif summary.ready + summary.retryable == 0:
        configuration_error = "There are no new or safely retryable QR codes to send."
    return QrDeliveryPreviewResponse(
        group_id=group.id,
        template_name=template_name or None,
        template_configured=provider_configured,
        linked_broadcast_count=len(linked_broadcasts),
        can_send=configuration_error is None,
        configuration_error=configuration_error,
        message_content=QR_DEFAULT_MESSAGE_CONTENT,
        summary=summary,
        recipients=rows,
    )
