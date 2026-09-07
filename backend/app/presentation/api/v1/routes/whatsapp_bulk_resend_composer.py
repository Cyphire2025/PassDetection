"""Shared editable saved-message rendering for selected resend preview and send."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.message_templates import (
    AUTOMATED_NOTICE,
    GREETING,
    STATIC_TEMPLATE_HEADER,
    format_support_contacts,
    render_message,
    validate_template_parameters,
)
from app.infrastructure.database.models import WhatsAppBroadcastGroupModel, WhatsAppMessageLogModel
from app.presentation.api.v1.routes.whatsapp_scope import _configured_template_name
from app.presentation.api.v1.routes.whatsapp_shared import (
    _as_message_type,
    _resolve_send_header_image,
    _resolve_send_message_content,
    _resolve_send_passport_intro,
    _select_support_contacts,
    _support_contacts_for_group,
    _template_snapshot_from_log,
    _validate_passport_link,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import WhatsAppBulkResendDraft


@dataclass(frozen=True)
class BulkResendEdits:
    message_content: str | None = None
    passport_intro: str | None = None
    header_image_id: str | None = None
    support_block: str | None = None
    media_template_name: str | None = None


@dataclass(frozen=True)
class SavedResendSnapshot:
    template_name: str
    rendered_message: str
    header_parameters: list[str]
    parameters: list[str]


async def validate_bulk_resend_edits(
    session: AsyncSession, *, group: WhatsAppBroadcastGroupModel, body: WhatsAppBulkResendDraft
) -> BulkResendEdits | None:
    """Validate the entire draft before any delivery claim or stale-state mutation."""
    if all(
        value is None
        for value in (
            body.message_content,
            body.passport_intro,
            body.header_image_id,
            body.support_contact_ids,
        )
    ):
        return None
    if body.message_type == "welcome" and (
        body.passport_intro is not None or body.support_contact_ids is not None
    ):
        raise HTTPException(
            status_code=400,
            detail="Passport introduction and support edits are only available for Passport Link messages",
        )
    content = (
        _resolve_send_message_content(
            body.message_type, body.message_content, group_name=group.name
        )
        if body.message_content is not None
        else None
    )
    intro = (
        _resolve_send_passport_intro(body.passport_intro, group_name=group.name)
        if body.passport_intro is not None
        else None
    )
    header = (
        _resolve_send_header_image(body.message_type, body.header_image_id, resend=True)
        if body.header_image_id is not None
        else None
    )
    template_name = None
    if header is not None:
        template_name = _configured_template_name(body.message_type).strip()
        if not template_name:
            raise HTTPException(
                status_code=503, detail="The WhatsApp image template is not configured"
            )
    support_block = None
    if body.support_contact_ids is not None:
        contacts = _select_support_contacts(
            await _support_contacts_for_group(session, group.id),
            body.support_contact_ids,
            message_type=body.message_type,
        )
        support_block = format_support_contacts(
            [(contact.name, contact.phone_number) for contact in contacts]
        )
    return BulkResendEdits(content, intro, header, support_block, template_name)


def resolve_saved_resend_snapshot(
    source: WhatsAppMessageLogModel, edits: BulkResendEdits | None = None
) -> SavedResendSnapshot:
    """Apply only explicit edits; a passport link always comes from this source row."""
    header, parameters = _template_snapshot_from_log(source)
    if not source.template_name or not source.template_name.strip() or not source.rendered_message:
        raise ValueError("The saved template or rendered message is missing")
    message_type = _as_message_type(source.message_type)
    if message_type == "passport_link":
        try:
            _validate_passport_link(parameters[1])
        except HTTPException as exc:
            raise ValueError("The saved passport link is invalid") from exc
    if edits is None:
        return SavedResendSnapshot(
            source.template_name, source.rendered_message, header, parameters
        )

    template_name = source.template_name
    if edits.header_image_id is not None:
        header = [edits.header_image_id]
        if not edits.media_template_name:
            raise ValueError("An edited image needs the configured media template")
        template_name = edits.media_template_name
        if message_type == "welcome":
            parameters = parameters[:1]
    content_index = 0 if message_type == "welcome" else 2
    if edits.message_content is not None:
        parameters[content_index] = edits.message_content
    if message_type == "passport_link":
        if edits.passport_intro is not None:
            parameters[0] = edits.passport_intro
        if edits.support_block is not None:
            parameters[3] = edits.support_block
    validate_template_parameters(
        message_type=message_type, header_parameters=header, body_parameters=parameters
    )
    if message_type == "welcome" and not header and len(parameters) == 2:
        # Legacy text welcome templates include their own saved support block.
        rendered = (
            f"{STATIC_TEMPLATE_HEADER}\n\n{GREETING}\n\n{parameters[0]}\n\n{AUTOMATED_NOTICE}\n\n"
            f"For assistance, please contact:\n{parameters[1]}\n\nRegards,\nTeam Global Connect Travels"
        )
    else:
        rendered = render_message(
            message_type=message_type,
            group_name="",  # Every varying value is explicit; never insert current group defaults.
            support_contacts=parameters[3] if message_type == "passport_link" else "",
            message_content=parameters[content_index],
            passport_link=parameters[1] if message_type == "passport_link" else None,
            passport_intro=parameters[0] if message_type == "passport_link" else None,
        )
    return SavedResendSnapshot(template_name, rendered, header, parameters)
