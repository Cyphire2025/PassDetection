"""Current authority over one stored schedule; no retention effect or file access."""

import asyncio
import json
from typing import Any
from uuid import UUID

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPAuthorizationService, MCPPrincipal
from app.application.mcp.credentials import MCPAuthError, utc
from app.core.config.settings import Settings
from app.domain.entities.entities import UserRole
from app.infrastructure.repositories.passport_retention_repository import (
    PassportRetentionRepository,
)

RETENTION_READ_TIMEOUT_SECONDS = 5
MAX_RETENTION_RESPONSE_BYTES = 8 * 1024


class RetentionReadError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class MCPPassportRetentionReadService:
    def __init__(self, session: AsyncSession, settings: Settings):
        self.session, self.settings = session, settings

    async def get_schedule(self, principal: MCPPrincipal, *, group_id: UUID) -> dict[str, Any]:
        try:
            async with asyncio.timeout(RETENTION_READ_TIMEOUT_SECONDS):
                if not isinstance(group_id, UUID):
                    raise RetentionReadError("retention_invalid_group")
                authority = MCPAuthorizationService(self.session, self.settings)
                grant = await authority.require_grant(principal.grant_id, lock=True)
                authority.require_capability(grant, "mcp:read")
                if grant.user_id != principal.user_id:
                    raise MCPAuthError()
                # require_grant already freshly validates and locks the active
                # Superadmin. Match its website permission for this exact group.
                schedule = await PassportRetentionRepository(self.session).get_schedule(
                    group_id=group_id,
                    role=UserRole.SUPER_ADMIN,
                    agency_id=None,
                    shared_lock=True,
                )
                if schedule is None:
                    raise RetentionReadError("retention_schedule_unavailable")
                days = schedule.passport_retention_days_applied
                if days is not None and (type(days) is not int or not 1 <= days <= 3650):
                    raise RetentionReadError("retention_read_limit")
                result = {
                    **schedule.project(),
                    "group_id": str(schedule.group_id),
                    "agency_id": str(schedule.agency_id),
                    "passport_purge_at": utc(schedule.passport_purge_at).isoformat()
                    if schedule.passport_purge_at is not None
                    else None,
                    "scope": "explicit_group",
                    "completeness": "complete",
                    "maximum_response_bytes": MAX_RETENTION_RESPONSE_BYTES,
                    "notice": "These are the stored passport-retention schedule values for the explicit group under current website access policy, including retained groups. A date or null value does not prove that a purge occurred, identify remaining records or files, or grant permission to schedule, cancel or delete anything. This read does not access files, run cleanup or change retention settings.",
                }
                envelope = {
                    **result,
                    "environment": self.settings.app_env,
                    "revision": self.settings.app_revision,
                    "observed_at": "2000-01-01T00:00:00.000000+00:00",
                    "audit_id": "00000000-0000-0000-0000-000000000000",
                }
                if (
                    len(json.dumps(envelope, ensure_ascii=True, allow_nan=False).encode())
                    > MAX_RETENTION_RESPONSE_BYTES
                ):
                    raise RetentionReadError("retention_read_limit")
                return result
        except TimeoutError as exc:
            raise RetentionReadError("retention_read_busy") from exc
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) in {"55P03", "57014"}:
                raise RetentionReadError("retention_read_busy") from exc
            raise
