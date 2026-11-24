"""Reads for upload links; HTTP declarations remain in client_groups."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.client_groups.list_client_groups_use_case import (
    ListClientGroupsUseCase,
)
from app.domain.entities.entities import (
    User,
    UserRole,
)
from app.presentation.api.v1.pagination import PageOffset, PageSize
from app.presentation.api.v1.routes.client_group_broadcast_configuration import (
    _broadcast_summaries,
    _linked_broadcast_summaries_by_group,
)
from app.presentation.api.v1.routes.client_group_operation_dependencies import (
    OwnerScopeFor,
    RequireManagedGroup,
    RequireViewableGroup,
    RequireWhatsappBroadcastAccess,
    UniqueLinkedRecipientCount,
)
from app.presentation.api.v1.schemas.client_group_schemas import (
    ClientGroupResponse,
    ClientGroupWhatsAppLinksResponse,
    WhatsAppBroadcastSummaryResponse,
)


async def list_client_groups(
    skip: PageOffset,
    limit: PageSize,
    status_filter: str | None,
    current_user: User,
    use_case: ListClientGroupsUseCase,
    *,
    _owner_scope_for: OwnerScopeFor,
) -> list[ClientGroupResponse]:
    if not current_user.agency_id:
        return []
    if status_filter == "deleted" and current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only super admins can view deleted group data",
        )

    results = await use_case.execute(
        agency_id=current_user.agency_id,
        skip=skip,
        limit=limit,
        status_filter=status_filter,
        created_by_user_id=None if status_filter == "deleted" else _owner_scope_for(current_user),
        visible_to_user=None if status_filter == "deleted" else current_user,
    )
    return [ClientGroupResponse.model_validate(r) for r in results]


async def list_whatsapp_broadcast_options_for_create(
    current_user: User,
    session: AsyncSession,
    *,
    _require_whatsapp_broadcast_access: RequireWhatsappBroadcastAccess,
) -> list[WhatsAppBroadcastSummaryResponse]:
    _require_whatsapp_broadcast_access(current_user)
    if not current_user.agency_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must be associated with an agency.",
        )
    return await _broadcast_summaries(
        session,
        agency_id=current_user.agency_id,
    )


async def list_whatsapp_broadcast_options_for_group(
    link_id: uuid.UUID,
    current_user: User,
    session: AsyncSession,
    *,
    _require_managed_group: RequireManagedGroup,
    _require_whatsapp_broadcast_access: RequireWhatsappBroadcastAccess,
) -> list[WhatsAppBroadcastSummaryResponse]:
    _require_whatsapp_broadcast_access(current_user)
    group = await _require_managed_group(session, current_user, link_id)
    return await _broadcast_summaries(
        session,
        agency_id=group.agency_id,
        existing_group_id=group.id,
    )


async def get_client_group_whatsapp_links(
    link_id: uuid.UUID,
    current_user: User,
    session: AsyncSession,
    *,
    _require_viewable_group: RequireViewableGroup,
    _require_whatsapp_broadcast_access: RequireWhatsappBroadcastAccess,
    _unique_linked_recipient_count: UniqueLinkedRecipientCount,
) -> ClientGroupWhatsAppLinksResponse:
    _require_whatsapp_broadcast_access(current_user)
    group = await _require_viewable_group(session, current_user, link_id)
    can_manage = await AuthorizationPolicy(session).can_manage_group(current_user, group)
    linked = await _linked_broadcast_summaries_by_group(
        session,
        agency_id=group.agency_id,
        client_group_ids=[group.id],
    )
    summaries = linked.get(group.id, [])
    return ClientGroupWhatsAppLinksResponse(
        client_group_id=group.id,
        broadcasts=summaries,
        broadcast_count=len(summaries),
        recipient_count=await _unique_linked_recipient_count(
            session,
            group_id=group.id,
            agency_id=group.agency_id,
        ),
        can_manage=can_manage,
    )
