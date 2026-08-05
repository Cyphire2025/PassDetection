from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.notification_service import (
    _announcement_notification,
    cancel_announcement_notifications,
    dispatch_mobile_push_batch,
    enqueue_announcement_notifications,
    enqueue_personal_document_change_notifications,
    reconcile_mobile_push_receipts,
    schedule_trip_countdown_notifications,
)
from app.application.mobile.push_provider import (
    DisabledMobilePushProvider,
    MobilePushMessage,
    MobilePushReceipt,
    MobilePushTicket,
)
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


def _access(*, enabled: bool = True) -> GCGroupAccessModel:
    return GCGroupAccessModel(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        client_organization_id=uuid.uuid4(),
        is_enabled=enabled,
        passenger_access_enabled=True,
        client_manager_access_enabled=True,
        coordinator_access_enabled=True,
    )


def _announcement(access: GCGroupAccessModel) -> GCAnnouncementModel:
    now = datetime.now(tz=UTC)
    return GCAnnouncementModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        group_id=access.group_id,
        gc_group_access_id=access.id,
        logical_announcement_id=uuid.uuid4(),
        version=1,
        category="general",
        priority="high",
        title="Gate changed",
        body="Use the updated meeting point shown in the app.",
        status="published",
        published_at=now,
        passenger_visible=True,
        client_manager_visible=True,
        coordinator_visible=True,
    )


def _group(
    access: GCGroupAccessModel,
    *,
    travel_date: date | None = None,
) -> ClientGroupModel:
    return ClientGroupModel(
        id=access.group_id,
        agency_id=access.agency_id,
        name="Countdown test group",
        token=f"countdown-{uuid.uuid4().hex}",
        status="active",
        travel_date=travel_date,
    )


async def _persist_push_target(
    db_session: AsyncSession,
    *,
    now: datetime,
) -> tuple[
    MobilePushRegistrationModel,
    MobileNotificationModel,
]:
    access = _access()
    group = _group(access)
    announcement = _announcement(access)
    passenger = MobilePassengerIdentityModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        group_id=access.group_id,
        gc_group_access_id=access.id,
        passenger_submission_id=uuid.uuid4(),
        normalized_phone_number="+919999999984",
        phone_lookup_hash=uuid.uuid4().hex * 2,
        status="claimed",
        claimed_at=now,
    )
    device_session = MobileDeviceSessionModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        subject_role="passenger",
        user_id=None,
        account_id=passenger.id,
        passenger_identity_id=passenger.id,
        passenger_subject_hash=uuid.uuid4().hex * 2,
        selected_gc_group_access_id=access.id,
        selected_group_id=access.group_id,
        device_identifier_hash=uuid.uuid4().hex * 2,
        platform="android",
        app_version="1.0.0",
        status="active",
        session_generation=0,
        refresh_family_id=uuid.uuid4(),
        expires_at=now + timedelta(days=1),
    )
    registration = MobilePushRegistrationModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        session_id=device_session.id,
        provider="expo",
        platform="android",
        environment="development",
        app_bundle_id="com.globalconnects.groupcompanion",
        token_ciphertext=mobile_push_fernet().encrypt(
            b"ExponentPushToken[receipt-test-token]"
        ),
        token_lookup_hash=uuid.uuid4().hex * 2,
        token_key_version=1,
        status="active",
        notifications_authorized=True,
    )
    notification = _announcement_notification(
        recipient_id=passenger.id,
        recipient_type="passenger",
        access=access,
        announcement=announcement,
        available_at=now,
        expires_at=None,
    )
    db_session.add_all(
        [
            group,
            access,
            announcement,
            passenger,
            device_session,
            registration,
            notification,
        ]
    )
    await db_session.flush()
    return registration, notification


def test_announcement_notification_keeps_content_off_lock_screen() -> None:
    access = _access()
    announcement = _announcement(access)
    passenger_id = uuid.uuid4()

    notification = _announcement_notification(
        recipient_id=passenger_id,
        recipient_type="passenger",
        access=access,
        announcement=announcement,
        available_at=datetime.now(tz=UTC),
        expires_at=None,
    )

    assert notification.recipient_passenger_identity_id == passenger_id
    assert notification.recipient_user_id is None
    assert notification.contains_sensitive_content is True
    assert notification.lock_screen_title == "Group Companion update"
    assert notification.lock_screen_body is None
    assert notification.public_payload == {
        "route": "updates",
        "trip_id": str(access.group_id),
        "event_id": str(announcement.id),
    }
    assert "Gate changed" not in notification.lock_screen_title


