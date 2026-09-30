"""Dashboard-only section controls; never exposed as an MCP tool."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.read_access import current_read_access
from app.domain.entities.entities import User
from app.domain.mcp_read_sections import read_section_catalog, validate_read_sections
from app.infrastructure.database.mcp_models import MCPControlModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.dependencies.auth import require_recent_mfa
from app.presentation.dependencies.csrf import require_cookie_csrf
from app.presentation.dependencies.mcp import require_mcp_management
from app.presentation.mcp.management_audit import MCPManagementAuditRoute

router = APIRouter(
    dependencies=[Depends(require_mcp_management), Depends(require_cookie_csrf), Depends(require_recent_mfa)],
    route_class=MCPManagementAuditRoute,
)


class MCPReadAccessUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allowed_read_sections: list[str] = Field(max_length=19)
    expected_revision: int = Field(ge=1, strict=True)

    @field_validator("allowed_read_sections")
    @classmethod
    def valid_sections(cls, values: list[str]) -> list[str]:
        return validate_read_sections(values)


def payload(request: Request, allowed: list[str], revision: int) -> dict[str, object]:
    settings = request.app.state.settings
    return {
        "read_only_mode": settings.mcp.read_only_mode,
        "effective_capabilities": settings.mcp.effective_capabilities,
        "allowed_read_sections": allowed,
        "revision": revision,
        "sections": read_section_catalog(),
        "connection_metadata_tools": ["connection_status"],
        "environment": settings.app_env,
        "backend_revision": settings.app_revision,
        "observed_at": datetime.now(UTC).isoformat(),
    }


@router.get("/read-access")
async def get_read_access(request: Request, session: AsyncSession = Depends(get_db_session)) -> dict[str, object]:
    try:
        allowed, revision = await current_read_access(session)
    except MCPAuthError:
        raise HTTPException(503, "MCP read access is unavailable") from None
    return payload(request, allowed, revision)


@router.put("/read-access")
async def set_read_access(
    body: MCPReadAccessUpdate, request: Request,
    user: User = Depends(require_mcp_management),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    row = await session.scalar(select(MCPControlModel).where(MCPControlModel.id == 1).with_for_update().execution_options(populate_existing=True))
    if row is None:
        raise HTTPException(503, "MCP read access is unavailable")
    if row.read_access_revision != body.expected_revision:
        raise HTTPException(409, "Read access changed. Reload current permissions before saving.")
    row.allowed_read_sections = body.allowed_read_sections
    row.read_access_revision += 1
    row.updated_at = datetime.now(UTC)
    await AuditLogRepository(session).record(
        action="mcp.read_access_changed", entity_type="mcp_control", user_id=user.id,
        metadata={"allowed_read_sections": body.allowed_read_sections, "revision": row.read_access_revision},
    )
    await session.commit()
    return payload(request, body.allowed_read_sections, row.read_access_revision)
