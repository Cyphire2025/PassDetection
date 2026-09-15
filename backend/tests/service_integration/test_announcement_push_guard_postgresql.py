"""Real row locks serialize withdrawal and fake-provider push dispatch safely."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from app.application.mobile.announcement_push_guard import (
    retain_dispatchable_announcement_notifications,
)
from app.application.mobile.notification_service import (
    _announcement_notification,
    cancel_announcement_notifications,
    dispatch_mobile_push_batch,
    reconcile_mobile_push_receipts,
)
from app.application.mobile.push_provider import MobilePushReceipt
from app.core.security.mobile_push_crypto import mobile_push_fernet
from app.infrastructure.database.gc_mobile_models import (
    ClientOrganizationModel,
    GCAnnouncementModel,
    GCGroupAccessModel,
    MobileDeviceSessionModel,
    MobileNotificationModel,
    MobilePushDeliveryModel,
    MobilePushRegistrationModel,
)
from app.infrastructure.database.models import (
    AgencyModel,
    CoordinatorGroupAssignmentModel,
    UserModel,
)
from tests.service_integration.test_whatsapp_receipts_postgresql import pg_factory as pg_factory
from tests.unit.application.test_announcement_push_guard import RecordingProvider
from tests.unit.application.test_mobile_notification_service import _access, _announcement, _group

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required"
    ),
]


@pytest.fixture
async def push_target(pg_factory):
    now = datetime.now(UTC)
    access = _access()
    group = _group(access)
    source = _announcement(access)
    user = UserModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        email="push-guard@example.test",
        hashed_password="synthetic-not-a-real-password-hash",
        full_name="Synthetic coordinator",
        role="agency_coordinator",
        is_active=True,
    )
    device = MobileDeviceSessionModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        subject_role="coordinator",
        user_id=user.id,
        account_id=user.id,
        selected_gc_group_access_id=access.id,
        selected_group_id=access.group_id,
        device_identifier_hash=uuid.uuid4().hex * 2,
        platform="android",
        app_version="1.0.0",
        status="active",
        expires_at=now + timedelta(days=1),
    )
    registration = MobilePushRegistrationModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        session_id=device.id,
        provider="expo",
        platform="android",
        environment="development",
        app_bundle_id="com.example.synthetic",
        token_ciphertext=mobile_push_fernet().encrypt(b"ExponentPushToken[synthetic-only]"),
        token_lookup_hash=uuid.uuid4().hex * 2,
        token_key_version=1,
        status="active",
        notifications_authorized=True,
    )
    notification = _announcement_notification(
        recipient_id=user.id,
        recipient_type="coordinator",
        access=access,
        announcement=source,
        available_at=now,
        expires_at=None,
    )
    async with pg_factory() as session:
        session.add(AgencyModel(id=access.agency_id, name="Synthetic", email="agency@example.test"))
        await session.flush()
        session.add_all(
            [
                group,
                user,
                ClientOrganizationModel(
                    id=access.client_organization_id,
                    agency_id=access.agency_id,
                    name="Synthetic client",
                    normalized_name="synthetic client",
                ),
            ]
        )
        await session.flush()
        session.add(access)
        await session.flush()
        session.add_all(
            [
                source,
                device,
                CoordinatorGroupAssignmentModel(
                    agency_id=access.agency_id,
                    group_id=access.group_id,
                    coordinator_user_id=user.id,
                    active=True,
                ),
            ]
        )
        await session.flush()
        session.add_all([registration, notification])
        await session.commit()
    return now, access.id, source.id, notification.id


async def _wait_blocked(factory, pid):
    async with factory() as observer:
        for _ in range(100):
            if await observer.scalar(
                text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                {"pid": pid},
            ):
                return
            await asyncio.sleep(0.02)
    raise AssertionError("Expected competing transaction to wait on a row lock")


@pytest.mark.parametrize("withdrawal_commits", [True, False])
async def test_source_locked_first_defers_without_deadlock_or_wrong_cancellation(
    pg_factory,
    push_target,
    withdrawal_commits,
):
    now, access_id, source_id, notification_id = push_target
    provider = RecordingProvider()
    source_locked = asyncio.Event()
    contender_pid = []

    async def withdraw():
        async with pg_factory() as session:
            contender_pid.append(await session.scalar(text("SELECT pg_backend_pid()")))
            access = await session.scalar(
                select(GCGroupAccessModel)
                .where(GCGroupAccessModel.id == access_id)
                .with_for_update(),
            )
            source = await session.scalar(
                select(GCAnnouncementModel)
                .where(GCAnnouncementModel.id == source_id)
                .with_for_update(),
            )
            source.status = "retired"
            source.retired_at = now
            await session.flush()
            source_locked.set()
            await cancel_announcement_notifications(
                session, access=access, announcement_id=source_id
            )
            if withdrawal_commits:
                await session.commit()
            else:
                await session.rollback()

    async with pg_factory() as dispatch_session:
        # Reproduce the dangerous opposing order: dispatch has the notification,
        # withdrawal has the source and waits for that same notification.
        notification = await dispatch_session.scalar(
            select(MobileNotificationModel)
            .where(MobileNotificationModel.id == notification_id)
            .with_for_update(),
        )
        contender = asyncio.create_task(withdraw())
        try:
            await asyncio.wait_for(source_locked.wait(), timeout=5)
            await _wait_blocked(pg_factory, contender_pid[0])
            assert (
                await asyncio.wait_for(
                    dispatch_mobile_push_batch(
                        dispatch_session,
                        provider=provider,
                        limit=100,
                        now=now,
                    ),
                    timeout=2,
                )
                == 0
            )
            assert notification.status == "queued"
            assert notification.failure_code is None
            assert provider.calls == 0
            await dispatch_session.commit()
            await asyncio.wait_for(contender, timeout=5)
        finally:
            if not contender.done():
                contender.cancel()
            await asyncio.gather(contender, return_exceptions=True)

    async with pg_factory() as session:
        notification = await session.get(MobileNotificationModel, notification_id)
        assert notification.status == ("cancelled" if withdrawal_commits else "queued")
        assert await _legacy_guard_then_dispatch(
            session,
            provider=provider,
            limit=100,
            now=now,
        ) == 0
        await session.commit()
    assert provider.calls == 0


async def test_legacy_source_guard_lock_is_held_until_commit_without_phone_send(
    pg_factory, push_target
):
    now, access_id, source_id, notification_id = push_target
    send_entered, release_send, withdrawal_started = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )
    contender_pid = []

    provider = RecordingProvider()

    async def dispatch():
        async with pg_factory() as session:
            notification = await session.scalar(select(MobileNotificationModel).where(
                MobileNotificationModel.id == notification_id).with_for_update())
            retained = await retain_dispatchable_announcement_notifications(
                session, notifications=[notification], now=now)
            assert retained == [notification]
            send_entered.set()
            await release_send.wait()
            await session.commit()
            return len(retained)

    async def withdraw():
        async with pg_factory() as session:
            contender_pid.append(await session.scalar(text("SELECT pg_backend_pid()")))
            access = await session.scalar(
                select(GCGroupAccessModel)
                .where(GCGroupAccessModel.id == access_id)
                .with_for_update(),
            )
            withdrawal_started.set()
            source = await session.scalar(
                select(GCAnnouncementModel)
                .where(GCAnnouncementModel.id == source_id)
                .with_for_update(),
            )
            source.status = "retired"
            source.retired_at = now
            await session.flush()
            await cancel_announcement_notifications(
                session, access=access, announcement_id=source_id
            )
            await session.commit()

    first = asyncio.create_task(dispatch())
    second = None
    try:
        await asyncio.wait_for(send_entered.wait(), timeout=5)
        second = asyncio.create_task(withdraw())
        await asyncio.wait_for(withdrawal_started.wait(), timeout=5)
        await _wait_blocked(pg_factory, contender_pid[0])
        assert not second.done()  # The legacy source guard holds its lock until commit.
        release_send.set()
        assert await asyncio.wait_for(first, timeout=5) == 1
        await asyncio.wait_for(second, timeout=5)
    finally:
        release_send.set()
        for task in (first, second):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in (first, second) if task), return_exceptions=True)

    async with pg_factory() as session:
        assert (await session.get(GCAnnouncementModel, source_id)).status == "retired"
        assert (await session.get(MobileNotificationModel, notification_id)).status == "cancelled"
        delivery = await session.scalar(select(MobilePushDeliveryModel))
        assert delivery is None
        assert await _legacy_guard_then_dispatch(session, provider=provider, limit=100, now=now) == 0
    assert provider.calls == 0  # Announcements are now exclusively in-app.


class ReceiptProvider(RecordingProvider):
    def __init__(self):
        super().__init__()
        self.receipt_calls = 0

    async def get_receipts(self, provider_ticket_ids):
        self.receipt_calls += 1
        return [
            MobilePushReceipt(provider_ticket_id=item, delivered=True, retryable=False)
            for item in provider_ticket_ids
        ]


async def _submit_ticket(factory, now):
    """Seed accepted history from before the in-app-only release for receipt recovery."""
    async with factory() as session:
        notification = await session.scalar(select(MobileNotificationModel))
        registration = await session.scalar(select(MobilePushRegistrationModel))
        session.add(MobilePushDeliveryModel(
            id=uuid.uuid4(), agency_id=notification.agency_id, notification_id=notification.id,
            registration_id=registration.id, provider="expo", status="receipt_pending",
            provider_ticket_id=f"ticket-{notification.id}", send_attempts=1,
            receipt_attempts=0, next_attempt_at=now, submitted_at=now,
        ))
        await session.commit()


@pytest.mark.parametrize("canceller", ["source_guard", "unpublish"])
async def test_receipt_refreshes_stale_parent_and_cannot_resurrect_cancelled_notification(
    pg_factory,
    push_target,
    canceller,
):
    now, access_id, source_id, notification_id = push_target
    await _submit_ticket(pg_factory, now)
    provider = ReceiptProvider()
    async with pg_factory() as receipt_session:
        cached_notification = await receipt_session.get(MobileNotificationModel, notification_id)
        assert cached_notification.status == "queued"
        async with pg_factory() as cancellation_session:
            source = await cancellation_session.get(GCAnnouncementModel, source_id)
            source.status = "retired"
            source.retired_at = now
            if canceller == "source_guard":
                assert (
                    await _legacy_guard_then_dispatch(
                        cancellation_session,
                        provider=provider,
                        limit=100,
                        now=now,
                    )
                    == 0
                )
            else:
                access = await cancellation_session.get(GCGroupAccessModel, access_id)
                await cancel_announcement_notifications(
                    cancellation_session,
                    access=access,
                    announcement_id=source_id,
                )
            await cancellation_session.commit()
        assert cached_notification.status == "queued"  # Deliberately stale ORM identity.
        assert (
            await reconcile_mobile_push_receipts(
                receipt_session,
                provider=provider,
                limit=100,
                now=now + timedelta(minutes=16),
            )
            == 1
        )
        await receipt_session.commit()
        assert cached_notification.status == "cancelled"
    async with pg_factory() as session:
        notification = await session.get(MobileNotificationModel, notification_id)
        delivery = await session.scalar(select(MobilePushDeliveryModel))
        assert notification.status == "cancelled"
        assert notification.failure_code == "announcement_unpublished"
        assert delivery.status == "delivered"
        assert delivery.provider_ticket_id == f"ticket-{notification_id}"
    assert provider.calls == 0
    assert provider.receipt_calls == 1


async def test_withdrawal_waits_for_receipt_and_cancellation_wins_without_deadlock(
    pg_factory,
    push_target,
):
    now, access_id, source_id, notification_id = push_target
    await _submit_ticket(pg_factory, now)
    entered, release, source_locked = asyncio.Event(), asyncio.Event(), asyncio.Event()
    contender_pid = []

    class PausedReceiptProvider(ReceiptProvider):
        async def get_receipts(self, provider_ticket_ids):
            entered.set()
            await release.wait()
            return await super().get_receipts(provider_ticket_ids)

    provider = PausedReceiptProvider()
    receipt_now = now + timedelta(minutes=16)

    async def reconcile():
        async with pg_factory() as session:
            result = await reconcile_mobile_push_receipts(
                session,
                provider=provider,
                limit=100,
                now=receipt_now,
            )
            await session.commit()
            return result

    async def withdraw():
        async with pg_factory() as session:
            contender_pid.append(await session.scalar(text("SELECT pg_backend_pid()")))
            access = await session.scalar(
                select(GCGroupAccessModel)
                .where(GCGroupAccessModel.id == access_id)
                .with_for_update(),
            )
            source = await session.scalar(
                select(GCAnnouncementModel)
                .where(GCAnnouncementModel.id == source_id)
                .with_for_update(),
            )
            source.status = "retired"
            source.retired_at = now
            await session.flush()
            source_locked.set()
            await cancel_announcement_notifications(
                session, access=access, announcement_id=source_id
            )
            await session.commit()

    first, second = asyncio.create_task(reconcile()), None
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        second = asyncio.create_task(withdraw())
        await asyncio.wait_for(source_locked.wait(), timeout=5)
        await _wait_blocked(pg_factory, contender_pid[0])
        # A second receipt worker defers the locked parent instead of locking a
        # child delivery first, and cannot misclassify that parent as missing.
        competing_provider = ReceiptProvider()
        async with pg_factory() as session:
            # Measure nonblocking SQL, not DNS/IPv6 fallback during a new local
            # test-service connection (the fixture deliberately uses NullPool).
            await session.connection()
            assert (
                await asyncio.wait_for(
                    reconcile_mobile_push_receipts(
                        session,
                        provider=competing_provider,
                        limit=100,
                        now=receipt_now,
                    ),
                    timeout=2,
                )
                == 0
            )
        assert competing_provider.receipt_calls == 0
        release.set()
        assert await asyncio.wait_for(first, timeout=5) == 1
        await asyncio.wait_for(second, timeout=5)
    finally:
        release.set()
        for task in (first, second):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in (first, second) if task), return_exceptions=True)
    async with pg_factory() as session:
        assert (await session.get(MobileNotificationModel, notification_id)).status == "cancelled"
        delivery = await session.scalar(select(MobilePushDeliveryModel))
        assert delivery.status == "delivered"
        assert delivery.provider_ticket_id == f"ticket-{notification_id}"
    assert provider.calls == 0
    assert provider.receipt_calls == 1


async def _legacy_guard_then_dispatch(session, *, provider, limit, now):
    """Exercise legacy source/receipt ordering independently of the new push exclusion."""
    rows = list(await session.scalars(select(MobileNotificationModel).with_for_update(skip_locked=True)))
    await retain_dispatchable_announcement_notifications(session, notifications=rows, now=now)
    return await dispatch_mobile_push_batch(session, provider=provider, limit=limit, now=now)
