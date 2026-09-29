"""Bounded projections of retained tour, rooming and menu records.

Only fixed query shapes are accepted. No ORM relationships are eagerly loaded
and no write-oriented route helpers are invoked while observing stored state.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES
from app.infrastructure.database.menu_models import (
    MealPlanEntryModel,
    MealPlanModel,
    MenuCategoryModel,
    MenuDishModel,
)
from app.infrastructure.database.models import (
    AgencyModel,
    AttendanceRecordModel,
    AttendanceSessionModel,
    ClientGroupModel,
    CoordinatorAssignmentModel,
    CoordinatorGroupAssignmentModel,
    PassportSubmissionModel,
    RoomingAssignmentModel,
    RoomingCheckinModel,
    RoomingHotelModel,
    RoomingHotelPassengerModel,
    RoomingRoomModel,
    UserModel,
)
from app.infrastructure.repositories.mcp_read_page import read_page
from app.infrastructure.repositories.operational_roster import operational_roster_member


class MCPOperationsReadRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def page(self, statement: Any, model: Any, *, cutoff: datetime,
                   after: tuple[datetime, uuid.UUID] | None, size: int,
                   timestamp: Any = None) -> list[dict[str, Any]]:
        return await read_page(self.session, statement, model, cutoff=cutoff, after=after, size=size, timestamp=timestamp)

    @staticmethod
    def operational(passenger_id: Any, group_id: uuid.UUID, agency_id: uuid.UUID) -> Any:
        passenger = PassportSubmissionModel
        return select(passenger.id).where(passenger.id == passenger_id, passenger.group_id == group_id,
            passenger.agency_id == agency_id, passenger.status.in_(OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES),
            operational_roster_member()).correlate_except(passenger).exists()

    async def tour(self, *, kind: str, group_id: uuid.UUID, agency_id: uuid.UUID,
                   session_id: uuid.UUID | None, include_inactive: bool, **page: Any) -> list[dict[str, Any]]:
        if kind in {"coordinators", "passenger_assignments"}:
            assignment: Any = CoordinatorGroupAssignmentModel if kind == "coordinators" else CoordinatorAssignmentModel
            user = UserModel
            fields = [assignment.id, assignment.coordinator_user_id, user.full_name.label("coordinator_name"),
                user.is_active.label("coordinator_active"), user.deleted_at.is_not(None).label("coordinator_deleted"),
                assignment.active, assignment.assigned_at.label("created_at"), assignment.unassigned_at]
            if kind == "passenger_assignments":
                fields += [assignment.passenger_id, self.operational(assignment.passenger_id, group_id, agency_id).label("passenger_is_operational")]
            query = select(*fields).join(user, and_(user.id == assignment.coordinator_user_id, user.agency_id == assignment.agency_id)).where(
                assignment.group_id == group_id, assignment.agency_id == agency_id)
            if kind == "passenger_assignments":
                passenger = PassportSubmissionModel
                query = query.join(passenger, and_(passenger.id == assignment.passenger_id,
                    passenger.group_id == assignment.group_id, passenger.agency_id == assignment.agency_id))
            if not include_inactive:
                query = query.where(assignment.active.is_(True))
            return await self.page(query, assignment, timestamp=assignment.assigned_at, **page)
        activity = AttendanceSessionModel
        if kind == "activities":
            query = select(activity.id, activity.canonical_session_id, activity.name, activity.status,
                activity.created_at, activity.updated_at, activity.started_at, activity.completed_at,
                activity.cancelled_at, activity.scheduled_starts_at, activity.scheduled_ends_at,
                activity.schedule_timezone, activity.schedule_version).where(
                    activity.group_id == group_id, activity.agency_id == agency_id)
            if session_id is not None:
                query = query.where(activity.id == session_id)
            return await self.page(query, activity, **page)
        record, passenger = AttendanceRecordModel, PassportSubmissionModel
        query = select(record.id, record.session_id, activity.canonical_session_id, record.passenger_id,
            record.coordinator_user_id, record.scanned_at, record.sync_source, record.created_at,
            self.operational(record.passenger_id, group_id, agency_id).label("passenger_is_operational")).join(
                activity, and_(activity.id == record.session_id, activity.agency_id == record.agency_id)).join(
                passenger, and_(passenger.id == record.passenger_id, passenger.agency_id == record.agency_id,
                                passenger.group_id == activity.group_id)).where(
                    activity.group_id == group_id, activity.agency_id == agency_id, record.agency_id == agency_id)
        if session_id is not None:
            query = query.where(record.session_id == session_id)
        return await self.page(query, record, **page)

    async def rooming(self, *, kind: str, group_id: uuid.UUID, agency_id: uuid.UUID,
                      hotel_id: uuid.UUID | None, **page: Any) -> list[dict[str, Any]]:
        hotel = RoomingHotelModel
        if kind == "hotels":
            model: Any = hotel
            query = select(hotel.id, hotel.hotel_name, hotel.city, hotel.check_in_date, hotel.check_out_date,
                hotel.allocation_revision, hotel.allocation_updated_at, hotel.created_at, hotel.updated_at)
        elif kind == "rooms":
            model = RoomingRoomModel
            query = select(model.id, model.hotel_id, model.room_number, model.room_type, model.capacity,
                model.allocation_tag, model.is_saved, model.sort_order, model.created_at, model.updated_at).join(hotel, hotel.id == model.hotel_id)
        elif kind == "selected_passengers":
            model = RoomingHotelPassengerModel
            query = select(model.id, model.hotel_id, model.passenger_id, model.is_vip, model.created_at,
                model.updated_at, self.operational(model.passenger_id, group_id, agency_id).label("passenger_is_operational")).join(
                    hotel, and_(hotel.id == model.hotel_id, hotel.group_id == model.group_id, hotel.agency_id == model.agency_id))
        elif kind == "allocations":
            model, room = RoomingAssignmentModel, RoomingRoomModel
            query = select(model.id, model.hotel_id, model.room_id, model.passenger_id, model.position,
                model.assigned_at.label("created_at"), self.operational(model.passenger_id, group_id, agency_id).label("passenger_is_operational")).join(
                    hotel, hotel.id == model.hotel_id).join(room, and_(room.id == model.room_id, room.hotel_id == model.hotel_id))
        else:
            model, room = RoomingCheckinModel, RoomingRoomModel
            query = select(model.id, model.hotel_id, model.room_id, model.passenger_id,
                model.checked_in, model.checked_in_at, model.key_issued, model.key_issued_at,
                model.welcome_letter_issued, model.welcome_letter_issued_at, model.created_at, model.updated_at,
                self.operational(model.passenger_id, group_id, agency_id).label("passenger_is_operational")).join(
                    hotel, and_(hotel.id == model.hotel_id, hotel.agency_id == model.agency_id)).join(
                    room, and_(room.id == model.room_id, room.hotel_id == model.hotel_id))
        query = query.where(hotel.group_id == group_id, hotel.agency_id == agency_id)
        if hotel_id is not None:
            query = query.where(hotel.id == hotel_id)
        if kind in {"selected_passengers", "allocations", "checkins"}:
            passenger = PassportSubmissionModel
            query = query.join(passenger, and_(passenger.id == model.passenger_id,
                passenger.group_id == hotel.group_id, passenger.agency_id == hotel.agency_id))
        return await self.page(query, model, timestamp=model.assigned_at if kind == "allocations" else None, **page)

    async def menu(self, *, kind: str, agency_id: uuid.UUID | None, category_id: uuid.UUID | None,
                   plan_id: uuid.UUID | None, include_inactive: bool, **page: Any) -> list[dict[str, Any]]:
        category, dish, plan, entry = MenuCategoryModel, MenuDishModel, MealPlanModel, MealPlanEntryModel
        query: Any
        if kind == "categories":
            model: Any = category
            scope = category.agency_id
            query = select(category.id, category.name, category.sort_order, category.created_at, category.updated_at)
            if category_id is not None:
                query = query.where(category.id == category_id)
        elif kind == "dishes":
            model, scope = dish, category.agency_id
            query = select(dish.id, dish.category_id, category.name.label("category_name"), dish.name,
                func.substr(dish.notes, 1, 2000).label("notes"), dish.is_active, dish.sort_order,
                dish.created_at, dish.updated_at).join(category, category.id == dish.category_id)
            if category_id is not None:
                query = query.where(dish.category_id == category_id)
            if not include_inactive:
                query = query.where(dish.is_active.is_(True))
        elif kind == "plans":
            model, scope = plan, plan.agency_id
            query = select(plan.id, plan.name, plan.trip_days, plan.start_date, plan.created_at, plan.updated_at)
            if plan_id is not None:
                query = query.where(plan.id == plan_id)
        else:
            model, scope = entry, plan.agency_id
            query = select(entry.id, entry.plan_id, entry.day_number, entry.meal_type, entry.dish_id,
                entry.category_id, entry.dish_name, entry.category_name, func.substr(entry.notes, 1, 2000).label("notes"),
                (func.length(entry.notes) > 2000).label("notes_truncated"), entry.created_at, entry.updated_at,
                plan.updated_at.label("plan_revision")).join(plan, plan.id == entry.plan_id).where(plan.id == plan_id)
        query = query.where(scope.is_(None) if agency_id is None else scope == agency_id)
        return await self.page(query, model, **page)

    async def directory(self, *, kind: str, agency_id: uuid.UUID | None,
                        include_inactive: bool, include_contact_details: bool, **page: Any) -> list[dict[str, Any]]:
        model: Any = AgencyModel if kind == "agencies" else UserModel
        if kind == "agencies":
            group, passport = ClientGroupModel, PassportSubmissionModel
            groups = select(func.count(group.id)).where(group.agency_id == model.id, group.deleted_at.is_(None), group.status != "deleted").scalar_subquery()
            raw = select(func.count(passport.id)).join(group, and_(group.id == passport.group_id, group.agency_id == passport.agency_id)).where(
                passport.agency_id == model.id, group.deleted_at.is_(None), group.status != "deleted").scalar_subquery()
            operational = select(func.count(passport.id)).join(group, and_(group.id == passport.group_id, group.agency_id == passport.agency_id)).where(
                passport.agency_id == model.id, group.deleted_at.is_(None), group.status != "deleted",
                passport.status.in_(OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES), operational_roster_member()).scalar_subquery()
            fields = [model.id, model.name, model.is_active, model.created_at, model.updated_at,
                groups.label("retained_group_count"), raw.label("passport_submission_count"), operational.label("operational_passenger_count")]
            if include_contact_details:
                fields += [model.email, model.phone]
        else:
            fields = [model.id, model.full_name, model.role, model.agency_id, model.is_active,
                      model.created_at, model.updated_at]
            if include_contact_details:
                fields += [model.email]
        query = select(*fields)
        if kind == "users":
            query = query.where(model.deleted_at.is_(None))
        if agency_id is not None:
            query = query.where((model.id if kind == "agencies" else model.agency_id) == agency_id)
        if not include_inactive:
            query = query.where(model.is_active.is_(True))
        return await self.page(query, model, **page)