@pytest.mark.asyncio
async def test_disabled_access_produces_no_recipient_queries() -> None:
    access = _access(enabled=False)
    announcement = _announcement(access)

    counts = await enqueue_announcement_notifications(
        object(),  # type: ignore[arg-type]
        access=access,
        announcement=announcement,
    )

    assert counts.total == 0


@pytest.mark.asyncio
async def test_disabled_delivery_provider_never_touches_queue() -> None:
    delivered = await dispatch_mobile_push_batch(
        object(),  # type: ignore[arg-type]
        provider=DisabledMobilePushProvider(),
        limit=100,
    )

    assert delivered == 0


@pytest.mark.asyncio
async def test_trip_countdown_scheduler_is_push_only_deduplicated_and_reschedulable(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.application.mobile.notification_service._COUNTDOWN_CLEANUP_PAGE_SIZE",
        2,
    )
    now = datetime(2026, 8, 4, 2, 0, tzinfo=UTC)
    access = _access()
    access.client_manager_access_enabled = False
    access.coordinator_access_enabled = False
    group = _group(access, travel_date=date(2026, 8, 7))
    group.destination = "Sensitive destination"
    passenger = MobilePassengerIdentityModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        group_id=access.group_id,
        gc_group_access_id=access.id,
        passenger_submission_id=uuid.uuid4(),
        normalized_phone_number="+919999999980",
        phone_lookup_hash="8" * 64,
        status="claimed",
        claimed_at=now,
    )
    db_session.add_all([group, access, passenger])
    await db_session.flush()

    first = await schedule_trip_countdown_notifications(
        db_session,
        timezone_name="Asia/Kolkata",
        send_hour=9,
        now=now,
    )
    duplicate = await schedule_trip_countdown_notifications(
        db_session,
        timezone_name="Asia/Kolkata",
        send_hour=9,
        now=now,
    )

    notification = (
        await db_session.execute(
            select(MobileNotificationModel).where(
                MobileNotificationModel.notification_type == "trip_countdown",
                MobileNotificationModel.dedupe_key == "trip-countdown:2026-08-07:3",
            )
        )
    ).scalar_one()
    scheduled_at = notification.available_at
    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=UTC)
    assert first.inserted == 3
    assert duplicate.inserted == 0
    assert scheduled_at == datetime(2026, 8, 4, 3, 30, tzinfo=UTC)
    assert notification.dedupe_key == "trip-countdown:2026-08-07:3"
    assert notification.contains_sensitive_content is False
    assert notification.lock_screen_body
    assert group.name not in notification.lock_screen_body
    assert "Sensitive destination" not in (notification.lock_screen_body or "")
    assert notification.public_payload == {
        "route": "trip",
        "trip_id": str(access.group_id),
    }

    group.travel_date = date(2026, 8, 8)
    changed = await schedule_trip_countdown_notifications(
        db_session,
        timezone_name="Asia/Kolkata",
        send_hour=9,
        now=now,
    )

    assert changed.cancelled == 3
    assert changed.inserted == 3
    assert notification.status == "cancelled"


@pytest.mark.asyncio
async def test_trip_countdown_scheduler_does_not_catch_up_a_passed_window(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 8, 4, 4, 0, tzinfo=UTC)  # 09:30 Asia/Kolkata
    access = _access()
    access.client_manager_access_enabled = False
    access.coordinator_access_enabled = False
    group = _group(access, travel_date=date(2026, 8, 7))
    passenger = MobilePassengerIdentityModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        group_id=access.group_id,
        gc_group_access_id=access.id,
        passenger_submission_id=uuid.uuid4(),
        normalized_phone_number="+919999999981",
        phone_lookup_hash="9" * 64,
        status="claimed",
        claimed_at=now,
    )
    db_session.add_all([group, access, passenger])
    await db_session.flush()

    counts = await schedule_trip_countdown_notifications(
        db_session,
        timezone_name="Asia/Kolkata",
        send_hour=9,
        now=now,
    )

    assert counts.inserted == 2
    rows = list(
        (
            await db_session.execute(
                select(MobileNotificationModel).where(
                    MobileNotificationModel.notification_type == "trip_countdown"
                )
            )
        ).scalars()
    )
    assert {row.dedupe_key for row in rows} == {
        "trip-countdown:2026-08-07:2",
        "trip-countdown:2026-08-07:1",
    }


