"""Page current countdown recipients and persist deduplicated rows."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.application.mobile.notification_contracts import _RECIPIENT_PAGE_SIZE
from app.application.mobile.notification_countdown_values import _countdown_notification_values
from app.application.mobile.passenger_notification_authority import retain_recipient_ids
from app.infrastructure.database.gc_mobile_models import (
    ClientManagerGroupAssignmentModel,
    ClientManagerProfileModel,
    GCGroupAccessModel,
    MobileNotificationModel,
    MobilePassengerIdentityModel,
)
from app.infrastructure.database.models import CoordinatorGroupAssignmentModel, UserModel


async def _enqueue_countdown_recipients(
    session: AsyncSession,
    *,
    access: GCGroupAccessModel,
    travel_date: date,
    timezone_name: str,
    days_remaining: int,
    available_at: datetime,
    expires_at: datetime,
) -> int:
    inserted = 0
    if access.passenger_access_enabled:
        inserted += await _enqueue_countdown_pages(
            session,
            statement=select(MobilePassengerIdentityModel.id).where(
                MobilePassengerIdentityModel.agency_id == access.agency_id,
                MobilePassengerIdentityModel.gc_group_access_id == access.id,
                MobilePassengerIdentityModel.group_id == access.group_id,
                MobilePassengerIdentityModel.status.in_(("eligible", "claimed")),
                MobilePassengerIdentityModel.revoked_at.is_(None),
            ),
            id_column=MobilePassengerIdentityModel.id,
            recipient_type="passenger",
            access=access,
            travel_date=travel_date,
            timezone_name=timezone_name,
            days_remaining=days_remaining,
            available_at=available_at,
            expires_at=expires_at,
        )
    if access.client_manager_access_enabled:
        inserted += await _enqueue_countdown_pages(
            session,
            statement=(
                select(UserModel.id)
                .join(
                    ClientManagerProfileModel,
                    ClientManagerProfileModel.user_id == UserModel.id,
                )
                .join(
                    ClientManagerGroupAssignmentModel,
                    ClientManagerGroupAssignmentModel.profile_id == ClientManagerProfileModel.id,
                )
                .where(
                    UserModel.agency_id == access.agency_id,
                    UserModel.role == "client_manager",
                    UserModel.is_active.is_(True),
                    UserModel.deleted_at.is_(None),
                    ClientManagerProfileModel.agency_id == access.agency_id,
                    ClientManagerProfileModel.status == "active",
                    ClientManagerProfileModel.deleted_at.is_(None),
                    ClientManagerGroupAssignmentModel.agency_id == access.agency_id,
                    ClientManagerGroupAssignmentModel.gc_group_access_id == access.id,
                    ClientManagerGroupAssignmentModel.group_id == access.group_id,
                    ClientManagerGroupAssignmentModel.is_active.is_(True),
                    ClientManagerGroupAssignmentModel.revoked_at.is_(None),
                )
            ),
            id_column=UserModel.id,
            recipient_type="client_manager",
            access=access,
            travel_date=travel_date,
            timezone_name=timezone_name,
            days_remaining=days_remaining,
            available_at=available_at,
            expires_at=expires_at,
        )
    if access.coordinator_access_enabled:
        inserted += await _enqueue_countdown_pages(
            session,
            statement=(
                select(UserModel.id)
                .join(
                    CoordinatorGroupAssignmentModel,
                    CoordinatorGroupAssignmentModel.coordinator_user_id == UserModel.id,
                )
                .where(
                    UserModel.agency_id == access.agency_id,
                    UserModel.role == "agency_coordinator",
                    UserModel.is_active.is_(True),
                    UserModel.deleted_at.is_(None),
                    CoordinatorGroupAssignmentModel.agency_id == access.agency_id,
                    CoordinatorGroupAssignmentModel.group_id == access.group_id,
                    CoordinatorGroupAssignmentModel.active.is_(True),
                )
            ),
            id_column=UserModel.id,
            recipient_type="coordinator",
            access=access,
            travel_date=travel_date,
            timezone_name=timezone_name,
            days_remaining=days_remaining,
            available_at=available_at,
            expires_at=expires_at,
        )
    return inserted


async def _enqueue_countdown_pages(
    session: AsyncSession,
    *,
    statement: Select[tuple[uuid.UUID]],
    id_column: InstrumentedAttribute[uuid.UUID],
    recipient_type: Literal["passenger", "client_manager", "coordinator"],
    access: GCGroupAccessModel,
    travel_date: date,
    timezone_name: str,
    days_remaining: int,
    available_at: datetime,
    expires_at: datetime,
) -> int:
    cursor: uuid.UUID | None = None
    inserted = 0
    while True:
        page_statement = statement
        if cursor is not None:
            page_statement = page_statement.where(id_column > cursor)
        ids = list(
            (
                await session.execute(
                    page_statement.order_by(id_column.asc()).limit(_RECIPIENT_PAGE_SIZE)
                )
            ).scalars()
        )
        if not ids:
            break
        allowed_ids = await retain_recipient_ids(
            session, recipient_ids=ids, recipient_type=recipient_type, access=access
        )
        rows = [
            _countdown_notification_values(
                recipient_id=recipient_id,
                recipient_type=recipient_type,
                access=access,
                travel_date=travel_date,
                timezone_name=timezone_name,
                days_remaining=days_remaining,
                available_at=available_at,
                expires_at=expires_at,
            )
            for recipient_id in allowed_ids
        ]
        inserted += await _insert_notifications_ignore_duplicates(session, rows=rows)
        cursor = ids[-1]
        if len(ids) < _RECIPIENT_PAGE_SIZE:
            break
    return inserted


async def _insert_notifications_ignore_duplicates(
    session: AsyncSession,
    *,
    rows: list[dict[str, object]],
) -> int:
    if not rows:
        return 0
    dialect_name = session.get_bind().dialect.name
    if dialect_name == "postgresql":
        result = await session.execute(
            postgresql_insert(MobileNotificationModel).values(rows).on_conflict_do_nothing()
        )
    elif dialect_name == "sqlite":
        result = await session.execute(
            sqlite_insert(MobileNotificationModel).values(rows).on_conflict_do_nothing()
        )
    else:
        raise RuntimeError("Countdown scheduling requires PostgreSQL or SQLite")
    return max(0, int(getattr(result, "rowcount", 0) or 0))
