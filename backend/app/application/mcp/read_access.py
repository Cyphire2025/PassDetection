"""Current database section authority, independent of stored bearer claims."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.credentials import MCPAuthError
from app.domain.mcp_read_sections import READ_TOOL_SECTIONS, validate_read_sections
from app.infrastructure.database.mcp_models import MCPControlModel


async def current_read_access(session: AsyncSession, *, lock: bool = False) -> tuple[list[str], int]:
    statement = select(MCPControlModel.allowed_read_sections, MCPControlModel.read_access_revision).where(MCPControlModel.id == 1)
    if lock:
        statement = statement.with_for_update(read=True)
    row = (await session.execute(statement)).one_or_none()
    if row is None or type(row[0]) is not list or type(row[1]) is not int or row[1] < 1:
        raise MCPAuthError("temporarily_unavailable", 503)
    try:
        values = validate_read_sections(row[0])
    except (TypeError, ValueError):
        raise MCPAuthError("temporarily_unavailable", 503) from None
    return values, row[1]


async def require_read_sections(session: AsyncSession, name: str) -> None:
    required = READ_TOOL_SECTIONS.get(name)
    if required is None:
        raise MCPAuthError("unsupported_read_tool", 403)
    if not required:
        return  # Explicit connection metadata has no business section.
    allowed, _ = await current_read_access(session, lock=True)
    if required - set(allowed):
        raise MCPAuthError("read_section_denied", 403)
