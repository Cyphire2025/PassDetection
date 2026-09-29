"""Current actor's dashboard summary; a bounded preview, never global analytics."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.credentials import utc
from app.application.mcp.read_context import MCPReadContext
from app.application.use_cases.dashboard.get_dashboard_stats_use_case import (
    GetDashboardStatsUseCase,
)
from app.domain.value_objects.dashboard_summary import (
    RECENT_DASHBOARD_LIMIT,
    DashboardProjectionLimitError,
)
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)

DASHBOARD_READ_TIMEOUT_SECONDS = 10
MAX_DASHBOARD_RESPONSE_BYTES = 32 * 1024


class MCPDashboardReadService(MCPReadContext):
    def __init__(self, session: AsyncSession, *, cursor_secret: str):
        super().__init__(session, cursor_secret=cursor_secret, namespace="dashboard-summary")

    async def get_summary(self, user_id: UUID) -> dict[str, Any]:
        async with asyncio.timeout(DASHBOARD_READ_TIMEOUT_SECONDS):
            actor = await self._actor(user_id, RECENT_DASHBOARD_LIMIT)
            result: dict[str, Any] = {
                "total_passports": 0, "pending_review": 0, "confirmed": 0,
                "active_links": 0, "recent_submissions": [],
            }
            if actor.agency_id is not None:
                summary = await GetDashboardStatsUseCase(
                    PassportSubmissionRepository(self.session), ClientGroupRepository(self.session),
                ).execute(actor.agency_id, visible_to_user=actor)
                result = asdict(summary)
                for row in result["recent_submissions"]:
                    row["id"] = str(row["id"])
                    row["created_at"] = utc(row["created_at"]).isoformat()
            result.update(
                agency_id=str(actor.agency_id) if actor.agency_id else None,
                recent_submissions_limit=RECENT_DASHBOARD_LIMIT,
                completeness="complete", content_trust="untrusted_business_data",
                consistency={
                    "mode": "live_multi_query", "snapshot_guaranteed": False,
                    "notice": "Counts and recent rows are observed by separate live queries and can change during this observation.",
                },
                notice="The five-row preview is not a pageable history. Active links counts active visible groups, not verified unexpired credentials. An account without an agency has zero counts; no cross-agency aggregate is returned.",
            )
            try:
                size = len(json.dumps(result, ensure_ascii=True, allow_nan=False).encode("utf-8"))
            except ValueError as exc:
                raise DashboardProjectionLimitError("Dashboard preview cannot be represented safely") from exc
            if size > MAX_DASHBOARD_RESPONSE_BYTES:
                raise DashboardProjectionLimitError("Dashboard summary exceeds its response bound")
            return result
