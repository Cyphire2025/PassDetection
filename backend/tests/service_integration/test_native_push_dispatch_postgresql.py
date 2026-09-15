"""Mixed native delivery proofs in retained, isolated PostgreSQL schemas only.

No Apple/Google client is constructed. Run with the explicit FCM PostgreSQL
test database settings and FCM_TEST_KEEP_SCHEMA=1; all schema/data is retained.
"""

from __future__ import annotations

import os
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.application.mobile.notification_service import dispatch_mobile_push_batch
from app.core.security.mobile_push_crypto import mobile_push_fernet
from app.infrastructure.database.gc_mobile_models import (
    MobileDeviceSessionModel,
    MobileNotificationModel,
    MobilePushDeliveryModel,
    MobilePushRegistrationModel,
)
from tests.service_integration.test_fcm_dispatch_postgresql import (
    FakeFcmProvider,
)
from tests.service_integration.test_fcm_dispatch_postgresql import (
    fcm_target as fcm_target,
)
from tests.service_integration.test_fcm_dispatch_postgresql import (
    pg_factory as pg_factory,
)
from tests.service_integration.test_fcm_dispatch_postgresql import (
    push_target as push_target,
)

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1",
        reason="explicit isolated PostgreSQL acceptance environment required",
    ),
]


@pytest.fixture(autouse=True)
def require_retained_schema():
    assert os.getenv("FCM_TEST_KEEP_SCHEMA") == "1", "Native push proofs require retained schemas"


class FakeApnsProvider(FakeFcmProvider):
    name = "apns"


async def _ios_registration(factory, registration_id, *, sibling):
    async with factory() as session:
        registration = await session.get(MobilePushRegistrationModel, registration_id)
        device = await session.get(MobileDeviceSessionModel, registration.session_id)
        if sibling:
            device = MobileDeviceSessionModel(
                id=uuid.uuid4(),
                agency_id=device.agency_id,
                subject_role=device.subject_role,
                user_id=device.user_id,
                account_id=device.account_id,
                selected_gc_group_access_id=device.selected_gc_group_access_id,
                selected_group_id=device.selected_group_id,
                device_identifier_hash=uuid.uuid4().hex * 2,
                platform="ios",
                app_version="1.0.6",
                status="active",
                expires_at=device.expires_at,
            )
            session.add(device)
            await session.flush()
            registration = MobilePushRegistrationModel(
                id=uuid.uuid4(),
                agency_id=device.agency_id,
                session_id=device.id,
                provider="apns",
                platform="ios",
                environment=registration.environment,
                app_bundle_id=registration.app_bundle_id,
                token_lookup_hash=uuid.uuid4().hex * 2,
                token_key_version=1,
                status="active",
                notifications_authorized=True,
            )
            session.add(registration)
        device.platform = "ios"
        registration.provider = "apns"
        registration.platform = "ios"
        registration.apns_environment = "development"
        registration.token_ciphertext = mobile_push_fernet().encrypt(b"ab" * 32)
        await session.commit()
        return registration.id


@pytest.mark.parametrize("ios_first", [False, True])
async def test_native_sibling_is_committed_before_parent_sent_and_both_orders_send_once(
    pg_factory, fcm_target, ios_first
):
    now, _, _, notification_id, android_id = fcm_target
    ios_id = await _ios_registration(pg_factory, android_id, sibling=True)
    observed = []

    async def observe_first_http(messages):
        async with pg_factory() as observer:
            rows = list(await observer.scalars(select(MobilePushDeliveryModel)))
            assert len(rows) == 2
            own = next(
                row for row in rows if str(row.registration_id) == messages[0].registration_id
            )
            sibling = next(row for row in rows if row.id != own.id)
            assert own.status == "submitting" and own.send_attempts == 1
            assert sibling.status == "retry" and sibling.send_attempts == 0
            assert sibling.provider_ticket_id is None
            observed.append(own.id)

    first = (
        FakeApnsProvider(observe_first_http) if ios_first else FakeFcmProvider(observe_first_http)
    )
    second = FakeFcmProvider() if ios_first else FakeApnsProvider()
    async with pg_factory() as session:
        assert await dispatch_mobile_push_batch(session, provider=first, limit=1, now=now) == 1
        await session.commit()
    async with pg_factory() as session:
        parent = await session.get(MobileNotificationModel, notification_id)
        assert parent.status == "sent"
        assert await dispatch_mobile_push_batch(session, provider=second, limit=1, now=now) == 1
        await session.commit()
    async with pg_factory() as session:
        rows = list(await session.scalars(select(MobilePushDeliveryModel)))
        assert {row.registration_id for row in rows} == {android_id, ios_id}
        assert {row.provider for row in rows} == {"fcm", "apns"}
        assert all(row.status == "provider_accepted" and row.send_attempts == 1 for row in rows)
        assert all(row.provider_ticket_id is not None and row.delivered_at is None for row in rows)
        for provider in (first, second):
            assert (
                await dispatch_mobile_push_batch(session, provider=provider, limit=1, now=now) == 0
            )
        await session.commit()
    assert len(observed) == 1 and first.calls == 1 and second.calls == 1


