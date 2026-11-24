"""Retention for upload links; HTTP declarations remain in client_groups."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.client_groups.delete_client_group_use_case import (
    DeleteClientGroupUseCase,
)
from app.application.use_cases.client_groups.restore_client_group_use_case import (
    RestoreClientGroupUseCase,
)
from app.application.use_cases.client_groups.revoke_client_group_use_case import (
    RevokeClientGroupUseCase,
)
from app.domain.entities.entities import (
    User,
    UserRole,
)
from app.domain.exceptions.exceptions import (
    AuthorizationError,
    ConflictError,
    EntityNotFoundError,
    PassDetectionError,
)
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.presentation.api.v1.routes.client_group_operation_dependencies import (
    SyncGroupBroadcastContacts,
)
from app.presentation.api.v1.schemas.client_group_schemas import (
    ClientGroupResponse,
)


async def revoke_client_group(
    link_id: uuid.UUID,
    current_user: User,
    use_case: RevokeClientGroupUseCase,
    session: AsyncSession,
) -> ClientGroupResponse:
    if not current_user.agency_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )

    group = await ClientGroupRepository(session).get_by_id(link_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Client group was not found"
        )
    try:
        await AuthorizationPolicy(session).require_manage_group(current_user, group)
        result = await use_case.execute(
            link_id=link_id,
            agency_id=current_user.agency_id,
            created_by_user_id=None,
        )
        return ClientGroupResponse.model_validate(result)
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except AuthorizationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=e.message)
    except PassDetectionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)


async def delete_client_group(
    link_id: uuid.UUID,
    current_user: User,
    use_case: DeleteClientGroupUseCase,
    session: AsyncSession,
) -> ClientGroupResponse:
    if not current_user.agency_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )

    group = await ClientGroupRepository(session).get_by_id(link_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Client group was not found"
        )
    try:
        await AuthorizationPolicy(session).require_delete_data(current_user, group)
        result = await use_case.execute(
            group_id=link_id,
            agency_id=current_user.agency_id,
            created_by_user_id=None,
        )
        return ClientGroupResponse.model_validate(result)
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except AuthorizationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=e.message)
    except PassDetectionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)


async def restore_client_group(
    link_id: uuid.UUID,
    current_user: User,
    use_case: RestoreClientGroupUseCase,
    session: AsyncSession,
    *,
    sync_group_broadcast_contacts: SyncGroupBroadcastContacts,
) -> ClientGroupResponse:
    if not current_user.agency_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )

    group = await ClientGroupRepository(session).get_by_id(link_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Client group was not found"
        )
    try:
        await AuthorizationPolicy(session).require_manage_group(current_user, group)
        result = await use_case.execute(
            group_id=link_id,
            agency_id=current_user.agency_id,
            created_by_user_id=None,
            allow_deleted_restore=current_user.role == UserRole.SUPER_ADMIN,
        )
        await sync_group_broadcast_contacts(
            session,
            agency_id=group.agency_id,
            group_id=group.id,
            actor_user_id=current_user.id,
        )
        return ClientGroupResponse.model_validate(result)
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except AuthorizationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=e.message)
    except PassDetectionError as e:
        raise HTTPException(
            status_code=(
                status.HTTP_409_CONFLICT
                if isinstance(e, ConflictError)
                else status.HTTP_400_BAD_REQUEST
            ),
            detail=e.message,
        )
