"""Response assembly for broadcast list rows."""

from __future__ import annotations

from app.infrastructure.database.models import WhatsAppBroadcastGroupModel
from app.presentation.api.v1.routes.whatsapp_shared import _matching_field_options
from app.presentation.api.v1.schemas.whatsapp_schemas import WhatsAppBroadcastGroupResponse


def broadcast_group_list_response(
    group: WhatsAppBroadcastGroupModel, recipient_count: int | None,
    rejected_count: int | None, has_import_only_source: bool, source_count: int | None,
) -> WhatsAppBroadcastGroupResponse:
    return WhatsAppBroadcastGroupResponse(
        id=group.id,
        name=group.name,
        organizing_company_name=group.organizing_company_name,
        archived_at=group.archived_at,
        is_archived=group.archived_at is not None,
        has_import_only_source=bool(has_import_only_source),
        source_contact_count=int(source_count or 0),
        recipient_count=int(recipient_count or 0),
        total_contact_count=(int(recipient_count or 0) + int(rejected_count or 0)),
        recipient_opt_in_confirmed=group.recipient_opt_in_confirmed_at is not None,
        available_matching_fields=_matching_field_options(
            getattr(group, "imported_field_keys", [])
        ),
        created_at=group.created_at,
        updated_at=group.updated_at,
    )
