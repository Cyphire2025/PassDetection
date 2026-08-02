from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.notification_service import (
    _announcement_notification,
    dispatch_mobile_push_batch,
    enqueue_announcement_notifications,
)
from app.application.mobile.push_provider import (
    DisabledMobilePushProvider,
    MobilePushMessage,
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
    MobilePushRegistrationModel,
)
from app.infrastructure.database.models import CoordinatorGroupAssignmentModel, UserModel


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


@pytest.mark.asyncio
async def test_dispatch_uses_encrypted_token_and_marks_ticket_sent(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(tz=UTC)
    access = _access()
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
        [access, announcement, passenger, device_session, registration, notification]
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
    assert notification.status == "sent"
    assert notification.sent_at is not None
    assert registration.last_success_at is not None


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
