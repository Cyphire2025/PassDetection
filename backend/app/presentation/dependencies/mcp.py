"""Dedicated dashboard permission mcp.manage; never implied by an MCP token."""

from typing import cast

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.credentials import MCPAuthError
from app.core.config.settings import Settings
from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.dependencies.auth import get_current_active_user


async def require_mcp_management(
    request: Request,
    user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> User:
    try:
        if user.role != UserRole.SUPER_ADMIN:
            raise MCPAuthError()
        await MCPAuthorizationService(
            session, cast(Settings, request.app.state.settings)
        ).require_identity(
            user.id,
            user.session_version,
        )
    except MCPAuthError as exc:
        await AuditLogRepository(session).record(
            action="mcp.management_denied",
            entity_type="mcp_connection",
            user_id=user.id,
            result="denied",
        )
        await session.commit()
        raise AuthorizationError("MCP management requires an active superadmin account") from exc
    return user
