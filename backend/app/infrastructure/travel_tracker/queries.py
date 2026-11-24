"""Explicit actor/group scopes and canonical tracker SQL; no request callbacks."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import cast

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import ColumnElement

from app.application.dtos.travel_tracker import TrackerGroup, TrackerStatus, TrackerTrack
from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.travel_tracker import TravelTrackerError
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.database.travel_tracker_model import TravelTrackerModel
from app.infrastructure.repositories.operational_roster import operational_roster_member

TRACKER_ROLES = {
    UserRole.SUPER_ADMIN,
    UserRole.AGENCY_ADMIN,
    UserRole.AGENCY_MANAGER,
    UserRole.AGENCY_STAFF,
}


def require_role(user: User) -> None:
    if user.role not in TRACKER_ROLES:
        raise TravelTrackerError(status_code=403, detail="Insufficient permissions")


def group_query(
    user: User, allowed_group_ids: Sequence[uuid.UUID] | None
) -> Select[tuple[ClientGroupModel]]:
    require_role(user)
    statement = AuthorizationPolicy.apply_group_visibility_scope(
        select(ClientGroupModel).where(
            ClientGroupModel.deleted_at.is_(None), ClientGroupModel.status.in_(["active", "closed"])
        ),
        user,
    )
    if allowed_group_ids is not None:
        statement = statement.where(ClientGroupModel.id.in_(allowed_group_ids))
    return cast(Select[tuple[ClientGroupModel]], statement)


async def load_group(
    session: AsyncSession,
    user: User,
    allowed_group_ids: Sequence[uuid.UUID] | None,
    group_id: uuid.UUID,
    *,
    lock: bool = False,
) -> ClientGroupModel:
    statement = group_query(user, allowed_group_ids).where(ClientGroupModel.id == group_id)
    if lock:
        statement = statement.with_for_update(of=ClientGroupModel).execution_options(
            populate_existing=True
        )
    group = (await session.execute(statement)).scalar_one_or_none()
    if group is None:
        raise TravelTrackerError(status_code=404, detail="Client group was not found")
    return group


def tracker_join() -> ColumnElement[bool]:
    return and_(
        TravelTrackerModel.passenger_id == PassportSubmissionModel.id,
        TravelTrackerModel.group_id == PassportSubmissionModel.group_id,
        TravelTrackerModel.agency_id == PassportSubmissionModel.agency_id,
    )


# Include imported/collected members in every processing state, while
# preserving explicit canonical roster removals.
def roster(group: ClientGroupModel) -> Select[tuple[PassportSubmissionModel, TravelTrackerModel]]:
    return (
        select(PassportSubmissionModel, TravelTrackerModel)
        .outerjoin(TravelTrackerModel, tracker_join())
        .where(
            PassportSubmissionModel.group_id == group.id,
            PassportSubmissionModel.agency_id == group.agency_id,
            operational_roster_member(),
        )
    )


def validate_filters(track: str, status: str, search: str | None) -> None:
    if track not in {"visa", "flight"} or status not in {"all", "marked", "pending"}:
        raise TravelTrackerError(status_code=422, detail="Invalid tracker filter")
    if search is not None and len(search) > 160:
        raise TravelTrackerError(
            status_code=422, detail="Search can contain at most 160 characters"
        )


def validate_page(page: int, page_size: int, maximum: int = 200) -> None:
    if page < 1 or page > 100000 or page_size < 1 or (page_size > maximum):
        raise TravelTrackerError(status_code=422, detail="Invalid pagination")


def field_expression(key: str) -> ColumnElement[str]:
    return func.coalesce(
        PassportSubmissionModel.confirmed_fields[key].as_string(),
        PassportSubmissionModel.extracted_fields[key].as_string(),
        "",
    )


def filter_roster(
    statement: Select[tuple[PassportSubmissionModel, TravelTrackerModel]],
    *,
    track: TrackerTrack,
    status: TrackerStatus,
    search: str | None,
) -> Select[tuple[PassportSubmissionModel, TravelTrackerModel]]:
    validate_filters(track, status, search)
    flag = TravelTrackerModel.visa_applied if track == "visa" else TravelTrackerModel.flight_booked
    if status != "all":
        statement = statement.where(func.coalesce(flag, False).is_(status == "marked"))
    normalized = " ".join((search or "").split())
    if normalized:
        expression = func.trim(field_expression("given_names") + " " + field_expression("surname"))
        statement = statement.where(
            or_(
                PassportSubmissionModel.client_name.icontains(normalized, autoescape=True),
                PassportSubmissionModel.client_email.icontains(normalized, autoescape=True),
                PassportSubmissionModel.client_phone.icontains(normalized, autoescape=True),
                field_expression("passport_number").icontains(normalized, autoescape=True),
                expression.icontains(normalized, autoescape=True),
            )
        )
    return statement


async def group_summary(
    session: AsyncSession, groups: list[ClientGroupModel]
) -> dict[uuid.UUID, TrackerGroup]:
    counts = {}
    if groups:
        statement = (
            select(
                PassportSubmissionModel.group_id,
                func.count(PassportSubmissionModel.id),
                func.sum(case((TravelTrackerModel.visa_applied.is_(True), 1), else_=0)),
                func.sum(case((TravelTrackerModel.flight_booked.is_(True), 1), else_=0)),
            )
            .outerjoin(TravelTrackerModel, tracker_join())
            .where(
                PassportSubmissionModel.group_id.in_([group.id for group in groups]),
                operational_roster_member(),
            )
            .group_by(PassportSubmissionModel.group_id)
        )
        counts = {
            group_id: (int(total), int(visa or 0), int(flight or 0))
            for group_id, total, visa, flight in (await session.execute(statement)).all()
        }
    output = {}
    for group in groups:
        total, visa, flight = counts.get(group.id, (0, 0, 0))
        output[group.id] = TrackerGroup(
            id=group.id,
            name=group.name,
            destination=group.destination,
            travel_date=group.travel_date,
            return_date=group.return_date,
            status=group.status,
            total=total,
            visa_marked=visa,
            flight_marked=flight,
        )
    return output
