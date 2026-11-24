"""Stable dashboard representation of a retained MCP connection."""

from __future__ import annotations

from datetime import UTC, datetime

from app.application.mcp.credentials import utc
from app.core.config.settings import Settings
from app.domain.mcp_section_permissions import WRITE_CAPABILITIES
from app.infrastructure.database.mcp_models import MCPGrantModel


def connection_payload(grant: MCPGrantModel, settings: Settings | None = None) -> dict[str, object]:
    effective = (
        set(grant.capabilities) & set(settings.mcp.effective_capabilities)
        if settings
        else set(grant.capabilities)
    )
    if grant.read_enabled is not True:
        effective.discard("mcp:read")
    if grant.write_enabled is not True:
        effective.difference_update(WRITE_CAPABILITIES)
    return {
        "id": str(grant.id),
        "user_id": str(grant.user_id),
        "client_id": grant.client_id,
        "name": grant.name,
        "enabled": grant.enabled,
        "read_enabled": grant.read_enabled,
        "write_enabled": grant.write_enabled,
        "allowed_read_sections": grant.allowed_read_sections,
        "allowed_write_sections": grant.allowed_write_sections,
        "permission_revision": grant.permission_revision,
        "device_platform": grant.device_platform,
        "capabilities": grant.capabilities,
        "effective_capabilities": sorted(effective),
        "created_at": grant.created_at,
        "expires_at": grant.expires_at,
        "last_used_at": grant.last_used_at,
        "revoked_at": grant.revoked_at,
        "status": "revoked"
        if grant.revoked_at
        else "expired"
        if utc(grant.expires_at) <= datetime.now(UTC)
        else "disabled"
        if not grant.enabled
        else "active",
    }
