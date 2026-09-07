"""Read-only per-recipient preview of an explicitly selected resend draft."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.passport_roster_resolution_repository import (
    active_replacement_phone_numbers_for_broadcast,
)
from app.presentation.api.v1.routes.whatsapp_bulk_resend_composer import (
    SavedResendSnapshot,
    resolve_saved_resend_snapshot,
    validate_bulk_resend_edits,
)
from app.presentation.api.v1.routes.whatsapp_bulk_resend_support import (
    recipient_skip_reason,
    selection_delivery_maps,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_ACCEPTED_STATUSES,
    WHATSAPP_ROLES,
    _agency_filter,
    _clean_name,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppBulkResendPreviewRequest,
    WhatsAppBulkResendPreviewResponse,
)
from app.presentation.dependencies.auth import require_role

router = APIRouter()


@router.post(
    "/groups/{group_id}/recipients/resend/preview",
    response_model=WhatsAppBulkResendPreviewResponse,
)
async def preview_selected_recipient_messages(
    group_id: uuid.UUID,
    body: WhatsAppBulkResendPreviewRequest,
    response: Response,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppBulkResendPreviewResponse:
    group = (
        await session.execute(
            select(WhatsAppBroadcastGroupModel).where(
                WhatsAppBroadcastGroupModel.id == group_id, *_agency_filter(current_user)
            )
        )
    ).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="WhatsApp broadcast group not found")
    if (
        body.preview_recipient_id is not None
        and body.preview_recipient_id not in body.recipient_ids
    ):
        raise HTTPException(
            status_code=404, detail="Preview recipient is not in the selected recipients"
        )
    recipients = list(
        (
            await session.execute(
                select(WhatsAppBroadcastRecipientModel).where(
                    WhatsAppBroadcastRecipientModel.broadcast_group_id == group.id,
                    WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
                    WhatsAppBroadcastRecipientModel.id.in_(body.recipient_ids),
                    WhatsAppBroadcastRecipientModel.removed_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    by_id = {recipient.id: recipient for recipient in recipients}
    if set(by_id) != set(body.recipient_ids):
        raise HTTPException(
            status_code=404,
            detail="One or more selected recipients are unavailable in this WhatsApp broadcast",
        )
    edits = await validate_bulk_resend_edits(session, group=group, body=body)
    states, active_statuses, sources = await selection_delivery_maps(
        session, group_id=group.id, body=body, lock_states=False
    )
    replaced = await active_replacement_phone_numbers_for_broadcast(
        session, broadcast_group_id=group.id, agency_id=group.agency_id
    )
    snapshots: dict[uuid.UUID, SavedResendSnapshot] = {}
    reasons: list[str] = []
    for recipient_id in body.recipient_ids:
        recipient = by_id[recipient_id]
        reason = recipient_skip_reason(
            recipient=recipient,
            state=states.get(recipient.id),
            active_statuses=active_statuses.get(recipient.id, set()),
            replaced_phones=replaced,
        )
        if reason is None:
            source = sources.get(recipient.id)
            if source is None:
                reason = "skipped_no_saved_message"
            else:
                try:
                    snapshots[recipient.id] = resolve_saved_resend_snapshot(source, edits)
                except (ValueError, IndexError):
                    reason = "skipped_no_saved_message"
        if reason is not None:
            reasons.append(reason)
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
        already_sent_count=sum(
            states[recipient_id].status in WHATSAPP_ACCEPTED_STATUSES for recipient_id in snapshots
        ),
        in_progress_count=reasons.count("skipped_in_progress"),
        uncertain_recipient_count=reasons.count("skipped_delivery_unknown"),
        passport_intro=snapshot.parameters[0] if passport else None,
        passport_link=snapshot.parameters[1] if passport else None,
        message_content=snapshot.parameters[2] if passport else snapshot.parameters[0],
        header_image_id=snapshot.header_parameters[0] if snapshot.header_parameters else None,
        content_source="latest_recipient",
        rendered_message=snapshot.rendered_message,
        header_parameter_values=snapshot.header_parameters,
        parameter_values=snapshot.parameters,
        selected=len(recipients),
        eligible_recipient_ids=list(snapshots),
        skipped_no_saved_message=reasons.count("skipped_no_saved_message"),
        skipped_replaced=reasons.count("skipped_replaced"),
        skipped_ineligible=reasons.count("skipped_ineligible"),
        skipped_in_progress=reasons.count("skipped_in_progress"),
        skipped_delivery_unknown=reasons.count("skipped_delivery_unknown"),
    )