@pytest.mark.asyncio
async def test_announcement_producer_targets_only_explicit_role_grants(
    db_session: AsyncSession,
) -> None:
    access = _access()
    announcement = _announcement(access)
    passenger = MobilePassengerIdentityModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        group_id=access.group_id,
        gc_group_access_id=access.id,
        passenger_submission_id=uuid.uuid4(),
        normalized_phone_number="+919999999991",
        phone_lookup_hash="1" * 64,
        status="eligible",
    )
    unrelated_passenger = MobilePassengerIdentityModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        group_id=uuid.uuid4(),
        gc_group_access_id=uuid.uuid4(),
        passenger_submission_id=uuid.uuid4(),
        normalized_phone_number="+919999999992",
        phone_lookup_hash="2" * 64,
        status="eligible",
    )
    manager_user = UserModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        email="manager-push@example.test",
        hashed_password="not-a-plaintext-password",
        full_name="Manager",
        role="client_manager",
        is_active=True,
    )
    manager_profile = ClientManagerProfileModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        user_id=manager_user.id,
        organization_id=access.client_organization_id,
        normalized_phone_number="+919999999993",
        status="active",
        activated_at=datetime.now(tz=UTC),
    )
    manager_assignment = ClientManagerGroupAssignmentModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        organization_id=access.client_organization_id,
        group_id=access.group_id,
        profile_id=manager_profile.id,
        gc_group_access_id=access.id,
        is_active=True,
    )
    coordinator_user = UserModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        email="coordinator-push@example.test",
        hashed_password="not-a-plaintext-password",
        full_name="Coordinator",
        role="agency_coordinator",
        is_active=True,
    )
    coordinator_assignment = CoordinatorGroupAssignmentModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        group_id=access.group_id,
        coordinator_user_id=coordinator_user.id,
        active=True,
    )
    db_session.add_all(
        [
            access,
            announcement,
            passenger,
            unrelated_passenger,
            manager_user,
            manager_profile,
            manager_assignment,
            coordinator_user,
            coordinator_assignment,
        ]
    )
    await db_session.flush()

    counts = await enqueue_announcement_notifications(
        db_session,
        access=access,
        announcement=announcement,
    )
    rows = list(
        (
            await db_session.execute(
                select(MobileNotificationModel).order_by(
                    MobileNotificationModel.recipient_type.asc()
                )
            )
        ).scalars()
    )

    assert counts.passengers == 1
    assert counts.client_managers == 1
    assert counts.coordinators == 1
    assert {row.recipient_type for row in rows} == {
        "passenger",
        "client_manager",
        "coordinator",
    }
    assert unrelated_passenger.id not in {
        row.recipient_passenger_identity_id for row in rows
    }

    document_counts = await enqueue_personal_document_change_notifications(
        db_session,
        access=access,
        passenger_identity_ids=[passenger.id],
        operation="upsert",
        dedupe_token="document-worker-batch:1",
    )
    document_rows = list(
        (
            await db_session.execute(
                select(MobileNotificationModel).where(
                    MobileNotificationModel.notification_type
                    == "personal_document_changed"
                )
            )
        ).scalars()
    )

    assert document_counts.passengers == 1
    assert document_counts.client_managers == 1
    assert document_counts.coordinators == 1
    assert {
        row.recipient_type: row.public_payload["route"] for row in document_rows
    } == {
        "passenger": "documents",
        "client_manager": "readiness",
        "coordinator": "passengers",
    }
    assert all(row.lock_screen_body is None for row in document_rows)
    assert all(row.contains_sensitive_content is True for row in document_rows)


