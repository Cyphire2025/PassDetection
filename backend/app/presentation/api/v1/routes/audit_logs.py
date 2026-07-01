"""
Audit Log Routes
================
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.schemas.operations_schemas import AuditLogResponse
from app.presentation.dependencies.auth import require_role

router = APIRouter()


@router.get(
    "",
    response_model=list[AuditLogResponse],
    status_code=status.HTTP_200_OK,
    summary="List audit logs for the current administrative scope",
)
async def list_audit_logs(
    current_user: User = Depends(require_role([UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN])),
    session: AsyncSession = Depends(get_db_session),
    skip: int = 0,
    limit: int = 100,
) -> list[AuditLogResponse]:
    agency_id = None if current_user.role == UserRole.SUPER_ADMIN else current_user.agency_id
    logs = await AuditLogRepository(session).list_by_agency(agency_id, skip=skip, limit=limit)
    return [
        AuditLogResponse(
            id=log.id,
            agency_id=log.agency_id,
            user_id=log.user_id,
            actor_email=log.actor_email,
            action=log.action,
            entity_type=log.entity_type,
            entity_id=log.entity_id,
            ip_address=log.ip_address,
            metadata=log.metadata_json,
            created_at=log.created_at,
        )
        for log in logs
    ]
