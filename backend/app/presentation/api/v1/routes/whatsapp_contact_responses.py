"""Contact previews and delivery-aware private recipient projections."""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping

from fastapi import HTTPException, status

from app.application.use_cases.whatsapp.welcome_policy import requires_prior_welcome
from app.infrastructure.database.models import (
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastRejectedContactModel,
    WhatsAppBroadcastSupportContactModel,
    WhatsAppRecipientMessageStateModel,
)
from app.presentation.api.v1.routes.whatsapp_contact_values import (
    MAX_WHATSAPP_REJECTED_ROWS,
    _clean_required_name,
    _validated_rejection_code,
)
from app.presentation.api.v1.routes.whatsapp_delivery_support import (
    WHATSAPP_ACCEPTED_STATUSES,
    WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES,
    WHATSAPP_SUPPRESSED_STATUSES,
)
from app.presentation.api.v1.routes.whatsapp_imported_fields import (
    _matching_field_options,
    _merge_imported_field_keys,
    _safe_imported_fields,
)
from app.presentation.api.v1.routes.whatsapp_recipient_inputs import _normalized_recipient_inputs
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppContactPreviewRecipient,
    WhatsAppContactPreviewRejectedRow,
    WhatsAppContactPreviewResponse,
    WhatsAppContactRejectionCode,
    WhatsAppMergedContactResponse,
    WhatsAppRecipientInput,
    WhatsAppRecipientMessageStatusResponse,
    WhatsAppRecipientResponse,
    WhatsAppRejectedContactResponse,
    WhatsAppSupportContactResponse,
)


def _excel_contact_preview_response(
    contacts: list[WhatsAppRecipientInput],
    rejected_rows: list[WhatsAppContactPreviewRejectedRow] | None = None,
    *,
    rejected_count: int | None = None,
    available_field_keys: Iterable[object] = (),
) -> WhatsAppContactPreviewResponse:
    all_rejected_rows = rejected_rows or []
    total_rejected = len(all_rejected_rows) if rejected_count is None else rejected_count
    counts: dict[WhatsAppContactRejectionCode, int] = {}
    if total_rejected == len(all_rejected_rows):
        for row in all_rejected_rows:
            counts[row.reason_code] = counts.get(row.reason_code, 0) + 1
    rejected_rows = all_rejected_rows[:MAX_WHATSAPP_REJECTED_ROWS]
    if not contacts and total_rejected == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No recipients were found. Include name and phone/WhatsApp "
                "columns with at least one contact."
            ),
        )

    normalized_contacts = _normalized_recipient_inputs(contacts) if contacts else {}
    recipients = [
        WhatsAppContactPreviewRecipient(
            name=_clean_required_name(contact.name, "Recipient name"),
            phone_number=normalized_phone,
            imported_fields=contact.imported_fields,
        )
        for normalized_phone, contact in normalized_contacts.items()
    ]
    return WhatsAppContactPreviewResponse(
        recipient_count=len(recipients),
        accepted_count=len(recipients),
        recipients=recipients,
        rejected_count=total_rejected,
        rejected_counts=counts,
        rejected_rows=rejected_rows,
        rejected_rows_truncated=total_rejected > len(rejected_rows),
        omitted_rejected_count=max(0, total_rejected - len(rejected_rows)),
        available_matching_fields=_matching_field_options(
            _merge_imported_field_keys(
                declared_keys=available_field_keys,
                imported_fields=[
                    *(contact.imported_fields for contact in contacts),
                    *(row.imported_fields for row in rejected_rows),
                ],
            )
        ),
    )


def _recipient_response(
    model: WhatsAppBroadcastRecipientModel,
    states: list[WhatsAppRecipientMessageStateModel] | None = None,
    resend_statuses: dict[str, str] | None = None,
    merged_contacts: list[WhatsAppMergedContactResponse] | None = None,
    *,
    phone_welcome_statuses: Mapping[uuid.UUID, str | None] | None = None,
) -> WhatsAppRecipientResponse:
    ordered_states = sorted(states or [], key=lambda state: state.message_type)
    latest_resend_statuses = resend_statuses or {}
    welcome_status = (
        phone_welcome_statuses.get(model.id)
        if phone_welcome_statuses is not None
        else next(
            (state.status for state in ordered_states if state.message_type == "welcome"), None
        )
    )
    from app.infrastructure.whatsapp.phone_welcome import welcome_required_reason

    welcome_reason = welcome_required_reason(welcome_status)
    return WhatsAppRecipientResponse(
        id=model.id,
        name=model.name,
        phone_number=model.phone_number,
        normalized_phone_number=model.normalized_phone_number,
        imported_fields=dict(getattr(model, "imported_fields", {}) or {}),
        is_source_managed=bool(getattr(model, "is_source_managed", False)),
        merged_contacts=merged_contacts or [],
        welcome_status=welcome_status,
        welcome_delivered=welcome_reason is None,
        welcome_required_reason=welcome_reason,
        sent_message_types=[
            state.message_type
            for state in ordered_states
            if state.status in WHATSAPP_ACCEPTED_STATUSES
        ],
        message_statuses=[
            WhatsAppRecipientMessageStatusResponse(
                message_type=state.message_type,
                status=state.status,
                already_sent=state.status in WHATSAPP_ACCEPTED_STATUSES,
                send_suppressed=state.status in WHATSAPP_SUPPRESSED_STATUSES,
                latest_resend_status=latest_resend_statuses.get(state.message_type),
                resend_blocked=(
                    latest_resend_statuses.get(state.message_type)
                    in WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES
                    or (
                        state.message_type == "welcome"
                        and welcome_status in WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES
                    )
                    or (
                        state.message_type == "welcome"
                        and state.status in WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES
                    )
                    or (
                        state.message_type == "group_invite"
                        and state.status in WHATSAPP_SUPPRESSED_STATUSES
                    )
                    or (requires_prior_welcome(state.message_type) and welcome_reason is not None)
                ),
                submitted_at=state.submitted_at,
                status_updated_at=state.status_updated_at,
            )
            for state in ordered_states
        ],
    )


def _rejected_contact_response(
    model: WhatsAppBroadcastRejectedContactModel,
) -> WhatsAppRejectedContactResponse:
    return WhatsAppRejectedContactResponse(
        id=model.id,
        source_file_name=model.source_file_name,
        sheet_name=model.sheet_name,
        row_number=model.row_number,
        raw_name=model.raw_name,
        raw_phone_number=model.raw_phone_number,
        imported_fields=_safe_imported_fields(model.imported_fields),
        reason_code=_validated_rejection_code(model.reason_code),
        reason=model.reason,
        created_at=model.created_at,
    )


def _support_contact_response(
    model: WhatsAppBroadcastSupportContactModel,
) -> WhatsAppSupportContactResponse:
    return WhatsAppSupportContactResponse(
        id=model.id,
        name=model.name,
        phone_number=model.phone_number,
        normalized_phone_number=model.normalized_phone_number,
    )
