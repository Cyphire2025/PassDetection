"""Canonical Superadmin cross-agency analytics with bounded scalar observations."""

from __future__ import annotations

import asyncio
import json
import math
from typing import Any

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPAuthorizationService, MCPPrincipal
from app.application.mcp.credentials import MCPAuthError, utc
from app.application.use_cases.passports.passport_analytics import GetPassportAnalyticsSummary
from app.core.config.settings import Settings
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES
from app.domain.value_objects.passport_analytics import PassportAnalyticsLimitError
from app.infrastructure.repositories.passport_analytics_repository import (
    PassportAnalyticsRepository,
)
from app.infrastructure.repositories.user_repository import UserRepository

READ_TIMEOUT_SECONDS = 5
MAX_DAY_GROUPS = 366
MAX_RESPONSE_BYTES = 64 * 1024
MAX_COUNT = (1 << 63) - 1


class AnalyticsReadError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _validate_counts(result: dict[str, Any]) -> None:
    if not set(result["status_counts"]) <= set(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES):
        raise PassportAnalyticsLimitError()
    for field in ("status_counts", "confidence_buckets", "submissions_by_day"):
        if any(
            type(value) is not int or not 0 <= value <= MAX_COUNT
            for value in result[field].values()
        ):
            raise PassportAnalyticsLimitError()
    average = result["average_confidence"]
    if average is not None and (type(average) not in (int, float) or not math.isfinite(average)):
        raise PassportAnalyticsLimitError()


class MCPPassportAnalyticsReadService:
    def __init__(self, session: AsyncSession, settings: Settings):
        self.session, self.settings = session, settings

    async def summary(self, principal: MCPPrincipal, *, days: int = 30) -> dict[str, Any]:
        try:
            async with asyncio.timeout(READ_TIMEOUT_SECONDS):
                if type(days) is not int:
                    raise AnalyticsReadError("analytics_invalid_query")
                authority = MCPAuthorizationService(self.session, self.settings)
                grant = await authority.require_grant(principal.grant_id, lock=True)
                authority.require_capability(grant, "mcp:read")
                if grant.user_id != principal.user_id:
                    raise MCPAuthError()
                actor = await UserRepository(self.session).get_by_id(principal.user_id)
                if actor is None:
                    raise MCPAuthError()
                summary, since, bounded_days = await GetPassportAnalyticsSummary(
                    PassportAnalyticsRepository(self.session, maximum_day_groups=MAX_DAY_GROUPS)
                ).execute(actor, days)
                result = summary.project()
                _validate_counts(result)
                result.update(
                    days=bounded_days,
                    window_start=utc(since).isoformat(),
                    window_end=None,
                    agency_scope="all_agencies",
                    completeness="complete",
                    maximum_day_groups=MAX_DAY_GROUPS,
                    maximum_response_bytes=MAX_RESPONSE_BYTES,
                    maximum_count=MAX_COUNT,
                    consistency={
                        "mode": "live_multi_query",
                        "atomic_snapshot_guaranteed": False,
                        "notice": "Status counts, confidence buckets/average and date groups are three separate live scalar queries. The rolling window has only a lower creation-time bound; future-dated rows remain eligible. Date keys use PostgreSQL CAST(created_at AS DATE) in the database session timezone, whose name is not observed by this read.",
                    },
                    count_semantics={
                        "scope": "Canonical office-visible passport statuses across all agencies for Superadmin, including an account without an agency. No active-agency filter or upper creation-time cutoff is added.",
                        "confidence": "high >= 0.9; medium between 0.75 and 0.899 inclusive; low < 0.75; missing SQL NULL. Values greater than 0.899 and less than 0.9 fall in no bucket. Average includes all non-NULL values and is rounded to three decimals. Bucket totals need not equal status or daily totals.",
                    },
                )
                envelope = {
                    **result,
                    "environment": self.settings.app_env,
                    "revision": self.settings.app_revision,
                    "observed_at": "2000-01-01T00:00:00.000000+00:00",
                    "audit_id": "00000000-0000-0000-0000-000000000000",
                }
                if (
                    len(json.dumps(envelope, ensure_ascii=True, allow_nan=False).encode())
                    > MAX_RESPONSE_BYTES
                ):
                    raise PassportAnalyticsLimitError()
                return result
        except PassportAnalyticsLimitError as exc:
            raise AnalyticsReadError("analytics_read_limit") from exc
        except TimeoutError as exc:
            raise AnalyticsReadError("analytics_read_busy") from exc
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) in {"55P03", "57014"}:
                raise AnalyticsReadError("analytics_read_busy") from exc
            raise
