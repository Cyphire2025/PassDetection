"""Durable, tenant-scoped mobile notification production and delivery."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from cryptography.fernet import InvalidToken
from sqlalchemy import Select, and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
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
    MobilePushDeliveryModel,
    MobilePushRegistrationModel,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    CoordinatorGroupAssignmentModel,
    UserModel,
)
from app.infrastructure.observability.operational_events import (
    OperationalEvent,
    record_operational_event,
)

_RECIPIENT_PAGE_SIZE = 250
_COUNTDOWN_CLEANUP_PAGE_SIZE = 1_000
_NOTIFICATION_TYPE = "group_announcement"
_COUNTDOWN_NOTIFICATION_TYPE = "trip_countdown"
_LOCK_SCREEN_TITLE = "Group Companion update"
_COUNTDOWN_DAYS = (3, 2, 1)
_COUNTDOWN_TEMPLATES: dict[int, tuple[tuple[str, str], ...]] = {
    3: (
        ("Three days to go ✈️", "Shopping done, or is the suitcase still waiting?"),
        ("Your trip is almost here 🌍", "Time to finish the last-minute checklist."),
        ("Three sleeps left", "Tickets, outfits and excitement ready?"),
    ),
    2: (
        ("Two days left 🧳", "Your suitcase would like some attention."),
        ("Almost boarding time", "Pack the essentials and save space for memories."),
        ("Two days to go ✨", "Time to turn that packing list into an actual packed bag."),
    ),
    1: (
        ("Tomorrow is the day ✈️", "Keep your passport, visa and tickets close."),
        ("One more sleep", "Check your documents and charge your phone."),
        ("Adventure starts tomorrow 🌍", "Documents ready? Bags zipped? Let's go."),
    ),
}
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


@dataclass(frozen=True, slots=True)
class DocumentChangeNotificationCounts:
    """Role-scoped, PII-free notification counts for a document mutation."""

    passengers: int = 0
    client_managers: int = 0
    coordinators: int = 0

    @property
    def total(self) -> int:
        return self.passengers + self.client_managers + self.coordinators


@dataclass(frozen=True, slots=True)
class CountdownNotificationCounts:
    """Bounded scheduler result without recipient or trip identifiers."""

    inserted: int = 0
    cancelled: int = 0
    groups_scanned: int = 0


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


async def enqueue_personal_document_change_notifications(
    session: AsyncSession,
    *,
    access: GCGroupAccessModel,
    passenger_identity_ids: Sequence[uuid.UUID],
    operation: Literal["upsert", "delete"],
    dedupe_token: str,
    now: datetime | None = None,
) -> DocumentChangeNotificationCounts:
    """Queue generic refresh triggers without leaking passenger/document details.

    Passengers are targeted only by their exact mobile identity. Client managers
    and coordinators receive summary-level refresh prompts only when the matching
    role is enabled and they hold an explicit assignment to this group.
    """

    current = now or datetime.now(tz=UTC)
    if not access.is_enabled or access.revoked_at is not None:
        return DocumentChangeNotificationCounts()
    available_at = max(
        value for value in (current, access.access_starts_at) if value is not None
    )
    expires_at = access.access_expires_at
    if expires_at is not None and expires_at <= available_at:
        return DocumentChangeNotificationCounts()

    identities = tuple(sorted(set(passenger_identity_ids), key=str))
    passengers = 0
    managers = 0
    coordinators = 0
    if access.passenger_access_enabled and identities:
        passengers = await _enqueue_document_change_ids(
            session,
            recipient_ids=identities,
            recipient_type="passenger",
            access=access,
            operation=operation,
            dedupe_token=dedupe_token,
            available_at=available_at,
            expires_at=expires_at,
        )
    if access.client_manager_access_enabled:
        managers = await _enqueue_document_change_user_pages(
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
            recipient_type="client_manager",
            access=access,
            operation=operation,
            dedupe_token=dedupe_token,
            available_at=available_at,
            expires_at=expires_at,
        )
    if access.coordinator_access_enabled:
        coordinators = await _enqueue_document_change_user_pages(
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
            recipient_type="coordinator",
            access=access,
            operation=operation,
            dedupe_token=dedupe_token,
            available_at=available_at,
            expires_at=expires_at,
        )
    return DocumentChangeNotificationCounts(
        passengers=passengers,
        client_managers=managers,
        coordinators=coordinators,
    )


async def schedule_trip_countdown_notifications(
    session: AsyncSession,
    *,
    timezone_name: str,
    send_hour: int = 9,
    now: datetime | None = None,
) -> CountdownNotificationCounts:
    """Reconcile future 3/2/1-day push-only trip countdowns.

    The trip model currently stores an authoritative date rather than a
    departure timestamp.  The configured IANA timezone and local send hour
    therefore define the delivery instant.  Passed instants are never caught
    up, which prevents a newly installed app or newly enabled group receiving
    a burst of stale countdowns.
    """

    if send_hour < 0 or send_hour > 23:
        raise ValueError("Countdown send hour must be between 0 and 23")
    timezone = ZoneInfo(timezone_name)
    current = _aware_utc(now or datetime.now(tz=UTC))
    assert current is not None
    local_today = current.astimezone(timezone).date()
    first_candidate_date = local_today + timedelta(days=1)
    last_candidate_date = local_today + timedelta(days=366)

    cancelled = await _cancel_stale_countdowns(session, now=current)
    inserted = 0
    groups_scanned = 0
    cursor: uuid.UUID | None = None
    while True:
        statement = (
            select(GCGroupAccessModel, ClientGroupModel)
            .join(ClientGroupModel, ClientGroupModel.id == GCGroupAccessModel.group_id)
            .where(
                ClientGroupModel.agency_id == GCGroupAccessModel.agency_id,
                ClientGroupModel.status.in_(("active", "closed")),
                ClientGroupModel.travel_date >= first_candidate_date,
                ClientGroupModel.travel_date <= last_candidate_date,
                GCGroupAccessModel.is_enabled.is_(True),
                GCGroupAccessModel.revoked_at.is_(None),
                or_(
                    GCGroupAccessModel.passenger_access_enabled.is_(True),
                    GCGroupAccessModel.client_manager_access_enabled.is_(True),
                    GCGroupAccessModel.coordinator_access_enabled.is_(True),
                ),
            )
            .order_by(GCGroupAccessModel.id.asc())
            .limit(100)
        )
        if cursor is not None:
            statement = statement.where(GCGroupAccessModel.id > cursor)
        rows = list((await session.execute(statement)).all())
        if not rows:
            break
        for access, group in rows:
            groups_scanned += 1
            if group.travel_date is None:
                continue
            trip_starts_at = datetime.combine(
                group.travel_date,
                time.min,
                tzinfo=timezone,
            ).astimezone(UTC)
            access_start = _aware_utc(access.access_starts_at)
            access_expiry = _aware_utc(access.access_expires_at)
            for days_remaining in _COUNTDOWN_DAYS:
                scheduled_at = datetime.combine(
                    group.travel_date - timedelta(days=days_remaining),
                    time(hour=send_hour),
                    tzinfo=timezone,
                ).astimezone(UTC)
                if scheduled_at <= current:
                    continue
                if access_start is not None and access_start > scheduled_at:
                    continue
                expires_at = min(
                    value
                    for value in (access_expiry, trip_starts_at)
                    if value is not None
                )
                if expires_at <= scheduled_at:
                    continue
                inserted += await _enqueue_countdown_recipients(
                    session,
                    access=access,
                    travel_date=group.travel_date,
                    days_remaining=days_remaining,
                    available_at=scheduled_at,
                    expires_at=expires_at,
                )
        cursor = rows[-1][0].id
        if len(rows) < 100:
            break
    return CountdownNotificationCounts(
        inserted=inserted,
        cancelled=cancelled,
        groups_scanned=groups_scanned,
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
            MobileNotificationModel.id.not_in(
                select(MobilePushDeliveryModel.notification_id).where(
                    MobilePushDeliveryModel.status.in_(
                        ("receipt_pending", "delivered")
                    )
                )
            ),
        )
        .values(
            status="cancelled",
            failure_code="announcement_unpublished",
            updated_at=now or datetime.now(tz=UTC),
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(MobilePushDeliveryModel)
        .where(
            MobilePushDeliveryModel.notification_id.in_(
                select(MobileNotificationModel.id).where(
                    MobileNotificationModel.agency_id == access.agency_id,
                    MobileNotificationModel.gc_group_access_id == access.id,
                    MobileNotificationModel.dedupe_key
                    == _announcement_dedupe_key(announcement_id),
                    MobileNotificationModel.status == "cancelled",
                )
            ),
            MobilePushDeliveryModel.status.in_(("submitting", "retry")),
        )
        .values(
            status="cancelled",
            last_error_code="announcement_unpublished",
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
    max_send_attempts: int = 5,
    retry_base_seconds: int = 5,
    receipt_initial_delay_seconds: int = 900,
) -> int:
    """Submit a bounded batch and durably retain every provider ticket."""

    if not provider.enabled:
        return 0
    if limit < 1 or limit > 100:
        raise ValueError("Mobile push batch limit must be between 1 and 100")
    if max_send_attempts < 1:
        raise ValueError("Mobile push send attempts must be positive")
    if retry_base_seconds < 1 or receipt_initial_delay_seconds < 1:
        raise ValueError("Mobile push retry delays must be positive")
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
    notifications = await _retain_currently_authorized_notifications(
        session,
        notifications=notifications,
        now=current,
    )
    if not notifications:
        return 0

    notification_ids = [item.id for item in notifications]
    deliveries = list(
        (
            await session.execute(
                select(MobilePushDeliveryModel).where(
                    MobilePushDeliveryModel.notification_id.in_(notification_ids)
                )
            )
        ).scalars()
    )
    delivery_by_target = {
        (item.notification_id, item.registration_id): item for item in deliveries
    }

    registrations = await _load_recipient_registrations(
        session,
        notifications=notifications,
        provider_name=provider.name,
        now=current,
    )
    messages: list[MobilePushMessage] = []
    registration_by_id: dict[str, MobilePushRegistrationModel] = {}
    notification_by_id = {str(item.id): item for item in notifications}
    delivery_by_message: dict[tuple[str, str], MobilePushDeliveryModel] = {}
    for notification in notifications:
        key = _notification_recipient_key(notification)
        for registration in registrations.get(key, []):
            if len(messages) >= limit:
                break
            delivery = delivery_by_target.get((notification.id, registration.id))
            if delivery is not None:
                if (
                    delivery.agency_id != notification.agency_id
                    or delivery.agency_id != registration.agency_id
                    or delivery.provider != provider.name
                ):
                    _fail_delivery(delivery, current, "tenant_scope_mismatch")
                    continue
                next_attempt_at = _aware_utc(delivery.next_attempt_at)
                if (
                    delivery.status != "retry"
                    or next_attempt_at is None
                    or next_attempt_at > current
                ):
                    continue
                if delivery.send_attempts >= max_send_attempts:
                    _fail_delivery(delivery, current, "send_attempts_exhausted")
                    continue
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
                notification.status = "failed"
                notification.failure_code = "invalid_public_payload"
                notification.updated_at = current
                continue
            if delivery is None:
                delivery = MobilePushDeliveryModel(
                    id=uuid.uuid4(),
                    agency_id=notification.agency_id,
                    notification_id=notification.id,
                    registration_id=registration.id,
                    provider=provider.name,
                    status="submitting",
                    send_attempts=0,
                    receipt_attempts=0,
                    next_attempt_at=current,
                )
                session.add(delivery)
                deliveries.append(delivery)
                delivery_by_target[(notification.id, registration.id)] = delivery
            delivery.status = "submitting"
            delivery.send_attempts += 1
            delivery.last_error_code = None
            delivery.updated_at = current
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
            delivery_by_message[(str(notification.id), str(registration.id))] = delivery
        if len(messages) >= limit:
            break

    if not messages:
        await session.flush()
        await _refresh_notification_delivery_states(
            session,
            notifications=notifications,
            now=current,
        )
        for notification in notifications:
            if notification.status == "queued" and not any(
                item.notification_id == notification.id for item in deliveries
            ):
                notification.failure_code = "no_active_registration"
                notification.available_at = current + timedelta(minutes=5)
                notification.updated_at = current
        return 0

    await session.flush()
    tickets = await provider.send(messages)
    submitted_notifications: set[str] = set()
    returned_targets: set[tuple[str, str]] = set()
    for ticket in tickets:
        ticket_notification = notification_by_id.get(ticket.notification_id)
        ticket_registration = registration_by_id.get(ticket.registration_id)
        delivery = delivery_by_message.get(
            (ticket.notification_id, ticket.registration_id)
        )
        if (
            ticket_notification is None
            or ticket_registration is None
            or delivery is None
        ):
            continue
        returned_targets.add((ticket.notification_id, ticket.registration_id))
        if ticket.accepted and ticket.provider_ticket_id is not None:
            submitted_notifications.add(ticket.notification_id)
            delivery.provider_ticket_id = ticket.provider_ticket_id
            delivery.status = "receipt_pending"
            delivery.submitted_at = current
            delivery.next_attempt_at = current + timedelta(
                seconds=receipt_initial_delay_seconds
            )
            delivery.last_error_code = None
            record_operational_event(OperationalEvent.MOBILE_PUSH, "ticket_accepted")
        else:
            code = ticket.error_code or "provider_ticket_error"
            ticket_registration.last_failure_at = current
            ticket_registration.last_failure_code = code
            if code == "DeviceNotRegistered":
                _revoke_registration(ticket_registration, current, code)
                _fail_delivery(delivery, current, code)
                record_operational_event(OperationalEvent.MOBILE_PUSH, "device_revoked")
            elif ticket.retryable and delivery.send_attempts < max_send_attempts:
                _retry_delivery(
                    delivery,
                    current,
                    code,
                    delay_seconds=_bounded_backoff_seconds(
                        retry_base_seconds,
                        delivery.send_attempts,
                    ),
                )
                record_operational_event(
                    OperationalEvent.MOBILE_PUSH,
                    "send_retry_scheduled",
                )
            else:
                _fail_delivery(delivery, current, code)
                record_operational_event(OperationalEvent.MOBILE_PUSH, "send_failed")
        ticket_registration.updated_at = current

    for target, delivery in delivery_by_message.items():
        if target in returned_targets:
            continue
        if delivery.send_attempts < max_send_attempts:
            _retry_delivery(
                delivery,
                current,
                "provider_missing_ticket",
                delay_seconds=_bounded_backoff_seconds(
                    retry_base_seconds,
                    delivery.send_attempts,
                ),
            )
            record_operational_event(
                OperationalEvent.MOBILE_PUSH,
                "send_retry_scheduled",
            )
        else:
            _fail_delivery(delivery, current, "provider_missing_ticket")
            record_operational_event(OperationalEvent.MOBILE_PUSH, "send_failed")

    await session.flush()
    await _refresh_notification_delivery_states(
        session,
        notifications=notifications,
        now=current,
    )
    return len(submitted_notifications)


async def reconcile_mobile_push_receipts(
    session: AsyncSession,
    *,
    provider: MobilePushProvider,
    limit: int,
    now: datetime | None = None,
    max_attempts: int = 8,
    max_age: timedelta = timedelta(hours=23),
    retry_base_seconds: int = 60,
) -> int:
    """Poll due provider receipts and apply monotonic delivery transitions."""

    if not provider.enabled:
        return 0
    if limit < 1 or limit > 1_000:
        raise ValueError("Mobile push receipt batch limit must be between 1 and 1,000")
    if max_attempts < 1 or max_age <= timedelta(0) or retry_base_seconds < 1:
        raise ValueError("Mobile push receipt retry policy was invalid")
    current = now or datetime.now(tz=UTC)
    deliveries = list(
        (
            await session.execute(
                select(MobilePushDeliveryModel)
                .where(
                    MobilePushDeliveryModel.provider == provider.name,
                    MobilePushDeliveryModel.status == "receipt_pending",
                    MobilePushDeliveryModel.next_attempt_at <= current,
                    MobilePushDeliveryModel.provider_ticket_id.is_not(None),
                )
                .order_by(
                    MobilePushDeliveryModel.next_attempt_at.asc(),
                    MobilePushDeliveryModel.id.asc(),
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).scalars()
    )
    if not deliveries:
        return 0

    notification_ids = {item.notification_id for item in deliveries}
    registration_ids = {item.registration_id for item in deliveries}
    notifications = {
        item.id: item
        for item in (
            (
                await session.execute(
                    select(MobileNotificationModel).where(
                        MobileNotificationModel.id.in_(notification_ids)
                    )
                )
            ).scalars()
        )
    }
    registrations = {
        item.id: item
        for item in (
            (
                await session.execute(
                    select(MobilePushRegistrationModel).where(
                        MobilePushRegistrationModel.id.in_(registration_ids)
                    )
                )
            ).scalars()
        )
    }

    eligible: list[MobilePushDeliveryModel] = []
    for delivery in deliveries:
        notification = notifications.get(delivery.notification_id)
        registration = registrations.get(delivery.registration_id)
        if (
            notification is None
            or registration is None
            or notification.agency_id != delivery.agency_id
            or registration.agency_id != delivery.agency_id
        ):
            _fail_delivery(delivery, current, "tenant_scope_mismatch")
            continue
        submitted_at = _aware_utc(delivery.submitted_at)
        if submitted_at is None or current - submitted_at >= max_age:
            _fail_delivery(delivery, current, "receipt_expired")
            registration.last_failure_at = current
            registration.last_failure_code = "receipt_expired"
            registration.updated_at = current
            record_operational_event(OperationalEvent.MOBILE_PUSH, "receipt_failed")
            continue
        eligible.append(delivery)

    if not eligible:
        await session.flush()
        await _refresh_notification_delivery_states(
            session,
            notifications=list(notifications.values()),
            now=current,
        )
        return 0

    ticket_ids = [
        item.provider_ticket_id
        for item in eligible
        if item.provider_ticket_id is not None
    ]
    receipt_by_ticket = {
        item.provider_ticket_id: item
        for item in await provider.get_receipts(ticket_ids)
    }
    delivered_notifications: set[uuid.UUID] = set()
    for delivery in eligible:
        ticket_id = delivery.provider_ticket_id
        if ticket_id is None:
            _fail_delivery(delivery, current, "provider_ticket_missing")
            continue
        registration = registrations[delivery.registration_id]
        receipt = receipt_by_ticket.get(ticket_id)
        delivery.receipt_attempts += 1
        if receipt is not None and receipt.delivered:
            delivery.status = "delivered"
            delivery.delivered_at = current
            delivery.failed_at = None
            delivery.last_error_code = None
            delivery.updated_at = current
            registration.last_success_at = current
            registration.last_failure_code = None
            registration.updated_at = current
            delivered_notifications.add(delivery.notification_id)
            record_operational_event(OperationalEvent.MOBILE_PUSH, "receipt_delivered")
            continue

        code = (
            receipt.error_code
            if receipt is not None and receipt.error_code is not None
            else "provider_missing_receipt_response"
        )
        registration.last_failure_at = current
        registration.last_failure_code = code
        registration.updated_at = current
        if code == "DeviceNotRegistered":
            _revoke_registration(registration, current, code)
            _fail_delivery(delivery, current, code)
            record_operational_event(OperationalEvent.MOBILE_PUSH, "device_revoked")
            continue
        retryable = receipt is None or receipt.retryable
        if retryable and delivery.receipt_attempts < max_attempts:
            delivery.next_attempt_at = current + timedelta(
                seconds=_bounded_backoff_seconds(
                    retry_base_seconds,
                    delivery.receipt_attempts,
                    maximum=3_600,
                )
            )
            delivery.last_error_code = code
            delivery.updated_at = current
            record_operational_event(
                OperationalEvent.MOBILE_PUSH,
                "receipt_retry_scheduled",
            )
        else:
            _fail_delivery(delivery, current, code)
            record_operational_event(OperationalEvent.MOBILE_PUSH, "receipt_failed")

    await session.flush()
    await _refresh_notification_delivery_states(
        session,
        notifications=list(notifications.values()),
        now=current,
    )
    return len(delivered_notifications)


def _retry_delivery(
    delivery: MobilePushDeliveryModel,
    now: datetime,
    code: str,
    *,
    delay_seconds: int,
) -> None:
    if delivery.status in {"delivered", "failed", "cancelled"}:
        return
    delivery.status = "retry"
    delivery.provider_ticket_id = None
    delivery.submitted_at = None
    delivery.delivered_at = None
    delivery.failed_at = None
    delivery.next_attempt_at = now + timedelta(seconds=delay_seconds)
    delivery.last_error_code = code
    delivery.updated_at = now


def _fail_delivery(
    delivery: MobilePushDeliveryModel,
    now: datetime,
    code: str,
) -> None:
    if delivery.status in {"delivered", "cancelled"}:
        return
    delivery.status = "failed"
    delivery.delivered_at = None
    delivery.failed_at = delivery.failed_at or now
    delivery.last_error_code = code
    delivery.updated_at = now


def _revoke_registration(
    registration: MobilePushRegistrationModel,
    now: datetime,
    code: str,
) -> None:
    if registration.status != "revoked":
        registration.status = "revoked"
        registration.notifications_authorized = False
        registration.revoked_at = now
    registration.last_failure_at = now
    registration.last_failure_code = code
    registration.updated_at = now


async def _refresh_notification_delivery_states(
    session: AsyncSession,
    *,
    notifications: list[MobileNotificationModel],
    now: datetime,
) -> None:
    if not notifications:
        return
    notification_ids = [item.id for item in notifications]
    deliveries = list(
        (
            await session.execute(
                select(MobilePushDeliveryModel).where(
                    MobilePushDeliveryModel.notification_id.in_(notification_ids)
                )
            )
        ).scalars()
    )
    grouped: dict[uuid.UUID, list[MobilePushDeliveryModel]] = {}
    for delivery in deliveries:
        grouped.setdefault(delivery.notification_id, []).append(delivery)

    for notification in notifications:
        if notification.status == "cancelled":
            continue
        rows = grouped.get(notification.id, [])
        if not rows:
            continue
        if any(item.status == "delivered" for item in rows):
            notification.status = "sent"
            notification.sent_at = notification.sent_at or now
            notification.failure_code = None
            notification.updated_at = now
            continue
        if notification.status == "sent":
            continue
        pending = [
            item
            for item in rows
            if item.status in {"submitting", "retry", "receipt_pending"}
        ]
        if pending:
            notification.status = "queued"
            retry_errors = [
                item.last_error_code
                for item in pending
                if item.status == "retry" and item.last_error_code is not None
            ]
            notification.failure_code = retry_errors[0] if retry_errors else None
            notification.updated_at = now
            continue
        notification.status = "failed"
        notification.failure_code = next(
            (
                item.last_error_code
                for item in rows
                if item.last_error_code is not None
            ),
            "provider_rejected",
        )
        notification.updated_at = now


def _bounded_backoff_seconds(
    base_seconds: int,
    attempt: int,
    *,
    maximum: int = 900,
) -> int:
    exponent = max(0, min(attempt - 1, 10))
    return min(maximum, int(base_seconds * (2**exponent)))


def _aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def _retain_currently_authorized_notifications(
    session: AsyncSession,
    *,
    notifications: list[MobileNotificationModel],
    now: datetime,
) -> list[MobileNotificationModel]:
    """Cancel due group pushes whose recipient no longer has trip access."""

    grouped = [
        item
        for item in notifications
        if item.gc_group_access_id is not None and item.group_id is not None
    ]
    if not grouped:
        return notifications

    eligible: set[
        tuple[str, uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]
    ] = set()
    passenger_filters = []
    manager_filters = []
    coordinator_filters = []
    for item in grouped:
        principal_id = (
            item.recipient_passenger_identity_id
            if item.recipient_type == "passenger"
            else item.recipient_user_id
        )
        if principal_id is None:
            continue
        condition = and_(
            GCGroupAccessModel.id == item.gc_group_access_id,
            GCGroupAccessModel.agency_id == item.agency_id,
            GCGroupAccessModel.group_id == item.group_id,
        )
        if item.recipient_type == "passenger":
            passenger_filters.append(
                and_(condition, MobilePassengerIdentityModel.id == principal_id)
            )
        elif item.recipient_type == "client_manager":
            manager_filters.append(and_(condition, UserModel.id == principal_id))
        elif item.recipient_type == "coordinator":
            coordinator_filters.append(and_(condition, UserModel.id == principal_id))

    access_conditions = (
        ClientGroupModel.status.in_(("active", "closed")),
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
    if passenger_filters:
        passenger_rows = (
            await session.execute(
                select(
                    MobilePassengerIdentityModel.agency_id,
                    MobilePassengerIdentityModel.gc_group_access_id,
                    MobilePassengerIdentityModel.group_id,
                    MobilePassengerIdentityModel.id,
                )
                .join(
                    GCGroupAccessModel,
                    GCGroupAccessModel.id
                    == MobilePassengerIdentityModel.gc_group_access_id,
                )
                .join(ClientGroupModel, ClientGroupModel.id == GCGroupAccessModel.group_id)
                .where(
                    *access_conditions,
                    GCGroupAccessModel.passenger_access_enabled.is_(True),
                    MobilePassengerIdentityModel.status.in_(("eligible", "claimed")),
                    MobilePassengerIdentityModel.revoked_at.is_(None),
                    or_(*passenger_filters),
                )
            )
        ).all()
        eligible.update(("passenger", *row) for row in passenger_rows)
    if manager_filters:
        manager_rows = (
            await session.execute(
                select(
                    GCGroupAccessModel.agency_id,
                    GCGroupAccessModel.id,
                    GCGroupAccessModel.group_id,
                    UserModel.id,
                )
                .join(
                    ClientManagerProfileModel,
                    ClientManagerProfileModel.user_id == UserModel.id,
                )
                .join(
                    ClientManagerGroupAssignmentModel,
                    ClientManagerGroupAssignmentModel.profile_id
                    == ClientManagerProfileModel.id,
                )
                .join(
                    GCGroupAccessModel,
                    GCGroupAccessModel.id
                    == ClientManagerGroupAssignmentModel.gc_group_access_id,
                )
                .join(ClientGroupModel, ClientGroupModel.id == GCGroupAccessModel.group_id)
                .where(
                    *access_conditions,
                    GCGroupAccessModel.client_manager_access_enabled.is_(True),
                    UserModel.role == "client_manager",
                    UserModel.is_active.is_(True),
                    UserModel.deleted_at.is_(None),
                    ClientManagerProfileModel.status == "active",
                    ClientManagerProfileModel.deleted_at.is_(None),
                    ClientManagerGroupAssignmentModel.is_active.is_(True),
                    ClientManagerGroupAssignmentModel.revoked_at.is_(None),
                    or_(*manager_filters),
                )
            )
        ).all()
        eligible.update(("client_manager", *row) for row in manager_rows)
    if coordinator_filters:
        coordinator_rows = (
            await session.execute(
                select(
                    GCGroupAccessModel.agency_id,
                    GCGroupAccessModel.id,
                    GCGroupAccessModel.group_id,
                    UserModel.id,
                )
                .join(
                    CoordinatorGroupAssignmentModel,
                    CoordinatorGroupAssignmentModel.coordinator_user_id
                    == UserModel.id,
                )
                .join(
                    GCGroupAccessModel,
                    and_(
                        GCGroupAccessModel.agency_id
                        == CoordinatorGroupAssignmentModel.agency_id,
                        GCGroupAccessModel.group_id
                        == CoordinatorGroupAssignmentModel.group_id,
                    ),
                )
                .join(ClientGroupModel, ClientGroupModel.id == GCGroupAccessModel.group_id)
                .where(
                    *access_conditions,
                    GCGroupAccessModel.coordinator_access_enabled.is_(True),
                    UserModel.role == "agency_coordinator",
                    UserModel.is_active.is_(True),
                    UserModel.deleted_at.is_(None),
                    CoordinatorGroupAssignmentModel.active.is_(True),
                    or_(*coordinator_filters),
                )
            )
        ).all()
        eligible.update(("coordinator", *row) for row in coordinator_rows)

    retained: list[MobileNotificationModel] = []
    cancelled_ids: list[uuid.UUID] = []
    for item in notifications:
        if item.gc_group_access_id is None or item.group_id is None:
            retained.append(item)
            continue
        principal_id = (
            item.recipient_passenger_identity_id
            if item.recipient_type == "passenger"
            else item.recipient_user_id
        )
        key = (
            item.recipient_type,
            item.agency_id,
            item.gc_group_access_id,
            item.group_id,
            principal_id,
        )
        if principal_id is not None and key in eligible:
            retained.append(item)
            continue
        item.status = "cancelled"
        item.failure_code = "recipient_access_revoked"
        item.updated_at = now
        cancelled_ids.append(item.id)
    if cancelled_ids:
        await session.execute(
            update(MobilePushDeliveryModel)
            .where(
                MobilePushDeliveryModel.notification_id.in_(cancelled_ids),
                MobilePushDeliveryModel.status.in_(("submitting", "retry")),
            )
            .values(
                status="cancelled",
                last_error_code="recipient_access_revoked",
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
    return retained


async def _cancel_stale_countdowns(
    session: AsyncSession,
    *,
    now: datetime,
) -> int:
    cancelled = 0
    cursor: uuid.UUID | None = None
    while True:
        statement = (
            select(
                MobileNotificationModel,
                GCGroupAccessModel,
                ClientGroupModel,
            )
            .join(
                GCGroupAccessModel,
                GCGroupAccessModel.id
                == MobileNotificationModel.gc_group_access_id,
            )
            .join(
                ClientGroupModel,
                ClientGroupModel.id == MobileNotificationModel.group_id,
            )
            .where(
                MobileNotificationModel.notification_type
                == _COUNTDOWN_NOTIFICATION_TYPE,
                MobileNotificationModel.status == "queued",
            )
            .order_by(MobileNotificationModel.id.asc())
            .limit(_COUNTDOWN_CLEANUP_PAGE_SIZE)
        )
        if cursor is not None:
            statement = statement.where(MobileNotificationModel.id > cursor)
        rows = list((await session.execute(statement)).all())
        if not rows:
            break
        cancelled_ids: list[uuid.UUID] = []
        for notification, access, group in rows:
            role_enabled = {
                "passenger": access.passenger_access_enabled,
                "client_manager": access.client_manager_access_enabled,
                "coordinator": access.coordinator_access_enabled,
            }.get(notification.recipient_type, False)
            scheduled_at = _aware_utc(notification.available_at)
            expires_at = _aware_utc(notification.expires_at)
            access_start = _aware_utc(access.access_starts_at)
            access_expiry = _aware_utc(access.access_expires_at)
            current_schedule = (
                group.travel_date is not None
                and notification.dedupe_key.startswith(
                    f"trip-countdown:{group.travel_date.isoformat()}:"
                )
            )
            invalid = (
                group.status not in {"active", "closed"}
                or not access.is_enabled
                or access.revoked_at is not None
                or not role_enabled
                or not current_schedule
                or scheduled_at is None
                or (access_start is not None and access_start > scheduled_at)
                or (access_expiry is not None and access_expiry <= scheduled_at)
                or (expires_at is not None and expires_at <= now)
            )
            if not invalid:
                continue
            notification.status = "cancelled"
            notification.failure_code = "countdown_schedule_changed"
            notification.updated_at = now
            cancelled_ids.append(notification.id)
        if cancelled_ids:
            await session.execute(
                update(MobilePushDeliveryModel)
                .where(
                    MobilePushDeliveryModel.notification_id.in_(cancelled_ids),
                    MobilePushDeliveryModel.status.in_(("submitting", "retry")),
                )
                .values(
                    status="cancelled",
                    last_error_code="countdown_schedule_changed",
                    updated_at=now,
                )
                .execution_options(synchronize_session=False)
            )
            cancelled += len(cancelled_ids)
        cursor = rows[-1][0].id
        if len(rows) < _COUNTDOWN_CLEANUP_PAGE_SIZE:
            break
    return cancelled


async def _enqueue_countdown_recipients(
    session: AsyncSession,
    *,
    access: GCGroupAccessModel,
    travel_date: date,
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
            travel_date=travel_date,
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
                    CoordinatorGroupAssignmentModel.coordinator_user_id
                    == UserModel.id,
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
                    page_statement.order_by(id_column.asc()).limit(
                        _RECIPIENT_PAGE_SIZE
                    )
                )
            ).scalars()
        )
        if not ids:
            break
        rows = [
            _countdown_notification_values(
                recipient_id=recipient_id,
                recipient_type=recipient_type,
                access=access,
                travel_date=travel_date,
                days_remaining=days_remaining,
                available_at=available_at,
                expires_at=expires_at,
            )
            for recipient_id in ids
        ]
        inserted += await _insert_notifications_ignore_duplicates(session, rows=rows)
        cursor = ids[-1]
        if len(ids) < _RECIPIENT_PAGE_SIZE:
            break
    return inserted


def _countdown_notification_values(
    *,
    recipient_id: uuid.UUID,
    recipient_type: Literal["passenger", "client_manager", "coordinator"],
    access: GCGroupAccessModel,
    travel_date: date,
    days_remaining: int,
    available_at: datetime,
    expires_at: datetime,
) -> dict[str, object]:
    templates = _COUNTDOWN_TEMPLATES[days_remaining]
    seed = (
        f"{access.group_id}:{recipient_id}:{travel_date.isoformat()}:{days_remaining}"
    ).encode("ascii")
    template_index = int.from_bytes(hashlib.sha256(seed).digest()[:2], "big") % len(
        templates
    )
    title, body = templates[template_index]
    is_passenger = recipient_type == "passenger"
    return {
        "id": uuid.uuid4(),
        "agency_id": access.agency_id,
        "group_id": access.group_id,
        "gc_group_access_id": access.id,
        "recipient_type": recipient_type,
        "recipient_user_id": None if is_passenger else recipient_id,
        "recipient_passenger_identity_id": recipient_id if is_passenger else None,
        "notification_type": _COUNTDOWN_NOTIFICATION_TYPE,
        "category": "itinerary",
        "priority": "normal",
        "title": title,
        "body": body,
        "lock_screen_title": title,
        "lock_screen_body": body,
        "contains_sensitive_content": False,
        "deep_link_path": f"/trip?trip_id={access.group_id}",
        "dedupe_key": (
            f"trip-countdown:{travel_date.isoformat()}:{days_remaining}"
        ),
        "public_payload": {"route": "trip", "trip_id": str(access.group_id)},
        "status": "queued",
        "available_at": available_at,
        "expires_at": expires_at,
    }


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
            postgresql_insert(MobileNotificationModel)
            .values(rows)
            .on_conflict_do_nothing()
        )
    elif dialect_name == "sqlite":
        result = await session.execute(
            sqlite_insert(MobileNotificationModel)
            .values(rows)
            .on_conflict_do_nothing()
        )
    else:
        raise RuntimeError("Countdown scheduling requires PostgreSQL or SQLite")
    return max(0, int(getattr(result, "rowcount", 0) or 0))


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


async def _enqueue_document_change_user_pages(
    session: AsyncSession,
    *,
    statement: Select[tuple[uuid.UUID]],
    recipient_type: Literal["client_manager", "coordinator"],
    access: GCGroupAccessModel,
    operation: Literal["upsert", "delete"],
    dedupe_token: str,
    available_at: datetime,
    expires_at: datetime | None,
) -> int:
    cursor: uuid.UUID | None = None
    inserted = 0
    while True:
        page_statement = statement
        if cursor is not None:
            page_statement = page_statement.where(UserModel.id > cursor)
        ids = list(
            (
                await session.execute(
                    page_statement.order_by(UserModel.id.asc()).limit(
                        _RECIPIENT_PAGE_SIZE
                    )
                )
            ).scalars()
        )
        if not ids:
            break
        inserted += await _enqueue_document_change_ids(
            session,
            recipient_ids=ids,
            recipient_type=recipient_type,
            access=access,
            operation=operation,
            dedupe_token=dedupe_token,
            available_at=available_at,
            expires_at=expires_at,
        )
        cursor = ids[-1]
        if len(ids) < _RECIPIENT_PAGE_SIZE:
            break
    return inserted


async def _enqueue_document_change_ids(
    session: AsyncSession,
    *,
    recipient_ids: Sequence[uuid.UUID],
    recipient_type: Literal["passenger", "client_manager", "coordinator"],
    access: GCGroupAccessModel,
    operation: Literal["upsert", "delete"],
    dedupe_token: str,
    available_at: datetime,
    expires_at: datetime | None,
) -> int:
    for recipient_id in recipient_ids:
        session.add(
            _personal_document_change_notification(
                recipient_id=recipient_id,
                recipient_type=recipient_type,
                access=access,
                operation=operation,
                dedupe_token=dedupe_token,
                available_at=available_at,
                expires_at=expires_at,
            )
        )
    if recipient_ids:
        await session.flush()
    return len(recipient_ids)


def _personal_document_change_notification(
    *,
    recipient_id: uuid.UUID,
    recipient_type: Literal["passenger", "client_manager", "coordinator"],
    access: GCGroupAccessModel,
    operation: Literal["upsert", "delete"],
    dedupe_token: str,
    available_at: datetime,
    expires_at: datetime | None,
) -> MobileNotificationModel:
    route_by_role = {
        "passenger": "documents",
        "client_manager": "readiness",
        "coordinator": "passengers",
    }
    title_by_role = {
        "passenger": "Travel documents updated",
        "client_manager": "Group readiness updated",
        "coordinator": "Passenger information updated",
    }
    body_by_role = {
        "passenger": "Open Group Companion to refresh your travel documents.",
        "client_manager": "Open Group Companion to refresh the group readiness summary.",
        "coordinator": "Open Group Companion to refresh passenger information.",
    }
    route = route_by_role[recipient_type]
    is_passenger = recipient_type == "passenger"
    return MobileNotificationModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        group_id=access.group_id,
        gc_group_access_id=access.id,
        recipient_type=recipient_type,
        recipient_user_id=None if is_passenger else recipient_id,
        recipient_passenger_identity_id=recipient_id if is_passenger else None,
        notification_type="personal_document_changed",
        category="document",
        priority="normal",
        title=title_by_role[recipient_type],
        body=body_by_role[recipient_type],
        lock_screen_title=_LOCK_SCREEN_TITLE,
        lock_screen_body=None,
        contains_sensitive_content=True,
        deep_link_path=f"/{route}?trip_id={access.group_id}",
        dedupe_key=_document_change_dedupe_key(
            dedupe_token=dedupe_token,
            recipient_type=recipient_type,
            operation=operation,
        ),
        public_payload={"route": route, "trip_id": str(access.group_id)},
        status="queued",
        available_at=available_at,
        expires_at=expires_at,
    )


def _document_change_dedupe_key(
    *,
    dedupe_token: str,
    recipient_type: str,
    operation: str,
) -> str:
    digest = hashlib.sha256(dedupe_token.encode("utf-8")).hexdigest()
    return f"personal-document:{operation}:{recipient_type}:{digest}"


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
    "CountdownNotificationCounts",
    "DocumentChangeNotificationCounts",
    "cancel_announcement_notifications",
    "dispatch_mobile_push_batch",
    "enqueue_announcement_notifications",
    "enqueue_personal_document_change_notifications",
    "reconcile_mobile_push_receipts",
    "schedule_trip_countdown_notifications",
]