@pytest.mark.asyncio
async def test_announcement_cancellation_removes_all_delivery_states_from_feed(
    db_session: AsyncSession,
) -> None:
    access = _access()
    announcement = _announcement(access)
    passengers = [
        MobilePassengerIdentityModel(
            id=uuid.uuid4(),
            agency_id=access.agency_id,
            group_id=access.group_id,
            gc_group_access_id=access.id,
            passenger_submission_id=uuid.uuid4(),
            normalized_phone_number=f"+9199999999{index}",
            phone_lookup_hash=f"{index + 10:064x}",
            status="eligible",
        )
        for index in range(3)
    ]
    db_session.add_all([access, announcement, *passengers])
    await db_session.flush()
    counts = await enqueue_announcement_notifications(
        db_session,
        access=access,
        announcement=announcement,
    )
    rows = list(
        (
            await db_session.execute(
                select(MobileNotificationModel).order_by(MobileNotificationModel.id)
            )
        ).scalars()
    )
    assert counts.passengers == 3
    rows[1].status = "sent"
    rows[1].sent_at = datetime.now(tz=UTC)
    rows[2].status = "failed"
    rows[2].failure_code = "provider_rejected"
    await db_session.flush()

    cancelled = await cancel_announcement_notifications(
        db_session,
        access=access,
        announcement_id=announcement.id,
    )
    for row in rows:
        await db_session.refresh(row)

    assert cancelled == 3
    assert {row.status for row in rows} == {"cancelled"}
    assert {row.failure_code for row in rows} == {"announcement_unpublished"}


@pytest.mark.asyncio
async def test_dispatch_uses_encrypted_token_and_marks_ticket_sent(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(tz=UTC)
    access = _access()
    group = _group(access)
    announcement = _announcement(access)
    passenger = MobilePassengerIdentityModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        group_id=access.group_id,
        gc_group_access_id=access.id,
        passenger_submission_id=uuid.uuid4(),
        normalized_phone_number="+919999999994",
        phone_lookup_hash="4" * 64,
        status="claimed",
        claimed_at=now,
    )
    device_session = MobileDeviceSessionModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        subject_role="passenger",
        user_id=None,
        account_id=passenger.id,
        passenger_identity_id=passenger.id,
        passenger_subject_hash="5" * 64,
        selected_gc_group_access_id=access.id,
        selected_group_id=access.group_id,
        device_identifier_hash="6" * 64,
        platform="android",
        app_version="1.0.0",
        status="active",
        session_generation=0,
        refresh_family_id=uuid.uuid4(),
        expires_at=now + timedelta(days=1),
    )
    push_token = "ExponentPushToken[abcdefghijklmnopqrstuv]"
    registration = MobilePushRegistrationModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        session_id=device_session.id,
        provider="expo",
        platform="android",
        environment="development",
        app_bundle_id="com.globalconnects.groupcompanion",
        token_ciphertext=mobile_push_fernet().encrypt(push_token.encode("utf-8")),
        token_lookup_hash="7" * 64,
        token_key_version=1,
        status="active",
        notifications_authorized=True,
    )
    notification = _announcement_notification(
        recipient_id=passenger.id,
        recipient_type="passenger",
        access=access,
        announcement=announcement,
        available_at=now,
        expires_at=None,
    )
    db_session.add_all(
        [
            group,
            access,
            announcement,
            passenger,
            device_session,
            registration,
            notification,
        ]
    )
    await db_session.flush()

    class RecordingProvider:
        name = "expo"
        enabled = True

        def __init__(self) -> None:
            self.messages: list[MobilePushMessage] = []

        async def send(self, messages: list[MobilePushMessage]) -> list[MobilePushTicket]:
            self.messages = messages
            return [
                MobilePushTicket(
                    registration_id=message.registration_id,
                    notification_id=message.notification_id,
                    accepted=True,
                    retryable=False,
                    provider_ticket_id=f"ticket-{message.notification_id}",
                )
                for message in messages
            ]

    provider = RecordingProvider()
    delivered = await dispatch_mobile_push_batch(
        db_session,
        provider=provider,
        limit=100,
        now=now + timedelta(seconds=1),
    )

    assert delivered == 1
    assert len(provider.messages) == 1
    assert provider.messages[0].token == push_token
    assert provider.messages[0].body is None
    assert set(provider.messages[0].data) == {"route", "trip_id", "event_id"}
    assert notification.status == "queued"
    assert notification.sent_at is None
    assert notification.available_at == now
    assert registration.last_success_at is None
    delivery = (
        await db_session.execute(select(MobilePushDeliveryModel))
    ).scalar_one()
    assert delivery.status == "receipt_pending"
    assert delivery.provider_ticket_id == f"ticket-{notification.id}"
    assert delivery.send_attempts == 1


