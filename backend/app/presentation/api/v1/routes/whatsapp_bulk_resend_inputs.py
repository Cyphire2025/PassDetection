"""Fresh eligibility and saved-message inputs before any selected resend claim."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.welcome_policy import requires_prior_welcome
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.repositories.passport_roster_resolution_repository import (
    active_replacement_phone_numbers_for_broadcast,
)
from app.infrastructure.whatsapp.phone_welcome import (
    WELCOME_DELIVERED_STATUSES,
    WELCOME_REQUIRED,
    sync_failed_broadcast_welcomes,
    welcome_states_for_phones,
)
from app.presentation.api.v1.routes.whatsapp_bulk_resend_composer import (
    BulkResendEdits,
    validate_bulk_resend_edits,
)
from app.presentation.api.v1.routes.whatsapp_bulk_resend_support import (
    expire_stale_explicit_claims,
    selection_delivery_maps,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import WhatsAppBulkResendRequest


@dataclass(frozen=True)
class BulkResendInputs:
    edits: BulkResendEdits
    states: dict[uuid.UUID, WhatsAppRecipientMessageStateModel]
    active_statuses: dict[uuid.UUID, set[str]]
    sources: dict[uuid.UUID, WhatsAppMessageLogModel]
    replaced_phones: set[str]


async def read_bulk_resend_inputs(
    session: AsyncSession,
    group: WhatsAppBroadcastGroupModel,
    body: WhatsAppBulkResendRequest,
    recipients: list[WhatsAppBroadcastRecipientModel],
) -> BulkResendInputs:
    edits = await validate_bulk_resend_edits(session, group=group, body=body)
    if requires_prior_welcome(body.message_type):
        welcome_states = await welcome_states_for_phones(
            session,
            agency_id=group.agency_id,
            broadcast_group_id=group.id,
            phones=[recipient.normalized_phone_number for recipient in recipients],
        )
        if any(
            welcome_states.get(recipient.normalized_phone_number) not in WELCOME_DELIVERED_STATUSES
            for recipient in recipients
        ):
            raise HTTPException(status_code=409, detail=WELCOME_REQUIRED)
    await expire_stale_explicit_claims(session, group_id=group.id, body=body)
    if body.message_type == "welcome":
        await sync_failed_broadcast_welcomes(session, broadcast_group_id=group.id)
    states, active_statuses, sources = await selection_delivery_maps(
        session, group_id=group.id, body=body
    )
    replaced_phones = await active_replacement_phone_numbers_for_broadcast(
        session, broadcast_group_id=group.id, agency_id=group.agency_id
    )
    return BulkResendInputs(edits, states, active_statuses, sources, replaced_phones)
