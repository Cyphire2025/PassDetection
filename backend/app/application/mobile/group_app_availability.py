"""Authoritative app availability, independent of collection-link acceptance."""

from datetime import UTC, datetime
from typing import Literal, TypedDict

from sqlalchemy import and_, case, or_
from sqlalchemy.sql.elements import ColumnElement

from app.infrastructure.database.gc_mobile_models import GCGroupAccessModel
from app.infrastructure.database.models import ClientGroupModel

GCAppAvailability = Literal["active", "scheduled", "paused", "ended", "unavailable"]
GCAppAvailabilityReason = Literal[
    "group_deleted",
    "group_archived",
    "group_unavailable",
    "not_configured",
    "app_disabled",
    "access_revoked",
    "no_roles_enabled",
    "access_ended",
    "access_not_started",
]


class GCAppAvailabilityValues(TypedDict):
    app_availability: GCAppAvailability
    app_availability_reason: GCAppAvailabilityReason | None
    app_availability_evaluated_at: datetime


def group_can_enable_mobile_access(group: ClientGroupModel) -> bool:
    return group.status in {"active", "closed"} and group.deleted_at is None


def availability_fields(
    group: ClientGroupModel, access: GCGroupAccessModel | None, *, now: datetime
) -> GCAppAvailabilityValues:
    state, reason = _availability(group, access, now=now)
    return {
        "app_availability": state,
        "app_availability_reason": reason,
        "app_availability_evaluated_at": now,
    }


def _availability(
    group: ClientGroupModel, access: GCGroupAccessModel | None, *, now: datetime
) -> tuple[GCAppAvailability, GCAppAvailabilityReason | None]:
    if group.deleted_at is not None or group.status == "deleted":
        return "unavailable", "group_deleted"
    if group.status == "archived":
        return "unavailable", "group_archived"
    if not group_can_enable_mobile_access(group):
        return "unavailable", "group_unavailable"
    if access is None or access.removed_at is not None:
        return "unavailable", "not_configured"
    if not access.is_enabled:
        return "paused", "app_disabled"
    if access.revoked_at is not None:
        return "paused", "access_revoked"
    if not (
        access.passenger_access_enabled
        or access.client_manager_access_enabled
        or access.coordinator_access_enabled
    ):
        return "paused", "no_roles_enabled"
    if access.access_expires_at is not None and _aware_utc(access.access_expires_at) <= now:
        return "ended", "access_ended"
    if access.access_starts_at is not None and _aware_utc(access.access_starts_at) > now:
        return "scheduled", "access_not_started"
    return "active", None


def availability_filter(value: GCAppAvailability, *, now: datetime) -> ColumnElement[bool]:
    """Mirror the projection precedence in SQL before counting/paginating."""
    return (
        case(
            (
                or_(
                    ClientGroupModel.status.not_in(("active", "closed")),
                    ClientGroupModel.deleted_at.is_not(None),
                    GCGroupAccessModel.id.is_(None),
                    GCGroupAccessModel.removed_at.is_not(None),
                ),
                "unavailable",
            ),
            (
                or_(
                    GCGroupAccessModel.is_enabled.is_(False),
                    GCGroupAccessModel.revoked_at.is_not(None),
                    and_(
                        GCGroupAccessModel.passenger_access_enabled.is_(False),
                        GCGroupAccessModel.client_manager_access_enabled.is_(False),
                        GCGroupAccessModel.coordinator_access_enabled.is_(False),
                    ),
                ),
                "paused",
            ),
            (GCGroupAccessModel.access_expires_at <= now, "ended"),
            (GCGroupAccessModel.access_starts_at > now, "scheduled"),
            else_="active",
        )
        == value
    )


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
