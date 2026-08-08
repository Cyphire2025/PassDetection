"""Notification query and response boundaries for Group Companion operations."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import String, cast, func, or_, select

from app.core.security.mobile_jwt import MobileAccessClaims
from app.infrastructure.database.gc_mobile_models import (
    ClientManagerGroupAssignmentModel,
    ClientManagerProfileModel,
    GCAnnouncementModel,
    GCGroupAccessModel,
    MobileNotificationModel,
    MobilePassengerIdentityModel,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    CoordinatorGroupAssignmentModel,
)
from app.presentation.api.v1.schemas.mobile_schemas import MobileNotificationResponse

_ANNOUNCEMENT_NOTIFICATION_TYPE = "group_announcement"


def _notification_recipient_filter(claims: MobileAccessClaims):
    if claims.principal_type == "passenger":
        return (
            (MobileNotificationModel.recipient_type == "passenger")
            & (MobileNotificationModel.recipient_passenger_identity_id == claims.principal_id)
            & MobileNotificationModel.recipient_user_id.is_(None)
        )
    return (
        (MobileNotificationModel.recipient_type == claims.principal_type)
        & (MobileNotificationModel.recipient_user_id == claims.principal_id)
        & MobileNotificationModel.recipient_passenger_identity_id.is_(None)
    )


def _published_announcement_notification_filter(agency_id: uuid.UUID):
    """Hide legacy notification rows whose source announcement is no longer published."""

    normalized_notification_source_id = func.replace(
        func.replace(
            MobileNotificationModel.dedupe_key,
            "announcement:",
            "",
        ),
        "-",
        "",
    )
    normalized_announcement_id = func.replace(
        cast(GCAnnouncementModel.id, String),
        "-",
        "",
    )
    current_announcement_exists = (
        select(GCAnnouncementModel.id)
        .where(
            GCAnnouncementModel.agency_id == agency_id,
            GCAnnouncementModel.agency_id == MobileNotificationModel.agency_id,
            GCAnnouncementModel.group_id == MobileNotificationModel.group_id,
            GCAnnouncementModel.gc_group_access_id
            == MobileNotificationModel.gc_group_access_id,
            GCAnnouncementModel.status == "published",
            normalized_announcement_id == normalized_notification_source_id,
        )
        .correlate(MobileNotificationModel)
        .exists()
    )
    return or_(
        MobileNotificationModel.notification_type
        != _ANNOUNCEMENT_NOTIFICATION_TYPE,
        current_announcement_exists,
    )


def _accessible_group_ids(claims: MobileAccessClaims, now: datetime):
    statement = (
        select(GCGroupAccessModel.group_id)
        .join(ClientGroupModel, ClientGroupModel.id == GCGroupAccessModel.group_id)
        .where(
            GCGroupAccessModel.agency_id == claims.agency_id,
            ClientGroupModel.agency_id == claims.agency_id,
            ClientGroupModel.status.in_(("active", "closed")),
            ClientGroupModel.deleted_at.is_(None),
            GCGroupAccessModel.is_enabled.is_(True),
            GCGroupAccessModel.revoked_at.is_(None),
            or_(
                GCGroupAccessModel.access_starts_at.is_(None),
                GCGroupAccessModel.access_starts_at <= now,
            ),
            or_(
                GCGroupAccessModel.access_expires_at.is_(None),
                GCGroupAccessModel.access_expires_at > now,
            ),
        )
    )
    if claims.principal_type == "passenger":
        statement = statement.join(
            MobilePassengerIdentityModel,
            MobilePassengerIdentityModel.gc_group_access_id == GCGroupAccessModel.id,
        ).where(
            GCGroupAccessModel.passenger_access_enabled.is_(True),
            MobilePassengerIdentityModel.id == claims.principal_id,
            MobilePassengerIdentityModel.status.in_(("eligible", "claimed")),
            MobilePassengerIdentityModel.revoked_at.is_(None),
        )
    elif claims.principal_type == "client_manager":
        statement = (
            statement.join(
                ClientManagerGroupAssignmentModel,
                ClientManagerGroupAssignmentModel.gc_group_access_id == GCGroupAccessModel.id,
            )
            .join(
                ClientManagerProfileModel,
                ClientManagerProfileModel.id == ClientManagerGroupAssignmentModel.profile_id,
            )
            .where(
                GCGroupAccessModel.client_manager_access_enabled.is_(True),
                ClientManagerProfileModel.user_id == claims.principal_id,
                ClientManagerProfileModel.status == "active",
                ClientManagerProfileModel.deleted_at.is_(None),
                ClientManagerGroupAssignmentModel.is_active.is_(True),
                ClientManagerGroupAssignmentModel.revoked_at.is_(None),
            )
        )
    else:
        statement = statement.join(
            CoordinatorGroupAssignmentModel,
            CoordinatorGroupAssignmentModel.group_id == GCGroupAccessModel.group_id,
        ).where(
            GCGroupAccessModel.coordinator_access_enabled.is_(True),
            CoordinatorGroupAssignmentModel.coordinator_user_id == claims.principal_id,
            CoordinatorGroupAssignmentModel.agency_id == claims.agency_id,
            CoordinatorGroupAssignmentModel.active.is_(True),
        )
    return statement.scalar_subquery()


def _notification_response(item: MobileNotificationModel) -> MobileNotificationResponse:
    return MobileNotificationResponse(
        id=item.id,
        trip_id=item.group_id,
        notification_type=item.notification_type,
        category=item.category,
        priority=_mobile_priority(item.priority),
        title=item.title,
        body=item.body,
        deep_link_path=item.deep_link_path,
        payload=_safe_public_payload(item.public_payload),
        available_at=item.available_at,
        expires_at=item.expires_at,
        read_at=item.read_at,
    )


def _safe_public_payload(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    safe: dict[str, object] = {}
    for key in ("screen", "group_id", "entity_id", "category"):
        item = value.get(key)
        if isinstance(item, (str, int, bool)) and len(str(item)) <= 512:
            safe[key] = item
    return safe


def _mobile_priority(value: str) -> str:
    if value == "emergency":
        return "emergency"
    if value == "high":
        return "important"
    return "normal"
