"""Own-agency office attendance reads through canonical revisioned projections."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPAuthorizationService, MCPPrincipal
from app.application.mcp.credentials import MCPAuthError, utc
from app.application.mcp.read_cursor import MCPReadCursor
from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.attendance_dashboard import (
    AttendanceActivityNotFoundError,
    AttendanceDashboardService,
    AttendanceSnapshotChangedError,
)
from app.application.use_cases.attendance_projection import (
    attendance_missing_data,
    attendance_summary_data,
)
from app.core.config.settings import Settings
from app.domain.exceptions.exceptions import AuthorizationError
from app.domain.value_objects.attendance_read_limits import (
    AttendanceReadLimitError,
    AttendanceReadLimits,
)
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.repositories.attendance_closeout_repository import (
    AttendanceCloseoutRepository,
)
from app.infrastructure.repositories.attendance_dashboard_repository import (
    AttendanceDashboardRepository,
)
from app.infrastructure.repositories.user_repository import UserRepository

READ_TIMEOUT_SECONDS = 5
MAX_RESPONSE_BYTES = 512 * 1024
READ_LIMITS = AttendanceReadLimits()


class AttendanceReadError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@asynccontextmanager
async def attendance_deadline() -> AsyncIterator[None]:
    try:
        async with asyncio.timeout(READ_TIMEOUT_SECONDS):
            yield
    except TimeoutError as exc:
        raise AttendanceReadError("attendance_read_busy") from exc
    except AttendanceReadLimitError as exc:
        raise AttendanceReadError("attendance_read_limit") from exc
    except AttendanceActivityNotFoundError as exc:
        raise AttendanceReadError("attendance_activity_unavailable") from exc
    except AttendanceSnapshotChangedError as exc:
        raise AttendanceReadError("attendance_snapshot_changed") from exc
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) in {"55P03", "57014"}:
            raise AttendanceReadError("attendance_read_busy") from exc
        raise


class MCPAttendanceReadService:
    def __init__(self, session: AsyncSession, settings: Settings):
        self.session, self.settings = session, settings
        self.cursors = MCPReadCursor(settings.app_secret_key, "mcp-attendance-missing-v1")
        self.dashboard = AttendanceDashboardService(
            AttendanceDashboardRepository(session, read_limits=READ_LIMITS),
            AttendanceCloseoutRepository(session, read_limits=READ_LIMITS),
        )

    async def _scope(self, principal: MCPPrincipal, group_id: uuid.UUID) -> Any:
        authority = MCPAuthorizationService(self.session, self.settings)
        grant = await authority.require_grant(principal.grant_id, lock=True)
        authority.require_capability(grant, "mcp:read")
        if grant.user_id != principal.user_id:
            raise MCPAuthError()
        actor = await UserRepository(self.session).get_by_id(principal.user_id)
        if actor is None or actor.agency_id is None:
            raise MCPAuthError("access_denied", 403)
        model = ClientGroupModel
        group = (
            await self.session.execute(
                select(
                    model.id,
                    model.agency_id,
                    func.substr(model.name, 1, 256).label("name"),
                    model.status,
                    model.deleted_at,
                    model.created_by_user_id,
                )
                .where(
                    model.id == group_id,
                    model.agency_id == actor.agency_id,
                    model.status != "deleted",
                )
                .with_for_update(read=True)
            )
        ).one_or_none()
        if group is None:
            raise AttendanceReadError("attendance_group_unavailable")
        try:
            await AuthorizationPolicy(self.session).require_assign_coordinator(actor, group)
        except AuthorizationError as exc:
            raise MCPAuthError("access_denied", 403) from exc
        if len(group.name) > 255:
            raise AttendanceReadLimitError()
        return group

    def _finish(
        self, result: dict[str, Any], group: Any, *, partial: bool = False
    ) -> dict[str, Any]:
        result["snapshot_revision"] = result.pop("revision")
        result.update(
            agency_id=str(group.agency_id),
            group_id=str(group.id),
            completeness="partial" if partial else "complete",
            content_trust="untrusted_business_data",
            maximum_response_bytes=MAX_RESPONSE_BYTES,
            maximum_activities=READ_LIMITS.activities,
            maximum_source_rows_per_family=READ_LIMITS.source_rows,
            maximum_derived_combinations=READ_LIMITS.derived_combinations,
            count_semantics={
                "present_count": "Distinct retained passenger IDs recorded across the canonical activity and its aliases, including IDs no longer in the current approved roster.",
                "missing_count": "Canonical max(current approved roster count minus retained present count, 0); this is not the total number of missing-passenger page rows.",
                "missing_passenger_pages": "Current approved roster members without a retained family record. Page rows and summary missing_count can diverge after roster changes; neither proves physical presence.",
            },
            consistency={
                "mode": "live_optimistic_revision",
                "atomic_snapshot_guaranteed": False,
                "notice": "Summary queries are live. Missing pages recheck the canonical activity/roster revision before and after reading; refresh the summary after a conflict. Closeout readiness describes retained reported queue metadata, not physical attendance or permission to close.",
            },
        )
        encoded = json.dumps(result, default=_json_scalar, ensure_ascii=True, allow_nan=False)
        safe = json.loads(encoded)
        envelope = {
            **safe,
            "environment": self.settings.app_env,
            "revision": self.settings.app_revision,
            "observed_at": "2000-01-01T00:00:00.000000+00:00",
            "audit_id": "00000000-0000-0000-0000-000000000000",
        }
        if (
            len(json.dumps(envelope, ensure_ascii=True, allow_nan=False).encode())
            > MAX_RESPONSE_BYTES
        ):
            raise AttendanceReadLimitError()
        return dict(safe)

    async def summary(self, principal: MCPPrincipal, *, group_id: uuid.UUID) -> dict[str, Any]:
        async with attendance_deadline():
            group = await self._scope(principal, group_id)
            projection = await self.dashboard.summary(
                agency_id=group.agency_id, group_id=group.id, group_name=group.name
            )
            result = attendance_summary_data(projection)
            partial = any(activity.coordinators_truncated for activity in projection.activities)
            return self._finish(result, group, partial=partial)

    async def missing(
        self,
        principal: MCPPrincipal,
        *,
        group_id: uuid.UUID,
        session_id: uuid.UUID,
        snapshot_revision: str,
        page_size: int = 50,
        cursor: str | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        async with attendance_deadline():
            if (
                type(page_size) is not int
                or not 1 <= page_size <= 100
                or not re.fullmatch("[0-9a-f]{32}", snapshot_revision)
                or search is not None
                and (not isinstance(search, str) or len(search) > 120)
            ):
                raise AttendanceReadError("attendance_invalid_query")
            group = await self._scope(principal, group_id)
            normalized = " ".join(search.split()) if search else None
            try:
                state = self.cursors.read(
                    cursor,
                    dict(
                        actor=principal.user_id,
                        agency=group.agency_id,
                        group=group.id,
                        session=session_id,
                        revision=snapshot_revision,
                        search=normalized or None,
                        page_size=page_size,
                    ),
                )
                after = self.cursors.after(state)
            except ValueError as exc:
                raise AttendanceReadError("attendance_invalid_query") from exc
            projection = await self.dashboard.missing_passengers(
                agency_id=group.agency_id,
                group_id=group.id,
                canonical_session_id=session_id,
                expected_revision=snapshot_revision,
                cursor=after[1] if after else None,
                limit=page_size,
                search=normalized or None,
            )
            result = attendance_missing_data(projection, page_size=page_size)
            if projection.page.next_cursor is not None:
                result["next_cursor"] = self.cursors.next(
                    state,
                    {
                        "id": projection.page.next_cursor,
                        "created_at": datetime.fromisoformat(state["cutoff"]),
                    },
                )
            return self._finish(result, group, partial=projection.page.has_more)


def _json_scalar(value: Any) -> str:
    if isinstance(value, datetime):
        return utc(value).isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    raise TypeError("Unsupported attendance projection type")
