"""Public read-only scope for explicitly selected saved-message previews."""

from __future__ import annotations

import uuid as uuid

from fastapi import APIRouter as APIRouter
from fastapi import Depends as Depends
from fastapi import HTTPException as HTTPException
from fastapi import Response as Response
from sqlalchemy import select as select
from sqlalchemy.ext.asyncio import AsyncSession as AsyncSession

from app.application.use_cases.whatsapp.welcome_policy import (
    requires_prior_welcome as requires_prior_welcome,
)
from app.domain.entities.entities import User as User
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel as WhatsAppBroadcastGroupModel,
)
from app.infrastructure.database.models import (
    WhatsAppBroadcastRecipientModel as WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.database.session import get_db_session as get_db_session
from app.infrastructure.repositories.passport_roster_resolution_repository import (
    active_replacement_phone_numbers_for_broadcast as active_replacement_phone_numbers_for_broadcast,
)
from app.infrastructure.whatsapp.broadcast_welcome import (
    broadcast_welcome_states as broadcast_welcome_states,
)
from app.infrastructure.whatsapp.phone_welcome import WELCOME_REQUIRED as WELCOME_REQUIRED
from app.infrastructure.whatsapp.phone_welcome import (
    welcome_states_for_phones as welcome_states_for_phones,
)
from app.presentation.api.v1.routes.whatsapp_archive_policy import (
    require_active_broadcast as require_active_broadcast,
)
from app.presentation.api.v1.routes.whatsapp_bulk_resend_composer import (
    SavedResendSnapshot as SavedResendSnapshot,
)
from app.presentation.api.v1.routes.whatsapp_bulk_resend_composer import (
    resolve_saved_resend_snapshot as resolve_saved_resend_snapshot,
)
from app.presentation.api.v1.routes.whatsapp_bulk_resend_composer import (
    validate_bulk_resend_edits as validate_bulk_resend_edits,
)
from app.presentation.api.v1.routes.whatsapp_bulk_resend_inputs import BulkResendInputs
from app.presentation.api.v1.routes.whatsapp_bulk_resend_preview_values import (
    BulkPreviewSelection,
    collect_bulk_preview_snapshots,
    project_bulk_resend_preview,
)
from app.presentation.api.v1.routes.whatsapp_bulk_resend_support import (
    recipient_skip_reason as recipient_skip_reason,
)
from app.presentation.api.v1.routes.whatsapp_bulk_resend_support import (
    selection_delivery_maps as selection_delivery_maps,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_ACCEPTED_STATUSES as WHATSAPP_ACCEPTED_STATUSES,
)
from app.presentation.api.v1.routes.whatsapp_shared import WHATSAPP_ROLES as WHATSAPP_ROLES
from app.presentation.api.v1.routes.whatsapp_shared import _agency_filter as _agency_filter
from app.presentation.api.v1.routes.whatsapp_shared import _clean_name as _clean_name
from app.presentation.api.v1.routes.whatsapp_welcome_view import (
    welcome_resend_skip_reason as welcome_resend_skip_reason,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppBulkResendPreviewRequest as WhatsAppBulkResendPreviewRequest,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppBulkResendPreviewResponse as WhatsAppBulkResendPreviewResponse,
)
from app.presentation.dependencies.auth import require_role as require_role

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
    require_active_broadcast(group)
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
    selection = BulkPreviewSelection(group, recipients, by_id)
    inputs = BulkResendInputs(edits, states, active_statuses, sources, replaced)
    eligible = await collect_bulk_preview_snapshots(session, body, selection, inputs)
    return project_bulk_resend_preview(body, response, selection, states, eligible)
