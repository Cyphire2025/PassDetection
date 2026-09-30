"""Current Superadmin authority over a fixed administrative count observation."""

import asyncio
import json
from typing import Any

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPAuthorizationService, MCPPrincipal
from app.application.mcp.credentials import MCPAuthError
from app.application.use_cases.admin_overview import ADMIN_OVERVIEW_FIELDS
from app.core.config.settings import Settings
from app.domain.entities.entities import UserRole
from app.infrastructure.repositories.admin_overview_repository import AdminOverviewRepository

ADMIN_OVERVIEW_TIMEOUT_SECONDS = 10
MAX_ADMIN_OVERVIEW_RESPONSE_BYTES = 8 * 1024


class AdminOverviewReadError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class MCPAdminOverviewReadService:
    def __init__(self, session: AsyncSession, settings: Settings):
        self.session, self.settings = session, settings

    async def get_overview(self, principal: MCPPrincipal) -> dict[str, Any]:
        try:
            async with asyncio.timeout(ADMIN_OVERVIEW_TIMEOUT_SECONDS):
                authority = MCPAuthorizationService(self.session, self.settings)
                grant = await authority.require_grant(principal.grant_id, lock=True)
                authority.require_capability(grant, "mcp:read")
                if grant.user_id != principal.user_id:
                    raise MCPAuthError()
                # require_grant freshly checks and locks active Superadmin
                # identity. Its canonical overview is global, even without an
                # agency; there is no need to hydrate another identity record.
                counts = await AdminOverviewRepository(self.session).overview(role=UserRole.SUPER_ADMIN, agency_id=None)
                if set(counts) != set(ADMIN_OVERVIEW_FIELDS) or any(
                    type(value) is not int or not 0 <= value <= 2**63 - 1 for value in counts.values()
                ):
                    raise AdminOverviewReadError("admin_overview_limit")
                result = {**counts, "scope": "platform_global", "completeness": "complete",
                    "consistency": {"mode": "live_multi_query", "snapshot_guaranteed": False},
                    "notice": "Seven separate live counts preserve the administrative website predicates. Agency, user and group totals include retained inactive or removed records. Passport totals include office-visible statuses under all parents; pending review, client submitted and failed exclude archived or deleted groups. Counts may change between queries and are not an atomic snapshot, unique-person count or service-health check."}
                envelope = {**result, "environment": self.settings.app_env, "revision": self.settings.app_revision,
                    "observed_at": "2000-01-01T00:00:00.000000+00:00", "audit_id": "00000000-0000-0000-0000-000000000000"}
                if len(json.dumps(envelope, ensure_ascii=True, allow_nan=False).encode()) > MAX_ADMIN_OVERVIEW_RESPONSE_BYTES:
                    raise AdminOverviewReadError("admin_overview_limit")
                return result
        except TimeoutError as exc:
            raise AdminOverviewReadError("admin_overview_busy") from exc
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) in {"55P03", "57014"}:
                raise AdminOverviewReadError("admin_overview_busy") from exc
            raise
