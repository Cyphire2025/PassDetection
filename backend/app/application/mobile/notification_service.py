"""Durable, tenant-scoped mobile notification production and delivery."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cryptography.fernet import InvalidToken
from sqlalchemy import Select, and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, undefer

from app.application.mobile.push_provider import MobilePushMessage, MobilePushProvider
from app.core.security.mobile_push_crypto import mobile_push_fernet
from app.infrastructure.database.gc_mobile_models import (
    ClientManagerGroupAssignmentModel,
    ClientManagerProfileModel,
    GCAnnouncementModel,
    GCGroupAccessModel,
    MobileDeviceSessionModel,
    MobileNotificationModel,
    MobilePassengerIdentityModel,
    MobilePushRegistrationModel,
)
from app.infrastructure.database.models import CoordinatorGroupAssignmentModel, UserModel

_RECIPIENT_PAGE_SIZE = 250
_NOTIFICATION_TYPE = "group_announcement"
_LOCK_SCREEN_TITLE = "Group Companion update"
_ALLOWED_PUSH_ROUTES = frozenset(
    {"trip", "documents", "qr", "updates", "readiness", "attendance", "passengers"}
)


@dataclass(frozen=True, slots=True)
class AnnouncementNotificationCounts:
    passengers: int = 0
    client_managers: int = 0
    coordinators: int = 0

    @property
    def total(self) -> int:
        return self.passengers + self.client_managers + self.coordinators


async def enqueue_announcement_notifications(
    session: AsyncSession,
    *,
    access: GCGroupAccessModel,
    announcement: GCAnnouncementModel,
    now: datetime | None = None,
) -> AnnouncementNotificationCounts:
    """Create one deduplicated feed row per currently authorized principal."""

    current = now or datetime.now(tz=UTC)
    if not access.is_enabled or access.revoked_at is not None:
        return AnnouncementNotificationCounts()
    available_at = max(
        value
        for value in (current, access.access_starts_at, announcement.availability_starts_at)
        if value is not None
    )
    expiry_candidates = [
        value
        for value in (access.access_expires_at, announcement.availability_expires_at)
        if value is not None
    ]
    expires_at = min(expiry_candidates) if expiry_candidates else None
    if expires_at is not None and expires_at <= available_at:
        return AnnouncementNotificationCounts()

    passengers = 0
    managers = 0
    coordinators = 0
    if access.passenger_access_enabled and announcement.passenger_visible:
        passengers = await _enqueue_recipient_pages(
            session,
            statement=select(MobilePassengerIdentityModel.id).where(
                MobilePassengerIdentityModel.agency_id == access.agency_id,
                MobilePassengerIdentityModel.gc_group_access_id == access.id,
                MobilePassengerIdentityModel.group_id == access.group_id,
                MobilePassengerIdentityModel.status.in_(("eligible", "claimed")),
            ),
            id_column=MobilePassengerIdentityModel.id,
            recipient_type="passenger",
            access=access,
            announcement=announcement,
            available_at=available_at,
            expires_at=expires_at,
        )
    if access.client_manager_access_enabled and announcement.client_manager_visible:
        managers = await _enqueue_recipient_pages(
            session,
            statement=(
                select(UserModel.id)
                .join(
                    ClientManagerProfileModel,
                    ClientManagerProfileModel.user_id == UserModel.id,
                )
                .join(
                    ClientManagerGroupAssignmentModel,
                    ClientManagerGroupAssignmentModel.profile_id
                    == ClientManagerProfileModel.id,
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
            announcement=announcement,
            available_at=available_at,
            expires_at=expires_at,
        )
    if access.coordinator_access_enabled and announcement.coordinator_visible:
        coordinators = await _enqueue_recipient_pages(
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
            announcement=announcement,
            available_at=available_at,
            expires_at=expires_at,
        )
    return AnnouncementNotificationCounts(
        passengers=passengers,
        client_managers=managers,
        coordinators=coordinators,
    )


async def cancel_announcement_notifications(
    session: AsyncSession,
    *,
    access: GCGroupAccessModel,
    announcement_id: uuid.UUID,
    now: datetime | None = None,
) -> int:
    """Cancel announcement pushes that have not left the durable queue."""

    result = await session.execute(
        update(MobileNotificationModel)
        .where(
            MobileNotificationModel.agency_id == access.agency_id,
            MobileNotificationModel.gc_group_access_id == access.id,
            MobileNotificationModel.dedupe_key == _announcement_dedupe_key(announcement_id),
            MobileNotificationModel.status == "queued",
        )
        .values(
            status="cancelled",
            failure_code="announcement_unpublished",
            updated_at=now or datetime.now(tz=UTC),
        )
        .execution_options(synchronize_session=False)
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def dispatch_mobile_push_batch(
    session: AsyncSession,
    *,
    provider: MobilePushProvider,
    limit: int,
    now: datetime | None = None,
) -> int:
    """Deliver a bounded locked batch; a disabled provider changes no state."""

    if not provider.enabled:
        return 0
    if limit < 1 or limit > 100:
        raise ValueError("Mobile push batch limit must be between 1 and 100")
    current = now or datetime.now(tz=UTC)
    notifications = list(
        (
            await session.execute(
                select(MobileNotificationModel)
                .where(
                    MobileNotificationModel.status == "queued",
                    MobileNotificationModel.available_at <= current,
                    or_(
                        MobileNotificationModel.expires_at.is_(None),
                        MobileNotificationModel.expires_at > current,
                    ),
                )
                .order_by(
                    MobileNotificationModel.available_at.asc(),
                    MobileNotificationModel.id.asc(),
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).scalars()
    )
    if not notifications:
        return 0

    registrations = await _load_recipient_registrations(
        session,
        notifications=notifications,
        provider_name=provider.name,
        now=current,
    )
    messages: list[MobilePushMessage] = []
    registration_by_id: dict[str, MobilePushRegistrationModel] = {}
    notification_by_id = {str(item.id): item for item in notifications}
    for notification in notifications:
        key = _notification_recipient_key(notification)
        for registration in registrations.get(key, []):
            if len(messages) >= limit:
                break
            try:
                token = mobile_push_fernet().decrypt(registration.token_ciphertext).decode(
                    "utf-8"
                )
                data = _validated_public_payload(notification)
            except (InvalidToken, UnicodeDecodeError):
                registration.status = "disabled"
                registration.last_failure_at = current
                registration.last_failure_code = "token_decryption_failed"
                registration.updated_at = current
                continue
            except ValueError:
                notification.failure_code = "invalid_public_payload"
                notification.available_at = current + timedelta(days=1)
                notification.updated_at = current
                continue
            message = MobilePushMessage(
                registration_id=str(registration.id),
                notification_id=str(notification.id),
                token=token,
                title=notification.lock_screen_title or _LOCK_SCREEN_TITLE,
                body=(
                    None
                    if notification.contains_sensitive_content
                    else notification.lock_screen_body
                ),
                data=data,
                priority="high" if notification.priority in {"high", "emergency"} else "default",
            )
            messages.append(message)
            registration_by_id[str(registration.id)] = registration
        if len(messages) >= limit:
            break

    if not messages:
        for notification in notifications:
            if notification.failure_code is None:
                notification.failure_code = "no_active_registration"
                notification.available_at = current + timedelta(minutes=5)
                notification.updated_at = current
        return 0

    tickets = await provider.send(messages)
    accepted_notifications: set[str] = set()
    retryable_notifications: set[str] = set()
    attempted_notifications: set[str] = set()
    permanent_error_by_notification: dict[str, str] = {}
    for ticket in tickets:
        ticket_notification = notification_by_id.get(ticket.notification_id)
        ticket_registration = registration_by_id.get(ticket.registration_id)
        if ticket_notification is None or ticket_registration is None:
            continue
        attempted_notifications.add(ticket.notification_id)
        if ticket.accepted:
            accepted_notifications.add(ticket.notification_id)
            ticket_registration.last_success_at = current
            ticket_registration.last_failure_code = None
        else:
            code = ticket.error_code or "provider_ticket_error"
            ticket_registration.last_failure_at = current
            ticket_registration.last_failure_code = code
            permanent_error_by_notification[ticket.notification_id] = code
            if code == "DeviceNotRegistered":
                ticket_registration.status = "revoked"
                ticket_registration.notifications_authorized = False
                ticket_registration.revoked_at = current
            elif ticket.retryable:
                retryable_notifications.add(ticket.notification_id)
        ticket_registration.updated_at = current

    for notification_id in attempted_notifications:
        notification = notification_by_id[notification_id]
        if notification_id in accepted_notifications:
            notification.status = "sent"
            notification.sent_at = current
            notification.failure_code = None
        elif notification_id in retryable_notifications:
            notification.status = "queued"
            notification.available_at = current + timedelta(minutes=1)
            notification.failure_code = permanent_error_by_notification.get(
                notification_id,
                "provider_unavailable",
            )
        else:
            notification.status = "failed"
            notification.failure_code = permanent_error_by_notification.get(
                notification_id,
                "provider_rejected",
            )
        notification.updated_at = current
    return len(accepted_notifications)


async def _enqueue_recipient_pages(
    session: AsyncSession,
    *,
    statement: Select[tuple[uuid.UUID]],
    id_column: InstrumentedAttribute[uuid.UUID],
    recipient_type: str,
    access: GCGroupAccessModel,
    announcement: GCAnnouncementModel,
    available_at: datetime,
    expires_at: datetime | None,
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
                    page_statement.order_by(id_column.asc()).limit(
                        _RECIPIENT_PAGE_SIZE
                    )
                )
            ).scalars()
        )
        if not ids:
            break
        for recipient_id in ids:
            session.add(
                _announcement_notification(
                    recipient_id=recipient_id,
                    recipient_type=recipient_type,
                    access=access,
                    announcement=announcement,
                    available_at=available_at,
                    expires_at=expires_at,
                )
            )
        await session.flush()
        inserted += len(ids)
        cursor = ids[-1]
        if len(ids) < _RECIPIENT_PAGE_SIZE:
            break
    return inserted


def _announcement_notification(
    *,
    recipient_id: uuid.UUID,
    recipient_type: str,
    access: GCGroupAccessModel,
    announcement: GCAnnouncementModel,
    available_at: datetime,
    expires_at: datetime | None,
) -> MobileNotificationModel:
    is_passenger = recipient_type == "passenger"
    return MobileNotificationModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        group_id=access.group_id,
        gc_group_access_id=access.id,
        recipient_type=recipient_type,
        recipient_user_id=None if is_passenger else recipient_id,
        recipient_passenger_identity_id=recipient_id if is_passenger else None,
        notification_type=_NOTIFICATION_TYPE,
        category=("announcement" if announcement.category == "general" else announcement.category),
        priority=announcement.priority,
        title=announcement.title,
        body=announcement.body,
        lock_screen_title=_LOCK_SCREEN_TITLE,
        lock_screen_body=None,
        contains_sensitive_content=True,
        deep_link_path=(
            f"/updates?trip_id={access.group_id}&event_id={announcement.id}"
        ),
        dedupe_key=_announcement_dedupe_key(announcement.id),
        public_payload={
            "route": "updates",
            "trip_id": str(access.group_id),
            "event_id": str(announcement.id),
        },
        status="queued",
        available_at=available_at,
        expires_at=expires_at,
    )


async def _load_recipient_registrations(
    session: AsyncSession,
    *,
    notifications: list[MobileNotificationModel],
    provider_name: str,
    now: datetime,
) -> dict[tuple[str, uuid.UUID, uuid.UUID], list[MobilePushRegistrationModel]]:
    user_ids = {
        item.recipient_user_id
        for item in notifications
        if item.recipient_user_id is not None
    }
    passenger_ids = {
        item.recipient_passenger_identity_id
        for item in notifications
        if item.recipient_passenger_identity_id is not None
    }
    if not user_ids and not passenger_ids:
        return {}
    recipient_filter = or_(
        and_(
            MobileDeviceSessionModel.subject_role.in_(("client_manager", "coordinator")),
            MobileDeviceSessionModel.user_id.in_(user_ids),
        ),
        and_(
            MobileDeviceSessionModel.subject_role == "passenger",
            MobileDeviceSessionModel.passenger_identity_id.in_(passenger_ids),
        ),
    )
    rows = list(
        (
            await session.execute(
                select(MobilePushRegistrationModel, MobileDeviceSessionModel)
                .options(undefer(MobilePushRegistrationModel.token_ciphertext))
                .join(
                    MobileDeviceSessionModel,
                    and_(
                        MobileDeviceSessionModel.id == MobilePushRegistrationModel.session_id,
                        MobileDeviceSessionModel.agency_id == MobilePushRegistrationModel.agency_id,
                    ),
                )
                .where(
                    MobilePushRegistrationModel.provider == provider_name,
                    MobilePushRegistrationModel.status == "active",
                    MobilePushRegistrationModel.notifications_authorized.is_(True),
                    MobileDeviceSessionModel.status == "active",
                    MobileDeviceSessionModel.revoked_at.is_(None),
                    MobileDeviceSessionModel.expires_at > now,
                    recipient_filter,
                )
                .order_by(MobilePushRegistrationModel.last_registered_at.desc())
            )
        ).all()
    )
    result: dict[
        tuple[str, uuid.UUID, uuid.UUID],
        list[MobilePushRegistrationModel],
    ] = {}
    for registration, device_session in rows:
        principal_id = (
            device_session.passenger_identity_id
            if device_session.subject_role == "passenger"
            else device_session.user_id
        )
        if principal_id is None:
            continue
        key = (device_session.subject_role, principal_id, device_session.agency_id)
        result.setdefault(key, []).append(registration)
    return result


def _notification_recipient_key(
    notification: MobileNotificationModel,
) -> tuple[str, uuid.UUID, uuid.UUID]:
    principal_id = (
        notification.recipient_passenger_identity_id
        if notification.recipient_type == "passenger"
        else notification.recipient_user_id
    )
    if principal_id is None:
        raise ValueError("Notification recipient was malformed")
    return (notification.recipient_type, principal_id, notification.agency_id)


def _validated_public_payload(notification: MobileNotificationModel) -> dict[str, str]:
    payload = notification.public_payload
    if not isinstance(payload, dict) or set(payload) - {"route", "trip_id", "event_id"}:
        raise ValueError("Notification public payload was malformed")
    route = payload.get("route")
    trip_id = payload.get("trip_id")
    event_id = payload.get("event_id")
    if route not in _ALLOWED_PUSH_ROUTES or trip_id != str(notification.group_id):
        raise ValueError("Notification public payload was out of scope")
    try:
        uuid.UUID(str(trip_id))
        if event_id is not None:
            uuid.UUID(str(event_id))
    except (TypeError, ValueError) as exc:
        raise ValueError("Notification public payload contained an invalid identifier") from exc
    result = {"route": str(route), "trip_id": str(trip_id)}
    if event_id is not None:
        result["event_id"] = str(event_id)
    return result


def _announcement_dedupe_key(announcement_id: uuid.UUID) -> str:
    return f"announcement:{announcement_id}"


__all__ = [
    "AnnouncementNotificationCounts",
    "cancel_announcement_notifications",
    "dispatch_mobile_push_batch",
    "enqueue_announcement_notifications",
]
