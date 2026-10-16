"""Fresh preview of the combined submission and document delivery filters."""

from dataclasses import asdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.document_updates import ACTIVE
from app.application.use_cases.whatsapp.group_updates import GroupUpdateFilters
from app.core.config.settings import get_settings
from app.infrastructure.database.models import ClientGroupModel, WhatsAppMessageLogModel
from app.infrastructure.whatsapp.group_update_audience import load_group_update_audience
from app.infrastructure.whatsapp.template_settings import (
    configured_template_name,
    template_language,
)
from app.presentation.api.v1.routes.document_update_preview import fingerprint
from app.presentation.api.v1.schemas.group_update_schemas import (
    GroupUpdateAudience,
    GroupUpdatePreview,
    GroupUpdateRecipient,
)


async def build_group_update_preview(
    session: AsyncSession, *, group: ClientGroupModel,
    audience: GroupUpdateAudience, lock: bool = False,
) -> GroupUpdatePreview:
    contacts = await load_group_update_audience(
        session, agency_id=group.agency_id, group_id=group.id,
        filters=GroupUpdateFilters(**audience.model_dump()), lock=lock,
    )
    logs = await session.stream(select(
        WhatsAppMessageLogModel.id, WhatsAppMessageLogModel.normalized_phone_number,
        WhatsAppMessageLogModel.status, WhatsAppMessageLogModel.status_updated_at,
        WhatsAppMessageLogModel.document_update_context,
    ).where(
        WhatsAppMessageLogModel.agency_id == group.agency_id,
        WhatsAppMessageLogModel.message_type == "document_update",
        WhatsAppMessageLogModel.document_update_context["group_id"].as_string() == str(group.id),
    ).order_by(WhatsAppMessageLogModel.created_at.desc(), WhatsAppMessageLogModel.id.desc())
      .execution_options(yield_per=500))
    latest: dict[str, tuple[int, str, str, datetime]] = {}
    active = set()
    rank = 0
    async for log_id, phone, status, at, context in logs:
        # Legacy distribution updates carry passenger IDs; group updates also
        # carry audience keys. Preserve history when the submitted phone changes.
        keys = {f"phone:{phone}"} if phone else set()
        keys.update((context or {}).get("audience_keys", []))
        keys.update(f"submission:{identifier}" for identifier in (context or {}).get("passenger_ids", []))
        for key in keys:
            latest.setdefault(key, (rank, str(log_id), status, at))
        if status in ACTIVE:
            active.update(keys)
        rank += 1
    rows = []
    for contact in contacts:
        reason = contact.reason
        keys = {contact.audience_key}
        if contact.phone_number:
            keys.add(f"phone:{contact.phone_number}")
        if keys & active:
            reason = "An earlier update to this number is queued, in progress or has an unknown outcome."
        previous = min((latest[key] for key in keys if key in latest), key=lambda record: record[0], default=None)
        rows.append(GroupUpdateRecipient(
            **{**asdict(contact), "reason": reason}, eligible=reason is None,
            latest_update_status=previous[2] if previous else None,
            latest_update_at=previous[3] if previous else None,
        ))
    template = await configured_template_name(session, "document_update")
    language = template_language("document_update")
    settings = get_settings()
    configured = bool(template and settings.whatsapp_access_token and settings.whatsapp_phone_number_id)
    return GroupUpdatePreview(
        group_id=group.id, audience=audience, template_name=template,
        template_language=language, can_send=configured,
        configuration_error=None if configured else "Configure the update template and WhatsApp credentials first.",
        recipients=rows,
        preview_token=fingerprint({
            "group": group.id, "agency": group.agency_id, "audience": audience.model_dump(),
            "template": template, "language": language,
            "rows": [row.model_dump(mode="json") for row in rows],
            "latest": sorted((key, *record) for key, record in latest.items()),
        }),
    )
