"""Freshly authorized email readiness and personal summary observations only."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPAuthorizationService, MCPPrincipal
from app.application.mcp.credentials import MCPAuthError
from app.application.use_cases.email_integrations.overview import (
    email_readiness,
    email_summary_day_start,
)
from app.core.config.settings import Settings
from app.domain.entities.entities import User
from app.infrastructure.repositories.email_summary_repository import EmailSummaryRepository
from app.infrastructure.repositories.user_repository import UserRepository

EMAIL_OVERVIEW_TIMEOUT_SECONDS = 10
MAX_EMAIL_OVERVIEW_RESPONSE_BYTES = 8 * 1024


class EmailOverviewReadError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@asynccontextmanager
async def _read_deadline() -> AsyncIterator[None]:
    try:
        async with asyncio.timeout(EMAIL_OVERVIEW_TIMEOUT_SECONDS):
            yield
    except TimeoutError as exc:
        raise EmailOverviewReadError("email_overview_busy") from exc
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) in {"55P03", "57014"}:
            raise EmailOverviewReadError("email_overview_busy") from exc
        raise


class MCPEmailOverviewReadService:
    def __init__(self, session: AsyncSession, settings: Settings):
        self.session, self.settings = session, settings

    async def _actor(self, principal: MCPPrincipal) -> User:
        authority = MCPAuthorizationService(self.session, self.settings)
        grant = await authority.require_grant(principal.grant_id, lock=True)
        authority.require_capability(grant, "mcp:read")
        if grant.user_id != principal.user_id:
            raise MCPAuthError()
        actor = await UserRepository(self.session).get_by_id(principal.user_id)
        if actor is None:
            raise MCPAuthError()
        return actor

    def _bounded(self, result: dict[str, Any]) -> dict[str, Any]:
        # Reserve the complete fixed-width invocation envelope, using the actual
        # settings and conservative escaped JSON rather than only service data.
        value = {**result, "environment": self.settings.app_env, "revision": self.settings.app_revision,
            "observed_at": "2000-01-01T00:00:00.000000+00:00", "audit_id": "00000000-0000-0000-0000-000000000000"}
        if len(json.dumps(value, ensure_ascii=True, allow_nan=False).encode("utf-8")) > MAX_EMAIL_OVERVIEW_RESPONSE_BYTES:
            raise EmailOverviewReadError("email_overview_limit")
        return result

    async def get_status(self, principal: MCPPrincipal) -> dict[str, Any]:
        async with _read_deadline():
            await self._actor(principal)
            return self._bounded({**email_readiness(self.settings), "completeness": "complete",
                "consistency": {"mode": "configuration_observation", "snapshot_guaranteed": False},
                "notice": "Readiness reflects configuration only. It does not validate credentials, a connected mailbox, provider availability, worker health or delivery. Reading does not enable features or contact a provider."})

    async def get_summary(self, principal: MCPPrincipal) -> dict[str, Any]:
        async with _read_deadline():
            actor = await self._actor(principal)
            today = email_summary_day_start()
            counts = await EmailSummaryRepository(self.session).summary(actor, today=today)
            if any(type(value) is not int or not 0 <= value <= 2**63 - 1 for value in counts.values()):
                raise EmailOverviewReadError("email_overview_limit")
            return self._bounded({**counts, "period_start_utc": today.isoformat(),
                "mailbox_scope": "personal_owner_only", "completeness": "complete",
                "consistency": {"mode": "live_multi_query", "snapshot_guaranteed": False},
                "notice": "Seven separate live counts cover only this account's personally owned mailboxes, across agencies for a Superadmin. Today starts at UTC midnight; predicates retain records at or after that boundary. Counts may change between queries. Stored records are not unique people or proof of delivery. Reading never syncs, retrieves files, retries work or sends messages."})
