"""Link Operations for upload links; HTTP declarations remain in client_groups."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.contact_normalization import normalize_whatsapp_phone
from app.application.use_cases.whatsapp.group_submission_matching import (
    filter_and_sort_match_rows,
    summarize_match_rows,
)
from app.domain.entities.entities import (
    User,
)
from app.infrastructure.database.models import (
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.repositories.audit_log_repository import (
    AuditLogRepository as AuditLogRepositoryType,
)
from app.presentation.api.v1.routes import (
    client_group_whatsapp_match_support as _whatsapp_match_support,
)
from app.presentation.api.v1.routes.client_group_operation_dependencies import (
    LinkedBroadcastMatchingFieldsForGroup,
    LinkedBroadcastNamesForGroup,
    ReplaceWhatsappLinks,
    RequireManagedGroup,
    RequireViewableGroup,
    RequireWhatsappBroadcastAccess,
    UniqueLinkedRecipientCount,
)
from app.presentation.api.v1.schemas.client_group_schemas import (
    ClientGroupWhatsAppLinksResponse,
    ClientGroupWhatsAppMatchesResponse,
    ReplacementCandidateListResponse,
    ReplacementCandidateResponse,
    ReplaceWhatsAppBroadcastLinksRequest,
)


async def replace_client_group_whatsapp_links(
    link_id: uuid.UUID,
    body: ReplaceWhatsAppBroadcastLinksRequest,
    current_user: User,
    _csrf: None,
    session: AsyncSession,
    *,
    _replace_whatsapp_links: ReplaceWhatsappLinks,
    _require_managed_group: RequireManagedGroup,
    _require_whatsapp_broadcast_access: RequireWhatsappBroadcastAccess,
    _unique_linked_recipient_count: UniqueLinkedRecipientCount,
    AuditLogRepository: type[AuditLogRepositoryType],
) -> ClientGroupWhatsAppLinksResponse:
    _require_whatsapp_broadcast_access(current_user)
    group = await _require_managed_group(session, current_user, link_id)
    summaries, previous_ids, changed = await _replace_whatsapp_links(
        session,
        group_id=group.id,
        agency_id=group.agency_id,
        created_by_user_id=current_user.id,
        broadcast_ids=body.whatsapp_broadcast_group_ids,
        matching_fields_by_broadcast=body.matching_fields_by_broadcast,
    )
    await AuditLogRepository(session).record(
        action="client_group_whatsapp_links_replaced",
        entity_type="client_group",
        entity_id=str(group.id),
        agency_id=group.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "changed": changed,
            "previous_broadcast_count": len(previous_ids),
            "broadcast_count": len(summaries),
            "whatsapp_broadcast_group_ids": [str(summary.id) for summary in summaries],
        },
    )
    return ClientGroupWhatsAppLinksResponse(
        client_group_id=group.id,
        broadcasts=summaries,
        broadcast_count=len(summaries),
        recipient_count=await _unique_linked_recipient_count(
            session,
            group_id=group.id,
            agency_id=group.agency_id,
        ),
        can_manage=True,
    )


async def get_client_group_whatsapp_matches(
    link_id: uuid.UUID,
    broadcast_id: uuid.UUID | None,
    match_status: Literal[
        "all",
        "submitted",
        "not_submitted",
        "multiple_submissions",
        "needs_review",
        "unmatched_submission",
        "replacement",
        "rejected_upload",
    ],
    sort_by: Literal["name", "phone", "status", "broadcast", "updated_at"],
    sort_order: Literal["asc", "desc"],
    page: int,
    page_size: int,
    current_user: User,
    session: AsyncSession,
    *,
    _linked_broadcast_matching_fields_for_group: LinkedBroadcastMatchingFieldsForGroup,
    _linked_broadcast_names_for_group: LinkedBroadcastNamesForGroup,
    _require_viewable_group: RequireViewableGroup,
    _require_whatsapp_broadcast_access: RequireWhatsappBroadcastAccess,
) -> ClientGroupWhatsAppMatchesResponse:
    _require_whatsapp_broadcast_access(current_user)
    group = await _require_viewable_group(session, current_user, link_id)
    linked_broadcasts = await _linked_broadcast_names_for_group(
        session,
        group_id=group.id,
        agency_id=group.agency_id,
    )
    matching_fields_by_broadcast = await _linked_broadcast_matching_fields_for_group(
        session,
        group_id=group.id,
        agency_id=group.agency_id,
    )
    if broadcast_id is not None and broadcast_id not in linked_broadcasts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=("The selected WhatsApp broadcast is not linked to this client group."),
        )

    rows, submission_model_by_id = await _whatsapp_match_support.load_current_whatsapp_match_rows(
        session,
        group=group,
        linked_broadcasts=linked_broadcasts,
        matching_fields_by_broadcast=matching_fields_by_broadcast,
    )
    counts = summarize_match_rows(rows)
    if broadcast_id is not None:
        rows = [row for row in rows if broadcast_id in row.broadcast_ids]
        counts = summarize_match_rows(rows)
    ordered_rows = filter_and_sort_match_rows(
        rows,
        status=match_status,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    total = len(ordered_rows)
    offset = (page - 1) * page_size
    page_rows = ordered_rows[offset : offset + page_size]
    return _whatsapp_match_support.build_whatsapp_matches_response(
        client_group_id=group.id,
        selected_broadcast_id=broadcast_id,
        linked_broadcast_count=len(linked_broadcasts),
        counts=counts,
        page_rows=page_rows,
        submissions_by_id=submission_model_by_id,
        total=total,
        page=page,
        page_size=page_size,
    )


async def list_replacement_candidates(
    link_id: uuid.UUID,
    current_user: User,
    session: AsyncSession,
    *,
    _linked_broadcast_names_for_group: LinkedBroadcastNamesForGroup,
    _require_managed_group: RequireManagedGroup,
    _require_whatsapp_broadcast_access: RequireWhatsappBroadcastAccess,
) -> ReplacementCandidateListResponse:
    _require_whatsapp_broadcast_access(current_user)
    group = await _require_managed_group(session, current_user, link_id)
    linked_broadcasts = await _linked_broadcast_names_for_group(
        session,
        group_id=group.id,
        agency_id=group.agency_id,
    )
    recipient_models: list[WhatsAppBroadcastRecipientModel] = []
    if linked_broadcasts:
        result = await session.execute(
            select(WhatsAppBroadcastRecipientModel).where(
                WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
                WhatsAppBroadcastRecipientModel.broadcast_group_id.in_(list(linked_broadcasts)),
                WhatsAppBroadcastRecipientModel.removed_at.is_(None),
                WhatsAppBroadcastRecipientModel.suppressed_by_roster_resolution_id.is_(None),
            )
        )
        recipient_models = list(result.scalars().all())

    grouped: dict[str, list[WhatsAppBroadcastRecipientModel]] = {}
    for recipient in recipient_models:
        normalized = normalize_whatsapp_phone(recipient.normalized_phone_number)
        if normalized:
            grouped.setdefault(normalized, []).append(recipient)
    items: list[ReplacementCandidateResponse] = []
    for phone, logical_recipients in grouped.items():
        ordered = sorted(
            logical_recipients,
            key=lambda recipient: (
                linked_broadcasts.get(recipient.broadcast_group_id, "").casefold(),
                str(recipient.id),
            ),
        )
        first = ordered[0]
        items.append(
            ReplacementCandidateResponse(
                recipient_id=first.id,
                recipient_ids=[recipient.id for recipient in ordered],
                name=next(
                    (recipient.name for recipient in ordered if recipient.name),
                    None,
                ),
                phone=phone,
                broadcast_ids=list(
                    dict.fromkeys(recipient.broadcast_group_id for recipient in ordered)
                ),
                broadcast_names=list(
                    dict.fromkeys(
                        linked_broadcasts[recipient.broadcast_group_id] for recipient in ordered
                    )
                ),
                imported_fields=dict(first.imported_fields or {}),
            )
        )
    items.sort(
        key=lambda item: (
            (item.name or "").casefold(),
            item.phone,
            str(item.recipient_id),
        )
    )
    return ReplacementCandidateListResponse(
        client_group_id=group.id,
        items=items,
    )
