"""Notification query and response boundaries for Group Companion operations."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import String, cast, false, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import ScalarSelect

from app.application.mobile.authored_notification_audience import collect_notification_audience
from app.core.security.mobile_jwt import MobileAccessClaims
from app.infrastructure.database.gc_mobile_models import (
    ClientManagerGroupAssignmentModel,
    ClientManagerProfileModel,
    GCAnnouncementModel,
    GCGroupAccessModel,
    MobileNotificationModel,
    MobilePassengerIdentityModel,
    MobilePassengerSessionIdentityModel,
)
from app.infrastructure.database.gc_notification_models import (
    GCNotificationRecipientGrantModel,
    GCNotificationRecipientModel,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    CoordinatorGroupAssignmentModel,
)
from app.infrastructure.repositories.coordinator_assignment_lifecycle import (
    expired_trip_clause,
)
from app.presentation.api.v1.schemas.mobile_schemas import MobileNotificationResponse

_ANNOUNCEMENT_NOTIFICATION_TYPE = "group_announcement"


async def authored_notification_filter(
    session: AsyncSession, claims: MobileAccessClaims, now: datetime
) -> ColumnElement[bool]:
    """Resolve current session authority once; filter every historical batch in SQL."""
    group_ids: list[uuid.UUID] | None = None
    principal_ids = {claims.principal_id}
    bindings: dict[uuid.UUID, MobilePassengerSessionIdentityModel] = {}
    if claims.principal_type == "passenger":
        rows = (
            await session.execute(
                select(MobilePassengerSessionIdentityModel).where(
                    MobilePassengerSessionIdentityModel.session_id == claims.session_id,
                    MobilePassengerSessionIdentityModel.agency_id == claims.agency_id,
                )
            )
        ).scalars()
        bindings = {row.passenger_identity_id: row for row in rows}
        principal_ids = set(bindings)
        group_ids = list({row.group_id for row in bindings.values()})
    if not principal_ids:
        return false()
    audience = await collect_notification_audience(
        session,
        agency_id=claims.agency_id,
        group_ids=group_ids,
        principal_ids=principal_ids,
        now=now,
    )
    grants = [grant for grant in audience.grants if grant.role == claims.principal_type]
    if claims.principal_type == "passenger":
        grants = [
            grant
            for grant in grants
            if (binding := bindings.get(grant.principal_id)) is not None
            and binding.identity_claim_generation == grant.claim_generation
            and binding.gc_group_access_id == grant.access_id
            and binding.group_id == grant.group_id
        ]
    if not grants:
        return false()
    Grant, Recipient = GCNotificationRecipientGrantModel, GCNotificationRecipientModel
    columns = (
        Grant.principal_id,
        Grant.group_id,
        Grant.gc_group_access_id,
        Grant.access_generation,
        Recipient.person_key,
    )
    values = [
        (
            grant.principal_id,
            grant.group_id,
            grant.access_id,
            grant.access_generation,
            grant.person_key,
        )
        for grant in grants
    ]
    live_grant = tuple_(*columns).in_(values)
    if claims.principal_type == "passenger":
        live_grant = tuple_(*columns, Grant.identity_claim_generation).in_(
            [(*value, grant.claim_generation) for value, grant in zip(values, grants, strict=True)]
        )
    exists = (
        select(Grant.id)
        .join(
            Recipient,
            (Recipient.id == Grant.recipient_id) & (Recipient.agency_id == Grant.agency_id),
        )
        .where(
            Recipient.id == MobileNotificationModel.authored_recipient_id,
            Recipient.agency_id == claims.agency_id,
            Recipient.recipient_type == claims.principal_type,
            MobileNotificationModel.notification_type == "gc_alert",
            live_grant,
        )
        .correlate(MobileNotificationModel)
        .exists()
    )
    return exists


def _notification_recipient_filter(claims: MobileAccessClaims) -> ColumnElement[bool]:
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


def _published_announcement_notification_filter(
    agency_id: uuid.UUID,
) -> ColumnElement[bool]:
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
            GCAnnouncementModel.gc_group_access_id == MobileNotificationModel.gc_group_access_id,
            GCAnnouncementModel.status == "published",
            normalized_announcement_id == normalized_notification_source_id,
        )
        .correlate(MobileNotificationModel)
        .exists()
    )
    return or_(
        MobileNotificationModel.notification_type != _ANNOUNCEMENT_NOTIFICATION_TYPE,
        current_announcement_exists,
    )


def _accessible_group_ids(
    claims: MobileAccessClaims,
    now: datetime,
) -> ScalarSelect[uuid.UUID]:
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
            ~expired_trip_clause(now),
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


def _mobile_priority(
    value: str,
) -> Literal["normal", "important", "emergency"]:
    if value == "emergency":
        return "emergency"
    if value == "high":
        return "important"
    return "normal"