@pytest.mark.asyncio
async def test_dispatch_cancels_group_push_after_recipient_access_is_revoked(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(tz=UTC)
    _registration, notification = await _persist_push_target(db_session, now=now)
    passenger = await db_session.get(
        MobilePassengerIdentityModel,
        notification.recipient_passenger_identity_id,
    )
    assert passenger is not None
    passenger.status = "revoked"
    passenger.revoked_at = now
    await db_session.flush()

    class RecordingProvider:
        name = "expo"
        enabled = True

        def __init__(self) -> None:
            self.messages: list[MobilePushMessage] = []

        async def send(self, messages: list[MobilePushMessage]) -> list[MobilePushTicket]:
            self.messages = messages
            return []

    provider = RecordingProvider()
    delivered = await dispatch_mobile_push_batch(
        db_session,
        provider=provider,
        limit=100,
        now=now + timedelta(seconds=1),
    )

    assert delivered == 0
    assert provider.messages == []
    assert notification.status == "cancelled"
    assert notification.failure_code == "recipient_access_revoked"


@pytest.mark.asyncio
async def test_receipt_confirmation_marks_notification_sent_once(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(tz=UTC)
    registration, notification = await _persist_push_target(db_session, now=now)
    delivery = MobilePushDeliveryModel(
        id=uuid.uuid4(),
        agency_id=notification.agency_id,
        notification_id=notification.id,
        registration_id=registration.id,
        provider="expo",
        provider_ticket_id="ticket-confirmed",
        status="receipt_pending",
        send_attempts=1,
        receipt_attempts=0,
        next_attempt_at=now,
        submitted_at=now - timedelta(minutes=15),
    )
    db_session.add(delivery)
    await db_session.flush()

    class ReceiptProvider:
        name = "expo"
        enabled = True

        async def send(
            self, messages: list[MobilePushMessage]
        ) -> list[MobilePushTicket]:
            raise AssertionError(messages)

        async def get_receipts(
            self, provider_ticket_ids: list[str]
        ) -> list[MobilePushReceipt]:
            return [
                MobilePushReceipt(
                    provider_ticket_id=item,
                    delivered=True,
                    retryable=False,
                )
                for item in provider_ticket_ids
            ]

    provider = ReceiptProvider()
    confirmed = await reconcile_mobile_push_receipts(
        db_session,
        provider=provider,
        limit=100,
        now=now,
    )
    confirmed_again = await reconcile_mobile_push_receipts(
        db_session,
        provider=provider,
        limit=100,
        now=now + timedelta(minutes=1),
    )

    assert confirmed == 1
    assert confirmed_again == 0
    assert delivery.status == "delivered"
    assert delivery.delivered_at == now
    assert notification.status == "sent"
    assert notification.sent_at == now
    assert registration.last_success_at == now


@pytest.mark.asyncio
async def test_send_retry_reuses_one_delivery_row_and_respects_due_time(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(tz=UTC)
    _registration, notification = await _persist_push_target(db_session, now=now)

    class RetryThenAcceptProvider:
        name = "expo"
        enabled = True

        def __init__(self) -> None:
            self.send_calls = 0

        async def send(
            self, messages: list[MobilePushMessage]
        ) -> list[MobilePushTicket]:
            self.send_calls += 1
            if self.send_calls == 1:
                return [
                    MobilePushTicket(
                        registration_id=item.registration_id,
                        notification_id=item.notification_id,
                        accepted=False,
                        retryable=True,
                        error_code="provider_unavailable",
                    )
                    for item in messages
                ]
            return [
                MobilePushTicket(
                    registration_id=item.registration_id,
                    notification_id=item.notification_id,
                    accepted=True,
                    retryable=False,
                    provider_ticket_id="ticket-after-retry",
                )
                for item in messages
            ]

        async def get_receipts(
            self, provider_ticket_ids: list[str]
        ) -> list[MobilePushReceipt]:
            raise AssertionError(provider_ticket_ids)

    provider = RetryThenAcceptProvider()
    first = await dispatch_mobile_push_batch(
        db_session,
        provider=provider,
        limit=100,
        now=now,
        retry_base_seconds=5,
    )
    too_early = await dispatch_mobile_push_batch(
        db_session,
        provider=provider,
        limit=100,
        now=now + timedelta(seconds=1),
        retry_base_seconds=5,
    )
    second = await dispatch_mobile_push_batch(
        db_session,
        provider=provider,
        limit=100,
        now=now + timedelta(seconds=5),
        retry_base_seconds=5,
    )
    deliveries = list(
        (await db_session.execute(select(MobilePushDeliveryModel))).scalars()
    )

    assert first == 0
    assert too_early == 0
    assert second == 1
    assert provider.send_calls == 2
    assert len(deliveries) == 1
    assert deliveries[0].send_attempts == 2
    assert deliveries[0].status == "receipt_pending"
    assert deliveries[0].provider_ticket_id == "ticket-after-retry"
    assert notification.status == "queued"


@pytest.mark.asyncio
async def test_receipt_device_not_registered_revokes_registration(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(tz=UTC)
    registration, notification = await _persist_push_target(db_session, now=now)
    delivery = MobilePushDeliveryModel(
        id=uuid.uuid4(),
        agency_id=notification.agency_id,
        notification_id=notification.id,
        registration_id=registration.id,
        provider="expo",
        provider_ticket_id="ticket-revoked",
        status="receipt_pending",
        send_attempts=1,
        receipt_attempts=0,
        next_attempt_at=now,
        submitted_at=now - timedelta(minutes=15),
    )
    db_session.add(delivery)
    await db_session.flush()

    class RevokedProvider:
        name = "expo"
        enabled = True

        async def send(
            self, messages: list[MobilePushMessage]
        ) -> list[MobilePushTicket]:
            raise AssertionError(messages)

        async def get_receipts(
            self, provider_ticket_ids: list[str]
        ) -> list[MobilePushReceipt]:
            return [
                MobilePushReceipt(
                    provider_ticket_id=item,
                    delivered=False,
                    retryable=False,
                    error_code="DeviceNotRegistered",
                )
                for item in provider_ticket_ids
            ]

    confirmed = await reconcile_mobile_push_receipts(
        db_session,
        provider=RevokedProvider(),
        limit=100,
        now=now,
    )

    assert confirmed == 0
    assert delivery.status == "failed"
    assert delivery.last_error_code == "DeviceNotRegistered"
    assert notification.status == "failed"
    assert registration.status == "revoked"
    assert registration.notifications_authorized is False
    assert registration.revoked_at == now


@pytest.mark.asyncio
async def test_receipt_reconciliation_fails_closed_on_tenant_scope_mismatch(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(tz=UTC)
    registration, notification = await _persist_push_target(db_session, now=now)
    delivery = MobilePushDeliveryModel(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        notification_id=notification.id,
        registration_id=registration.id,
        provider="expo",
        provider_ticket_id="ticket-wrong-tenant",
        status="receipt_pending",
        send_attempts=1,
        receipt_attempts=0,
        next_attempt_at=now,
        submitted_at=now - timedelta(minutes=15),
    )
    db_session.add(delivery)
    await db_session.flush()

    class NeverCalledProvider:
        name = "expo"
        enabled = True

        async def send(
            self, messages: list[MobilePushMessage]
        ) -> list[MobilePushTicket]:
            raise AssertionError(messages)

        async def get_receipts(
            self, provider_ticket_ids: list[str]
        ) -> list[MobilePushReceipt]:
            raise AssertionError(provider_ticket_ids)

    confirmed = await reconcile_mobile_push_receipts(
        db_session,
        provider=NeverCalledProvider(),
        limit=100,
        now=now,
    )

    assert confirmed == 0
    assert delivery.status == "failed"
    assert delivery.last_error_code == "tenant_scope_mismatch"
    assert notification.status == "failed"


@pytest.mark.asyncio
async def test_missing_receipt_retries_with_backoff_then_fails_bounded(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(tz=UTC)
    registration, notification = await _persist_push_target(db_session, now=now)
    delivery = MobilePushDeliveryModel(
        id=uuid.uuid4(),
        agency_id=notification.agency_id,
        notification_id=notification.id,
        registration_id=registration.id,
        provider="expo",
        provider_ticket_id="ticket-late",
        status="receipt_pending",
        send_attempts=1,
        receipt_attempts=0,
        next_attempt_at=now,
        submitted_at=now - timedelta(minutes=15),
    )
    db_session.add(delivery)
    await db_session.flush()

    class MissingReceiptProvider:
        name = "expo"
        enabled = True

        async def send(
            self, messages: list[MobilePushMessage]
        ) -> list[MobilePushTicket]:
            raise AssertionError(messages)

        async def get_receipts(
            self, provider_ticket_ids: list[str]
        ) -> list[MobilePushReceipt]:
            del provider_ticket_ids
            return []

    provider = MissingReceiptProvider()
    first = await reconcile_mobile_push_receipts(
        db_session,
        provider=provider,
        limit=100,
        now=now,
        max_attempts=2,
        retry_base_seconds=60,
    )

    assert first == 0
    assert delivery.status == "receipt_pending"
    assert delivery.receipt_attempts == 1
    assert delivery.next_attempt_at == now + timedelta(seconds=60)
    assert notification.status == "queued"

    second = await reconcile_mobile_push_receipts(
        db_session,
        provider=provider,
        limit=100,
        now=now + timedelta(seconds=60),
        max_attempts=2,
        retry_base_seconds=60,
    )

    assert second == 0
    assert delivery.status == "failed"
    assert delivery.receipt_attempts == 2
    assert delivery.last_error_code == "provider_missing_receipt_response"
    assert notification.status == "failed"


@pytest.mark.asyncio
async def test_receipt_is_not_polled_after_provider_retention_window(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(tz=UTC)
    registration, notification = await _persist_push_target(db_session, now=now)
    delivery = MobilePushDeliveryModel(
        id=uuid.uuid4(),
        agency_id=notification.agency_id,
        notification_id=notification.id,
        registration_id=registration.id,
        provider="expo",
        provider_ticket_id="ticket-expired",
        status="receipt_pending",
        send_attempts=1,
        receipt_attempts=0,
        next_attempt_at=now,
        submitted_at=now - timedelta(hours=23),
    )
    db_session.add(delivery)
    await db_session.flush()

    class NeverCalledProvider:
        name = "expo"
        enabled = True

        async def send(
            self, messages: list[MobilePushMessage]
        ) -> list[MobilePushTicket]:
            raise AssertionError(messages)

        async def get_receipts(
            self, provider_ticket_ids: list[str]
        ) -> list[MobilePushReceipt]:
            raise AssertionError(provider_ticket_ids)

    confirmed = await reconcile_mobile_push_receipts(
        db_session,
        provider=NeverCalledProvider(),
        limit=100,
        now=now,
        max_age=timedelta(hours=23),
    )

    assert confirmed == 0
    assert delivery.status == "failed"
    assert delivery.last_error_code == "receipt_expired"
    assert notification.status == "failed"
    assert registration.last_failure_code == "receipt_expired"


@pytest.mark.asyncio
async def test_passenger_notification_producer_pages_beyond_250(
    db_session: AsyncSession,
) -> None:
    access = _access()
    access.client_manager_access_enabled = False
    access.coordinator_access_enabled = False
    announcement = _announcement(access)
    identities = [
        MobilePassengerIdentityModel(
            id=uuid.uuid4(),
            agency_id=access.agency_id,
            group_id=access.group_id,
            gc_group_access_id=access.id,
            passenger_submission_id=uuid.uuid4(),
            normalized_phone_number=f"+91{index:010d}",
            phone_lookup_hash=f"{index:064x}",
            status="eligible",
        )
        for index in range(251)
    ]
    db_session.add_all([access, announcement, *identities])
    await db_session.flush()

    counts = await enqueue_announcement_notifications(
        db_session,
        access=access,
        announcement=announcement,
    )
    notifications = list(
        (
            await db_session.execute(select(MobileNotificationModel.id))
        ).scalars()
    )

    assert counts.passengers == 251
    assert len(notifications) == 251
