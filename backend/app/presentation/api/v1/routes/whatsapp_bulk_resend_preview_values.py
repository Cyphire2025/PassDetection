"""Collect eligible saved previews and project their existing private response."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.welcome_policy import requires_prior_welcome
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.whatsapp.broadcast_welcome import broadcast_welcome_states
from app.infrastructure.whatsapp.phone_welcome import WELCOME_REQUIRED, welcome_states_for_phones
from app.presentation.api.v1.routes.whatsapp_bulk_resend_composer import (
    SavedResendSnapshot,
    resolve_saved_resend_snapshot,
)
from app.presentation.api.v1.routes.whatsapp_bulk_resend_inputs import BulkResendInputs
from app.presentation.api.v1.routes.whatsapp_bulk_resend_support import recipient_skip_reason
from app.presentation.api.v1.routes.whatsapp_shared import WHATSAPP_ACCEPTED_STATUSES, _clean_name
from app.presentation.api.v1.routes.whatsapp_welcome_view import welcome_resend_skip_reason
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppBulkResendPreviewRequest,
    WhatsAppBulkResendPreviewResponse,
)


@dataclass(frozen=True)
class BulkPreviewSelection:
    group: WhatsAppBroadcastGroupModel
    recipients: list[WhatsAppBroadcastRecipientModel]
    by_id: dict[uuid.UUID, WhatsAppBroadcastRecipientModel]


@dataclass(frozen=True)
class BulkPreviewSnapshots:
    snapshots: dict[uuid.UUID, SavedResendSnapshot]
    reasons: list[str]


async def collect_bulk_preview_snapshots(
    session: AsyncSession,
    body: WhatsAppBulkResendPreviewRequest,
    selection: BulkPreviewSelection,
    inputs: BulkResendInputs,
) -> BulkPreviewSnapshots:
    group = selection.group
    recipients = selection.recipients
    by_id = selection.by_id
    edits = inputs.edits
    states = inputs.states
    active_statuses = inputs.active_statuses
    sources = inputs.sources
    replaced = inputs.replaced_phones
    snapshots: dict[uuid.UUID, SavedResendSnapshot] = {}
    reasons: list[str] = []
    phone_states = (
        await welcome_states_for_phones(
            session,
            agency_id=group.agency_id,
            broadcast_group_id=group.id,
            phones=[recipient.normalized_phone_number for recipient in recipients],
        )
        if body.message_type == "welcome" or requires_prior_welcome(body.message_type)
        else {}
    )
    active_welcomes = (
        await broadcast_welcome_states(
            session,
            agency_id=group.agency_id,
            broadcast_group_id=group.id,
            phones=[recipient.normalized_phone_number for recipient in recipients],
            active_only=True,
        )
        if body.message_type == "welcome"
        else {}
    )
    for recipient_id in body.recipient_ids:
        recipient = by_id[recipient_id]
        reason = recipient_skip_reason(
            message_type=body.message_type,
            recipient=recipient,
            state=states.get(recipient.id),
            active_statuses=active_statuses.get(recipient.id, set()),
            replaced_phones=replaced,
        )
        explicit_welcome_resend = body.message_type == "welcome" and (
            states.get(recipient.id) is not None
            and states[recipient.id].status in WHATSAPP_ACCEPTED_STATUSES
        )
        reason = reason or welcome_resend_skip_reason(
            body.message_type,
            (active_welcomes if explicit_welcome_resend else phone_states).get(
                recipient.normalized_phone_number
            ),
        )
        if reason is None:
            source = sources.get(recipient.id)
            if source is None:
                reason = "skipped_no_saved_message"
            else:
                try:
                    snapshots[recipient.id] = resolve_saved_resend_snapshot(
                        source, edits, preview=True
                    )
                except (ValueError, IndexError):
                    reason = "skipped_no_saved_message"
        if reason is not None:
            reasons.append(reason)
    return BulkPreviewSnapshots(snapshots, reasons)


def project_bulk_resend_preview(
    body: WhatsAppBulkResendPreviewRequest,
    response: Response,
    selection: BulkPreviewSelection,
    states: dict[uuid.UUID, WhatsAppRecipientMessageStateModel],
    eligible: BulkPreviewSnapshots,
) -> WhatsAppBulkResendPreviewResponse:
    recipients = selection.recipients
    by_id = selection.by_id
    snapshots = eligible.snapshots
    reasons = eligible.reasons
    if not snapshots:
        raise HTTPException(
            status_code=409,
            detail="No eligible saved messages are available for this selection. Refresh the recipient list before trying again.",
        )
    preview_id = body.preview_recipient_id or next(iter(snapshots))
    if preview_id not in snapshots:
        raise HTTPException(
            status_code=409,
            detail="This recipient is currently unavailable for resend. Choose another selected recipient to preview.",
        )
    snapshot = snapshots[preview_id]
    person = by_id[preview_id]
    passport = body.message_type == "passport_link"
    response.headers["Cache-Control"] = "private, no-store"
    return WhatsAppBulkResendPreviewResponse(
        message_type=body.message_type,
        template_name=snapshot.template_name,
        recipient_id=person.id,
        recipient_name=_clean_name(person.name) or "Guest",
        recipient_count=len(recipients),
        eligible_recipient_count=len(snapshots),
        already_sent_count=(
            reasons.count("skipped_already_sent")
            if body.message_type == "group_invite"
            else sum(
                states[recipient_id].status in WHATSAPP_ACCEPTED_STATUSES
                for recipient_id in snapshots
            )
        ),
        in_progress_count=reasons.count("skipped_in_progress"),
        uncertain_recipient_count=reasons.count("skipped_delivery_unknown"),
        welcome_required_count=reasons.count("skipped_welcome_required"),
        welcome_required_reason=WELCOME_REQUIRED if "skipped_welcome_required" in reasons else None,
        passport_intro=snapshot.parameters[0] if passport else None,
        passport_link=snapshot.parameters[1] if passport else None,
        group_invite_link=snapshot.parameters[1] if body.message_type == "group_invite" else None,
        message_content=snapshot.parameters[2] if passport else snapshot.parameters[0],
        header_image_id=snapshot.header_parameters[0] if snapshot.header_parameters else None,
        content_source="latest_recipient",
        rendered_message=snapshot.rendered_message,
        header_parameter_values=snapshot.header_parameters,
        parameter_values=snapshot.parameters,
        selected=len(recipients),
        missing_header_image_count=sum(
            body.message_type == "group_invite" and not item.header_parameters
            for item in snapshots.values()
        ),
        eligible_recipient_ids=list(snapshots),
        skipped_no_saved_message=reasons.count("skipped_no_saved_message"),
        skipped_replaced=reasons.count("skipped_replaced"),
        skipped_ineligible=reasons.count("skipped_ineligible"),
        skipped_in_progress=reasons.count("skipped_in_progress"),
        skipped_delivery_unknown=reasons.count("skipped_delivery_unknown"),
    )
