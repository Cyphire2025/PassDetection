"""Review an original welcome against current submitted traveller numbers."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.message_templates import validate_template_parameters
from app.core.config.settings import get_settings
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    WhatsAppBroadcastGroupModel,
)
from app.infrastructure.whatsapp.phone_welcome import welcome_states_for_phones
from app.infrastructure.whatsapp.traveller_destinations import load_traveller_destinations
from app.presentation.api.v1.routes.whatsapp_composer_support import (
    _latest_composer_snapshot,
    _template_snapshot_from_log,
)
from app.presentation.api.v1.schemas.traveller_welcome_schemas import (
    TravellerWelcomePreview,
    TravellerWelcomeRecipient,
    TravellerWelcomeSource,
    TravellerWelcomeSummary,
)

WELCOME_CONFIRMED = frozenset({"delivered", "read"})
WELCOME_PENDING = frozenset({"queued", "processing", "submitted", "sent", "delivery_unknown"})


@dataclass(frozen=True, slots=True)
class TravellerWelcomeContent:
    template_name: str
    rendered_message: str
    header_parameters: list[str]
    body_parameters: list[str]


async def linked_welcome_sources(
    session: AsyncSession, *, group: ClientGroupModel, lock: bool = False,
) -> list[WhatsAppBroadcastGroupModel]:
    statement = select(WhatsAppBroadcastGroupModel).join(
        ClientGroupWhatsAppBroadcastLinkModel,
        ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id == WhatsAppBroadcastGroupModel.id,
    ).where(
        ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group.id,
        ClientGroupWhatsAppBroadcastLinkModel.agency_id == group.agency_id,
        WhatsAppBroadcastGroupModel.agency_id == group.agency_id,
        WhatsAppBroadcastGroupModel.recipient_opt_in_confirmed_at.is_not(None),
    ).order_by(WhatsAppBroadcastGroupModel.id)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return list((await session.scalars(statement)).all())


async def _original_welcome_content(
    session: AsyncSession, source_id: uuid.UUID | None, header_image_id: str | None = None,
) -> TravellerWelcomeContent | None:
    if source_id is None:
        return None
    snapshot = await _latest_composer_snapshot(
        session, group_id=source_id, message_type="welcome", include_explicit_resends=True,
    )
    if snapshot is None:
        return None
    headers, parameters = _template_snapshot_from_log(snapshot.log)
    if header_image_id:
        headers = [header_image_id]
    try:
        validate_template_parameters(
            message_type="welcome", header_parameters=headers, body_parameters=parameters,
        )
    except ValueError:
        return None
    if not snapshot.log.template_name or not snapshot.log.rendered_message:
        return None
    return TravellerWelcomeContent(
        template_name=snapshot.log.template_name,
        rendered_message=snapshot.log.rendered_message,
        header_parameters=headers,
        body_parameters=parameters,
    )


def welcome_preview_fingerprint(
    *, group: ClientGroupModel, source_id: uuid.UUID | None,
    content: TravellerWelcomeContent | None, recipients: list[TravellerWelcomeRecipient],
) -> str:
    """Fence contact/roster and template changes, without invalidating on receipts."""
    value = {
        "agency": str(group.agency_id), "group": str(group.id), "source": str(source_id),
        "template": content.template_name if content else None,
        "header": content.header_parameters if content else [],
        "body": content.body_parameters if content else [],
        "contacts": sorted((row.phone_number or "", sorted(map(str, row.passenger_ids)))
                           for row in recipients),
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


async def build_traveller_welcome_preview(
    session: AsyncSession, *, group: ClientGroupModel,
    source_broadcast_id: uuid.UUID | None = None, lock: bool = False,
    header_image_id: str | None = None,
) -> tuple[TravellerWelcomePreview, TravellerWelcomeContent | None]:
    sources = await linked_welcome_sources(session, group=group, lock=lock)
    selected = next((source for source in sources if source.id == source_broadcast_id), None)
    if source_broadcast_id is not None and selected is None:
        raise HTTPException(409, "The selected welcome source is no longer linked and opted in.")
    selected = selected or (sources[0] if sources else None)
    content = await _original_welcome_content(
        session, selected.id if selected else None, header_image_id,
    )
    if content is None and source_broadcast_id is None:
        for source in sources[1:]:
            candidate = await _original_welcome_content(session, source.id, header_image_id)
            if candidate is not None:
                selected, content = source, candidate
                break
    destinations = await load_traveller_destinations(
        session, agency_id=group.agency_id, group_id=group.id, lock=lock,
    )
    phones = {row.phone_number for row in destinations if row.phone_number}
    states = await welcome_states_for_phones(session, agency_id=group.agency_id, phones=phones)
    settings = get_settings()
    configured = bool(content and settings.whatsapp_access_token and settings.whatsapp_phone_number_id)
    error = None
    if not selected:
        error = "Link an opted-in WhatsApp broadcast containing the original welcome first."
    elif not content:
        error = (
            "No reusable welcome is available with these template parameters. Select the "
            "broadcast containing the original welcome. Legacy text welcomes must retain "
            "their original format without a replacement image."
        )
    elif not configured:
        error = "WhatsApp Cloud API credentials are not configured."
    contacts: dict[str, TravellerWelcomeRecipient] = {}
    for destination in destinations:
        key = destination.phone_number or str(destination.passenger_id)
        if key not in contacts:
            phone = destination.phone_number
            state = states.get(phone, "required") if phone else "blocked"
            reason = destination.reason
            if state in WELCOME_PENDING:
                reason = "Waiting for WhatsApp to confirm welcome delivery. Documents remain blocked."
            elif state == "failed":
                reason = "The previous welcome failed. Review and retry it."
            elif state in WELCOME_CONFIRMED:
                reason = "Welcome already delivered to this number. It will not be sent again."
            contacts[key] = TravellerWelcomeRecipient(
                phone_number=phone, status=state, reason=reason or error,
                eligible=bool(phone and configured and state in {"required", "failed"}),
                rendered_message=content.rendered_message if content else None,
            )
        contacts[key].passenger_ids.append(destination.passenger_id)
        contacts[key].passenger_names.append(destination.passenger_name)
    recipients = list(contacts.values())
    summary = TravellerWelcomeSummary(
        total_numbers=len(phones),
        needs_welcome=sum(row.status in {"required", "failed"} for row in recipients),
        already_welcomed=sum(row.status in WELCOME_CONFIRMED for row in recipients),
        in_progress=sum(row.status in WELCOME_PENDING for row in recipients),
        blocked=sum(row.status == "blocked" for row in recipients),
    )
    preview = TravellerWelcomePreview(
        group_id=group.id,
        preview_token=welcome_preview_fingerprint(
            group=group, source_id=selected.id if selected else None,
            content=content, recipients=recipients,
        ),
        source_broadcast_id=selected.id if selected else None,
        source_broadcast_name=selected.name if selected else None,
        sources=[TravellerWelcomeSource(id=source.id, name=source.name) for source in sources],
        template_name=content.template_name if content else None,
        template_configured=configured, can_send=any(row.eligible for row in recipients),
        configuration_error=error, summary=summary, recipients=recipients,
        poll_after_seconds=5 if summary.in_progress else None,
    )
    return preview, content
