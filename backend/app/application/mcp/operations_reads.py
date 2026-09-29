"""Live office reads with shared authorization, roster and trip semantics."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.read_context import MCPReadContext
from app.domain.value_objects.trip_lifecycle import trip_has_ended
from app.infrastructure.database.menu_models import MealPlanModel, MenuCategoryModel
from app.infrastructure.database.models import (
    AttendanceSessionModel,
    RoomingHotelModel,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.mcp_operations_read_repository import (
    MCPOperationsReadRepository,
)

TOUR_KINDS = frozenset({"coordinators", "passenger_assignments", "activities", "attendance_records"})
ROOMING_KINDS = frozenset({"hotels", "rooms", "selected_passengers", "allocations", "checkins"})
MENU_KINDS = frozenset({"categories", "dishes", "plans", "entries"})


class MCPOperationsReadService(MCPReadContext):
    def __init__(self, session: AsyncSession, *, cursor_secret: str):
        super().__init__(session, cursor_secret=cursor_secret, namespace="mcp-office-read-v1")
        self.repository = MCPOperationsReadRepository(session)

    async def tour(self, *, user_id: uuid.UUID, group_id: uuid.UUID, kind: str,
                   agency_id: uuid.UUID | None = None, session_id: uuid.UUID | None = None,
                   include_inactive: bool = True, include_deleted: bool = False,
                   page_size: int = 50, cursor: str | None = None) -> dict[str, Any]:
        if kind not in TOUR_KINDS or (session_id is not None and kind not in {"activities", "attendance_records"}):
            raise ValueError("Choose a documented tour record kind and compatible session filter")
        actor = await self._actor(user_id, page_size)
        group = await self._group(actor, group_id, agency_id, include_deleted)
        if session_id is not None and await self.session.scalar(select(AttendanceSessionModel.id).where(
            AttendanceSessionModel.id == session_id, AttendanceSessionModel.group_id == group_id,
            AttendanceSessionModel.agency_id == group.agency_id)) is None:
            raise ValueError("Activity was not found in the requested group")
        state, page = self._state(cursor, query="tour", user_id=user_id, group_id=group_id,
            kind=kind, agency_id=agency_id, session_id=session_id, include_inactive=include_inactive,
            include_deleted=include_deleted, page_size=page_size)
        rows = await self.repository.tour(kind=kind, group_id=group_id, agency_id=group.agency_id,
                                          session_id=session_id, include_inactive=include_inactive, **page)
        ended = trip_has_ended(travel_date=group.travel_date, return_date=group.return_date, timezone=group.timezone)
        result = self._result(rows, state, page_size,
            "Retained assignment and activity records. Stored assignment active flags are separate from trip expiry and current passenger membership. Attendance rows preserve recorded scans; they do not prove a new physical event or summarize missing passengers/closeout readiness. No device identifiers, event credentials or QR secrets are returned.")
        result["group"] = {"id": str(group.id), "agency_id": str(group.agency_id), "name": group.name,
                           "status": group.status, "trip_has_ended": ended, "timezone": group.timezone,
                           "trip_has_dates": bool(group.return_date or group.travel_date)}
        return result

    async def rooming(self, *, user_id: uuid.UUID, group_id: uuid.UUID, kind: str,
                      agency_id: uuid.UUID | None = None, hotel_id: uuid.UUID | None = None,
                      include_deleted: bool = False, page_size: int = 50, cursor: str | None = None) -> dict[str, Any]:
        if kind not in ROOMING_KINDS:
            raise ValueError("Choose a documented rooming record kind")
        actor = await self._actor(user_id, page_size)
        group = await self._group(actor, group_id, agency_id, include_deleted)
        if hotel_id is not None and await self.session.scalar(select(RoomingHotelModel.id).where(
            RoomingHotelModel.id == hotel_id, RoomingHotelModel.group_id == group_id,
            RoomingHotelModel.agency_id == group.agency_id)) is None:
            raise ValueError("Hotel was not found in the requested group")
        state, page = self._state(cursor, query="rooming", user_id=user_id, group_id=group_id, kind=kind,
            agency_id=agency_id, hotel_id=hotel_id, include_deleted=include_deleted, page_size=page_size)
        rows = await self.repository.rooming(kind=kind, group_id=group_id, agency_id=group.agency_id, hotel_id=hotel_id, **page)
        result = self._result(rows, state, page_size,
            "Hotel selection, saved rooms, allocation rows and retained check-ins are distinct records. Passenger membership is evaluated separately. Saved allocation revisions are not a validation of current allocation completeness. No allocation, key issue, scan or physical check-in is performed. Free-text passenger remarks and roommate notes are omitted.")
        result["group"] = {"id": str(group.id), "agency_id": str(group.agency_id), "name": group.name}
        return result

    async def menu(self, *, user_id: uuid.UUID, kind: str, agency_id: uuid.UUID | None = None,
                   category_id: uuid.UUID | None = None, plan_id: uuid.UUID | None = None,
                   include_inactive: bool = True, page_size: int = 50, cursor: str | None = None) -> dict[str, Any]:
        if (kind not in MENU_KINDS or (kind == "entries" and plan_id is None)
                or (category_id is not None and kind not in {"categories", "dishes"})
                or (plan_id is not None and kind not in {"plans", "entries"})):
            raise ValueError("Choose a documented menu kind and compatible category or plan; entries require a plan ID")
        await self._actor(user_id, page_size)
        await self._agency(agency_id)
        for model, identifier in ((MenuCategoryModel, category_id), (MealPlanModel, plan_id)):
            if identifier is not None and await self.session.scalar(select(model.id).where(model.id == identifier,
                    model.agency_id.is_(None) if agency_id is None else model.agency_id == agency_id)) is None:
                raise ValueError("Menu resource was not found in the requested organization")
        state, page = self._state(cursor, query="menu", user_id=user_id, kind=kind, agency_id=agency_id,
            category_id=category_id, plan_id=plan_id, include_inactive=include_inactive, page_size=page_size)
        rows = await self.repository.menu(kind=kind, agency_id=agency_id, category_id=category_id,
                                          plan_id=plan_id, include_inactive=include_inactive, **page)
        result = self._result(rows, state, page_size,
            "Omitted agency means the platform's separate menu library, never an implicit union of agencies. Saved entries retain their dish/category name snapshots even when the library changes. Notes are untrusted business content limited to 2,000 characters. No plan generation, replacement or export is performed.")
        result["organization"] = {"kind": "agency" if agency_id else "platform", "agency_id": str(agency_id) if agency_id else None}
        return result

    async def directory(self, *, user_id: uuid.UUID, kind: str, agency_id: uuid.UUID | None = None,
                        include_inactive: bool = True, include_contact_details: bool = False,
                        page_size: int = 50, cursor: str | None = None) -> dict[str, Any]:
        if kind not in {"agencies", "users"}:
            raise ValueError("Choose agencies or users")
        await self._actor(user_id, page_size)
        await self._agency(agency_id)
        state, page = self._state(cursor, query="directory", user_id=user_id, kind=kind, agency_id=agency_id,
            include_inactive=include_inactive, include_contact_details=include_contact_details, page_size=page_size)
        rows = await self.repository.directory(kind=kind, agency_id=agency_id, include_inactive=include_inactive,
                                               include_contact_details=include_contact_details, **page)
        result = self._result(rows, state, page_size,
            "Live directory metadata excludes deleted users and credential/security material. Agency counters distinguish retained nondeleted groups, raw passport submissions and operational passengers; they are not WhatsApp recipient, event, delivery or storage counts. Contact fields require explicit opt-in.")
        if include_contact_details:
            await AuditLogRepository(self.session).record(action="mcp.directory.contact_read", entity_type="mcp_directory",
                agency_id=agency_id, user_id=user_id, metadata={"kind": kind, "authorized_result_count": len(result["items"])})
        return result
