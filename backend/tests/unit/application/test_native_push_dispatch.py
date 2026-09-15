"""Real database boundaries for mixed Android/iPhone dispatch without live sends."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.application.mobile.notification_service import dispatch_mobile_push_batch
from app.core.security.mobile_push_crypto import mobile_push_fernet
from app.infrastructure.database.gc_mobile_models import (
    MobileDeviceSessionModel,
    MobilePushDeliveryModel,
)
from tests.unit.application.test_fcm_dispatch_intents import (
    FcmProvider,
    _additional_device,
    _target,
)


class ApnsProvider(FcmProvider):
    name = "apns"


async def _ios(session, registration):
    registration.provider = "apns"
    registration.platform = "ios"
    registration.apns_environment = "development"
    registration.token_ciphertext = mobile_push_fernet().encrypt(b"a1" * 32)
    device = await session.get(MobileDeviceSessionModel, registration.session_id)
    device.platform = "ios"
    await session.flush()


@pytest.mark.parametrize("ios_first", [False, True])
async def test_each_native_platform_gets_its_own_attempt_after_sibling_acceptance(db_session, ios_first):
    now = datetime.now(UTC)
    android, notification = await _target(db_session, now)
    ios = await _additional_device(db_session, android, now)
    await _ios(db_session, ios)
    fcm, apns = FcmProvider(), ApnsProvider()
    first, second = (apns, fcm) if ios_first else (fcm, apns)
    assert await dispatch_mobile_push_batch(db_session, provider=first, limit=1, now=now) == 1
    await db_session.commit()
    rows = list(await db_session.scalars(select(MobilePushDeliveryModel)))
    assert len(rows) == 2 and {row.status for row in rows} == {"retry", "provider_accepted"}
    assert notification.status == "sent"
    assert await dispatch_mobile_push_batch(db_session, provider=second, limit=1, now=now) == 1
    await db_session.commit()
    assert all(row.status == "provider_accepted" and row.send_attempts == 1 for row in rows)
    assert all(row.delivered_at is None for row in rows)
    assert apns.calls[0][0].apns_environment == "development"
    for provider in (fcm, apns):
        assert await dispatch_mobile_push_batch(db_session, provider=provider, limit=1, now=now) == 0
        assert len(provider.calls) == 1


async def test_ios_only_recipient_is_not_delayed_by_android_scan_and_does_not_starve_android(db_session):
    now = datetime.now(UTC)
    ios, notification = await _target(db_session, now)
    await _ios(db_session, ios)
    fcm = FcmProvider()
    assert await dispatch_mobile_push_batch(db_session, provider=fcm, limit=1, now=now) == 0
    await db_session.commit()
    assert notification.available_at == now
    android, _ = await _target(db_session, now + timedelta(seconds=1))
    assert await dispatch_mobile_push_batch(db_session, provider=fcm, limit=1, now=now + timedelta(seconds=2)) == 1
    assert fcm.calls[0][0].registration_id == str(android.id)
    apns = ApnsProvider()
    assert await dispatch_mobile_push_batch(db_session, provider=apns, limit=1, now=now + timedelta(seconds=2)) == 1
    assert apns.calls[0][0].registration_id == str(ios.id)


async def test_interrupted_ios_attempt_is_recovered_as_unknown_and_not_repeated(db_session):
    now = datetime.now(UTC)
    ios, _ = await _target(db_session, now)
    await _ios(db_session, ios)
    provider = ApnsProvider(interrupt=True)
    with pytest.raises(RuntimeError, match="worker interrupted"):
        await dispatch_mobile_push_batch(db_session, provider=provider, limit=20, now=now)
    await db_session.rollback()
    provider.interrupt = False
    assert await dispatch_mobile_push_batch(db_session, provider=provider, limit=20, now=now + timedelta(minutes=16)) == 0
    row = (await db_session.scalars(select(MobilePushDeliveryModel))).one()
    assert row.status == "unknown" and row.send_attempts == 1 and len(provider.calls) == 1


@pytest.mark.parametrize("provider", [FcmProvider, ApnsProvider])
async def test_published_announcements_never_create_native_phone_attempts(db_session, provider):
    now = datetime.now(UTC)
    registration, notification = await _target(db_session, now)
    if provider is ApnsProvider:
        await _ios(db_session, registration)
    notification.notification_type = "group_announcement"
    await db_session.flush()
    transport = provider()
    assert await dispatch_mobile_push_batch(db_session, provider=transport, limit=20, now=now) == 0
    assert not transport.calls
    assert await db_session.scalar(select(MobilePushDeliveryModel)) is None
    assert notification.status == "queued"
