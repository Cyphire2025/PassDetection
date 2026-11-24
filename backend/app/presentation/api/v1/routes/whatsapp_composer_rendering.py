"""Render the current message and its exact approved template parameters."""

from __future__ import annotations

from app.application.use_cases.whatsapp.message_templates import (
    WhatsAppMessageType,
    format_support_contacts,
    render_message,
    template_header_parameters,
    template_parameters,
)
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastSupportContactModel,
)
from app.presentation.api.v1.routes.whatsapp_composer_content import (
    _as_message_type,
    _resolve_message_content,
    _resolve_message_links,
    _resolve_passport_intro,
)
from app.presentation.api.v1.routes.whatsapp_contact_support import _clean_name
from app.presentation.api.v1.schemas.whatsapp_schemas import WhatsAppSendRequest


def _message_values(
    *,
    group: WhatsAppBroadcastGroupModel,
    recipient: WhatsAppBroadcastRecipientModel,
    support_contacts: list[WhatsAppBroadcastSupportContactModel],
    body: WhatsAppSendRequest,
    preview: bool = False,
) -> tuple[
    WhatsAppMessageType,
    str | None,
    str | None,
    str,
    str,
    str,
    list[str],
    list[str],
]:
    message_type = _as_message_type(body.message_type)
    message_content = _resolve_message_content(
        message_type,
        body.message_content,
        group_name=group.name,
    )
    passport_intro = (
        _resolve_passport_intro(body.passport_intro, group_name=group.name)
        if message_type == "passport_link"
        else None
    )
    passport_link, group_invite_link = _resolve_message_links(body, preview=preview)
    recipient_name = _clean_name(recipient.name) or "Guest"
    support_block = format_support_contacts(
        [(contact.name, contact.phone_number) for contact in support_contacts]
    )
    rendered = render_message(
        message_type=message_type,
        group_name=group.name,
        support_contacts=support_block,
        message_content=message_content,
        passport_link=passport_link,
        passport_intro=passport_intro,
        group_invite_link=group_invite_link,
    )
    header_parameters = template_header_parameters(
        message_type=message_type,
        header_image_id=body.header_image_id,
    )
    parameters = template_parameters(
        message_type=message_type,
        group_name=group.name,
        support_contacts=support_block,
        message_content=message_content,
        passport_link=passport_link,
        passport_intro=passport_intro,
        group_invite_link=group_invite_link,
    )
    return (
        message_type,
        passport_intro,
        passport_link,
        message_content,
        recipient_name,
        rendered,
        header_parameters,
        parameters,
    )


# Keep existing public imports and pickle identities.
_message_values.__module__ = "app.presentation.api.v1.routes.whatsapp_composer_support"
