"""Render a selected preview and project its existing eligibility/status response."""

from __future__ import annotations

from typing import Literal, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.whatsapp.template_settings import configured_template_name
from app.presentation.api.v1.routes.whatsapp_composer_preview import (
    PreviewSavedSnapshot,
    PreviewSelection,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_ACCEPTED_STATUSES,
    _merge_composer_snapshot,
    _message_values,
    _preview_message_metadata,
    _recipient_delivery_counts,
    _select_support_contacts,
    _support_contacts_for_group,
)
from app.presentation.api.v1.routes.whatsapp_welcome_view import welcome_preview_values
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppPreviewRequest,
    WhatsAppPreviewResponse,
)


async def build_preview_response(
    session: AsyncSession,
    body: WhatsAppPreviewRequest,
    selection: PreviewSelection,
    saved: PreviewSavedSnapshot,
) -> WhatsAppPreviewResponse:
    group = selection.group
    source_recipients = selection.source_recipients
    audience_resolution = selection.audience_resolution
    recipients = selection.recipients
    recipient = selection.recipient
    message_type = selection.message_type
    snapshot = saved.snapshot
    content_source = saved.content_source
    target_state = saved.target_state
    resolved_body = _merge_composer_snapshot(body, snapshot)
    support_contacts = _select_support_contacts(
        await _support_contacts_for_group(session, group.id),
        resolved_body.support_contact_ids,
        message_type=message_type,
    )
    (
        message_type,
        passport_intro,
        passport_link,
        message_content,
        recipient_name,
        rendered,
        header_parameters,
        parameters,
    ) = _message_values(
        group=group,
        recipient=recipient,
        support_contacts=support_contacts,
        body=resolved_body,
        preview=True,
    )
    if body.resend_recipient_id is not None:
        recipient_count = 1
        eligible_count = 1
        already_sent_count = (
            1
            if target_state is not None and target_state.status in WHATSAPP_ACCEPTED_STATUSES
            else 0
        )
        in_progress_count = 0
        uncertain_count = 0
    else:
        recipient_count = len(source_recipients)
        (
            eligible_count,
            already_sent_count,
            in_progress_count,
            uncertain_count,
        ) = await _recipient_delivery_counts(
            session,
            recipients=recipients,
            message_type=message_type,
            include_previous_recipients=body.include_previous_recipients,
        )
    template_name = await configured_template_name(session, message_type)
    preview_response = WhatsAppPreviewResponse(
        message_type=message_type,
        template_name=template_name,
        recipient_id=recipient.id,
        recipient_name=recipient_name,
        recipient_count=recipient_count,
        audience=cast(Literal["all", "not_submitted"], audience_resolution.audience),
        audience_client_group_id=audience_resolution.client_group_id,
        audience_recipient_count=len(recipients),
        audience_recipient_ids=list(audience_resolution.selectable_recipient_ids),
        excluded_submitted_count=audience_resolution.excluded_submitted_count,
        excluded_needs_review_count=(audience_resolution.excluded_needs_review_count),
        eligible_recipient_count=eligible_count,
        already_sent_count=already_sent_count,
        in_progress_count=in_progress_count,
        uncertain_recipient_count=uncertain_count,
        passport_intro=passport_intro,
        **_preview_message_metadata(resolved_body, header_parameters),
        message_content=message_content,
        content_source=content_source,
        rendered_message=rendered,
        header_parameter_values=header_parameters,
        parameter_values=parameters,
    )
    values = await welcome_preview_values(
        session,
        agency_id=group.agency_id,
        message_type=message_type,
        recipients=recipients,
        selected_recipient_id=body.resend_recipient_id,
        explicit_resend=bool(
            body.resend_recipient_id
            and target_state
            and target_state.status in WHATSAPP_ACCEPTED_STATUSES
        ),
    )
    return preview_response.model_copy(update=values)