async def test_ios_worker_interruption_keeps_committed_unknown_intent_without_resend(
    pg_factory, fcm_target
):
    now, _, _, notification_id, registration_id = fcm_target
    await _ios_registration(pg_factory, registration_id, sibling=False)

    async def interrupt(messages):
        assert len(messages) == 1 and messages[0].apns_environment == "development"
        raise RuntimeError("synthetic iOS worker interruption after possible send")

    interrupted = FakeApnsProvider(interrupt)
    async with pg_factory() as session:
        with pytest.raises(RuntimeError, match="synthetic iOS worker interruption"):
            await dispatch_mobile_push_batch(session, provider=interrupted, limit=20, now=now)
        await session.rollback()
    async with pg_factory() as observer:
        row = await observer.scalar(select(MobilePushDeliveryModel))
        assert row.status == "submitting" and row.send_attempts == 1
        assert row.provider == "apns" and row.provider_ticket_id is None
    later = FakeApnsProvider()
    async with pg_factory() as session:
        assert (
            await dispatch_mobile_push_batch(
                session, provider=later, limit=20, now=now + timedelta(minutes=16)
            )
            == 0
        )
        await session.commit()
    async with pg_factory() as observer:
        row = await observer.scalar(select(MobilePushDeliveryModel))
        parent = await observer.get(MobileNotificationModel, notification_id)
        assert row.status == "unknown" and row.send_attempts == 1
        assert row.delivered_at is None and row.provider_ticket_id is None
        assert parent.failure_code == "provider_outcome_unknown"
    assert interrupted.calls == 1 and later.calls == 0


@pytest.mark.parametrize("provider_type", [FakeFcmProvider, FakeApnsProvider])
async def test_historical_group_announcement_cannot_create_native_phone_attempts(
    pg_factory, fcm_target, provider_type
):
    now, _, _, notification_id, registration_id = fcm_target
    if provider_type is FakeApnsProvider:
        await _ios_registration(pg_factory, registration_id, sibling=False)
    async with pg_factory() as session:
        notification = await session.get(MobileNotificationModel, notification_id)
        notification.notification_type = "group_announcement"
        await session.commit()
    provider = provider_type()
    async with pg_factory() as session:
        assert await dispatch_mobile_push_batch(session, provider=provider, limit=20, now=now) == 0
        await session.commit()
    async with pg_factory() as observer:
        assert await observer.scalar(select(MobilePushDeliveryModel)) is None
        assert (await observer.get(MobileNotificationModel, notification_id)).available_at == now
    assert provider.calls == 0


@pytest.mark.parametrize("provider_type", [FakeFcmProvider, FakeApnsProvider])
async def test_no_device_near_expiry_keeps_publication_time_and_separate_retry_schedule(
    pg_factory, fcm_target, provider_type
):
    now, _, _, notification_id, registration_id = fcm_target
    if provider_type is FakeApnsProvider:
        await _ios_registration(pg_factory, registration_id, sibling=False)
    async with pg_factory() as session:
        registration = await session.get(MobilePushRegistrationModel, registration_id)
        registration.status = "disabled"
        parent = await session.get(MobileNotificationModel, notification_id)
        parent.expires_at = now + timedelta(seconds=30)
        await session.commit()
    provider = provider_type()
    async with pg_factory() as session:
        assert await dispatch_mobile_push_batch(session, provider=provider, limit=20, now=now) == 0
        await session.commit()
    async with pg_factory() as session:
        parent = await session.get(MobileNotificationModel, notification_id)
        assert parent.available_at == now
        assert parent.next_push_attempt_at == now + timedelta(minutes=5)
        assert parent.expires_at == now + timedelta(seconds=30)
        assert parent.failure_code == "no_active_registration"
        assert await session.scalar(select(MobilePushDeliveryModel)) is None
        assert (
            await dispatch_mobile_push_batch(
                session, provider=provider, limit=20, now=now + timedelta(minutes=6)
            )
            == 0
        )
        await session.commit()
    async with pg_factory() as observer:
        parent = await observer.get(MobileNotificationModel, notification_id)
        assert parent.available_at == now and parent.expires_at == now + timedelta(seconds=30)
    assert provider.calls == 0
