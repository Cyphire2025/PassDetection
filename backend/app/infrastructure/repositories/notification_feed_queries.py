"""Shared direct-recipient predicates, ordering and unread-count semantics."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.sql.elements import ColumnElement

from app.infrastructure.database.models import NotificationModel


def direct_predicates(user_id: UUID, agency_id: UUID | None) -> list[ColumnElement[bool]]:
    predicates = [NotificationModel.user_id == user_id]
    if agency_id is not None:
        predicates.append(NotificationModel.agency_id == agency_id)
    return predicates


def direct_feed_query(
    *, user_id: UUID, agency_id: UUID | None, unread_only: bool = False,
    priority: str | None = None, after: tuple[datetime, UUID] | None = None,
    cutoff: datetime | None = None, limit: int = 30,
) -> Select[tuple[NotificationModel]]:
    predicates = direct_predicates(user_id, agency_id)
    if unread_only:
        predicates.append(NotificationModel.is_read.is_(False))
    if priority is not None:
        predicates.append(NotificationModel.priority == priority)
    if cutoff is not None:
        predicates.append(NotificationModel.created_at <= cutoff)
    if after is not None:
        stamp, identifier = after
        predicates.append(or_(NotificationModel.created_at < stamp, and_(
            NotificationModel.created_at == stamp, NotificationModel.id < identifier)))
    return select(NotificationModel).where(*predicates).order_by(
        NotificationModel.created_at.desc(), NotificationModel.id.desc()).limit(limit + 1)


def direct_unread_count(user_id: UUID, agency_id: UUID | None) -> Select[tuple[int]]:
    # The website badge ignores page/priority filters and counts all personal
    # unread rows in the actor's scope.
    return select(func.count(NotificationModel.id)).where(
        *direct_predicates(user_id, agency_id), NotificationModel.is_read.is_(False))
