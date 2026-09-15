from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.notification_service import (
    dispatch_mobile_push_batch,
    reconcile_mobile_push_receipts,
)
from app.application.mobile.push_provider import MobilePushMessage, MobilePushTicket
from app.core.security.mobile_push_crypto import mobile_push_fernet
from app.infrastructure.database.gc_mobile_models import (
    GCGroupAccessModel,
    MobileDeviceSessionModel,
    MobilePassengerSessionIdentityModel,
    MobilePushDeliveryModel,
    MobilePushRegistrationModel,
)
from tests.unit.application.test_mobile_notification_service import _persist_push_target


class FcmProvider:
    name = "fcm"
    enabled = True
    supports_receipts = False

    def __init__(self, *, unknown: bool = False, interrupt: bool = False, retry: bool = False):
        self.calls: list[list[MobilePushMessage]] = []
        self.unknown = unknown
        self.interrupt = interrupt
        self.retry = retry

    async def send(self, messages: list[MobilePushMessage]) -> list[MobilePushTicket]:
        self.calls.append(messages)
        if self.interrupt:
            raise RuntimeError("worker interrupted after possible provider acceptance")
        return [
            MobilePushTicket(
                registration_id=message.registration_id,
                notification_id=message.notification_id,
                accepted=not self.unknown and not self.retry,
                retryable=self.retry,
                provider_ticket_id=(
                    None
                    if self.unknown or self.retry
                    else f"projects/test/messages/{message.registration_id}"
                ),
                requires_receipt=False,
                outcome_unknown=self.unknown,
                error_code="fcm_quota_exceeded" if self.retry else None,
                retry_after_seconds=120 if self.retry else None,
            )
            for message in messages
        ]

    async def get_receipts(self, _: list[str]):
        raise AssertionError("FCM has no Expo-style receipt endpoint")


async def _target(session: AsyncSession, now: datetime):
    registration, notification = await _persist_push_target(session, now=now)
    registration.provider = "fcm"
    registration.token_ciphertext = mobile_push_fernet().encrypt(b"native-fcm-registration-token")
    await session.flush()
    return registration, notification


async def _additional_device(session, registration, now):
    original = await session.get(MobileDeviceSessionModel, registration.session_id)
    device = MobileDeviceSessionModel(
        id=uuid.uuid4(),
        agency_id=original.agency_id,
        subject_role=original.subject_role,
        user_id=original.user_id,
        account_id=original.account_id,
        passenger_identity_id=original.passenger_identity_id,
        passenger_subject_hash=original.passenger_subject_hash,
        selected_gc_group_access_id=original.selected_gc_group_access_id,
        selected_group_id=original.selected_group_id,
        device_identifier_hash=uuid.uuid4().hex * 2,
        platform="android",
        app_version="1.0.0",
        status="active",
        session_generation=0,
        refresh_family_id=uuid.uuid4(),
        expires_at=now + timedelta(days=1),
    )
    extra = MobilePushRegistrationModel(
        id=uuid.uuid4(),
        agency_id=registration.agency_id,
        session_id=device.id,
        provider="fcm",
        platform="android",
        environment="development",
        app_bundle_id=registration.app_bundle_id,
        token_ciphertext=mobile_push_fernet().encrypt(uuid.uuid4().hex.encode()),
        token_lookup_hash=uuid.uuid4().hex * 2,
        token_key_version=1,
        status="active",
        notifications_authorized=True,
        last_registered_at=now,
    )
    original_binding = await session.get(
        MobilePassengerSessionIdentityModel,
        (original.id, original.passenger_identity_id),
    )
    binding = MobilePassengerSessionIdentityModel(
        session_id=device.id, passenger_identity_id=original_binding.passenger_identity_id,
        agency_id=original_binding.agency_id, group_id=original_binding.group_id,
        gc_group_access_id=original_binding.gc_group_access_id,
        identity_claim_generation=original_binding.identity_claim_generation,
    )
    session.add_all([device, extra, binding])
    await session.flush()
    return extra


@pytest.mark.asyncio
async def test_fcm_acceptance_is_terminal_but_never_fabricates_phone_delivery(db_session):
    now = datetime.now(UTC)
    _, notification = await _target(db_session, now)
    notification.expires_at = now + timedelta(seconds=75)
    provider = FcmProvider()
    assert await dispatch_mobile_push_batch(db_session, provider=provider, limit=100, now=now) == 1
    await db_session.commit()
    delivery = (await db_session.scalars(select(MobilePushDeliveryModel))).one()
    assert delivery.status == "provider_accepted"
    assert delivery.provider_ticket_id and delivery.submitted_at
    assert delivery.delivered_at is None and delivery.receipt_attempts == 0
    assert notification.status == "sent"
    assert 0 < provider.calls[0][0].ttl_seconds <= 75
    assert (
        await reconcile_mobile_push_receipts(db_session, provider=provider, limit=100, now=now) == 0
    )
    assert await dispatch_mobile_push_batch(db_session, provider=provider, limit=100, now=now) == 0
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_ambiguous_fcm_outcome_is_saved_and_never_automatically_resent(db_session):
    now = datetime.now(UTC)
    _, notification = await _target(db_session, now)
    provider = FcmProvider(unknown=True)
    assert await dispatch_mobile_push_batch(db_session, provider=provider, limit=20, now=now) == 0
    await db_session.commit()
    delivery = (await db_session.scalars(select(MobilePushDeliveryModel))).one()
    assert delivery.status == "unknown" and delivery.failed_at is None
    assert notification.failure_code == "provider_outcome_unknown"
    assert (
        await dispatch_mobile_push_batch(
            db_session, provider=provider, limit=20, now=now + timedelta(hours=1)
        )
        == 0
    )
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_worker_interruption_keeps_committed_intent_and_recovers_as_unknown(db_session):
    now = datetime.now(UTC)
    await _target(db_session, now)
    provider = FcmProvider(interrupt=True)
    with pytest.raises(RuntimeError, match="worker interrupted"):
        await dispatch_mobile_push_batch(db_session, provider=provider, limit=20, now=now)
    await db_session.rollback()
    delivery = (await db_session.scalars(select(MobilePushDeliveryModel))).one()
    assert delivery.status == "submitting" and delivery.send_attempts == 1
    assert (
        await dispatch_mobile_push_batch(
            db_session, provider=provider, limit=20, now=now + timedelta(minutes=16)
        )
        == 0
    )
    await db_session.refresh(delivery)
    assert delivery.status == "unknown" and len(provider.calls) == 1


@pytest.mark.asyncio
async def test_failed_intent_commit_prevents_any_fcm_request(db_session, monkeypatch):
    now = datetime.now(UTC)
    await _target(db_session, now)
    provider = FcmProvider()
    monkeypatch.setattr(
        db_session, "commit", AsyncMock(side_effect=RuntimeError("database unavailable"))
    )
    with pytest.raises(RuntimeError, match="database unavailable"):
        await dispatch_mobile_push_batch(db_session, provider=provider, limit=20, now=now)
    assert provider.calls == []


@pytest.mark.asyncio
async def test_access_revocation_in_intent_commit_gap_prevents_send(db_session, monkeypatch):
    now = datetime.now(UTC)
    _, notification = await _target(db_session, now)
    original_commit = db_session.commit

    async def commit_then_withdraw():
        await original_commit()
        await db_session.execute(
            update(GCGroupAccessModel).values(is_enabled=False, revoked_at=now)
        )
        await original_commit()

    monkeypatch.setattr(db_session, "commit", commit_then_withdraw)
    provider = FcmProvider()
    assert await dispatch_mobile_push_batch(db_session, provider=provider, limit=20, now=now) == 0
    assert notification.status == "cancelled"
    delivery = (await db_session.scalars(select(MobilePushDeliveryModel))).one()
    assert delivery.status == "cancelled" and provider.calls == []


@pytest.mark.asyncio
async def test_explicit_quota_rejection_respects_provider_delay_before_retry(db_session):
    now = datetime.now(UTC)
    await _target(db_session, now)
    provider = FcmProvider(retry=True)
    await dispatch_mobile_push_batch(db_session, provider=provider, limit=20, now=now)
    await db_session.commit()
    delivery = (await db_session.scalars(select(MobilePushDeliveryModel))).one()
    assert delivery.status == "retry" and delivery.send_attempts == 1
    assert (
        await dispatch_mobile_push_batch(
            db_session, provider=provider, limit=20, now=now + timedelta(seconds=119)
        )
        == 0
    )
    provider.retry = False
    assert (
        await dispatch_mobile_push_batch(
            db_session, provider=provider, limit=20, now=now + timedelta(seconds=120)
        )
        == 1
    )
    assert len(provider.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [("platform", "ios"), ("environment", "production"), ("app_bundle_id", "other.package")],
)
async def test_fcm_does_not_send_to_wrong_native_platform_environment_or_package(
    db_session, field, value
):
    now = datetime.now(UTC)
    registration, _ = await _target(db_session, now)
    setattr(registration, field, value)
    await db_session.flush()
    provider = FcmProvider()
    assert await dispatch_mobile_push_batch(db_session, provider=provider, limit=20, now=now) == 0
    assert provider.calls == []


@pytest.mark.asyncio
async def test_multi_device_partial_acceptance_retries_only_the_explicit_rejection(db_session):
    now = datetime.now(UTC)
    accepted_registration, notification = await _target(db_session, now)
    retry_registration = await _additional_device(db_session, accepted_registration, now)
    uncertain_registration = await _additional_device(db_session, accepted_registration, now)

    class MixedProvider(FcmProvider):
        async def send(self, messages):
            tickets = await super().send(messages)
            if len(self.calls) > 1:
                return tickets
            outcomes = []
            for ticket in tickets:
                if ticket.registration_id == str(retry_registration.id):
                    ticket = replace(
                        ticket,
                        accepted=False,
                        provider_ticket_id=None,
                        retryable=True,
                        retry_after_seconds=120,
                        error_code="fcm_quota_exceeded",
                    )
                elif ticket.registration_id == str(uncertain_registration.id):
                    ticket = replace(
                        ticket,
                        accepted=False,
                        provider_ticket_id=None,
                        outcome_unknown=True,
                        error_code="provider_outcome_unknown",
                    )
                outcomes.append(ticket)
            return outcomes

    provider = MixedProvider()
    assert await dispatch_mobile_push_batch(db_session, provider=provider, limit=20, now=now) == 1
    await db_session.commit()
    rows = {
        row.registration_id: row
        for row in await db_session.scalars(select(MobilePushDeliveryModel))
    }
    assert notification.status == "sent"
    assert rows[accepted_registration.id].status == "provider_accepted"
    assert rows[retry_registration.id].status == "retry"
    assert rows[uncertain_registration.id].status == "unknown"
    assert all(row.delivered_at is None for row in rows.values())
    assert (
        await dispatch_mobile_push_batch(
            db_session, provider=provider, limit=20, now=now + timedelta(seconds=119)
        )
        == 0
    )
    assert len(provider.calls) == 1
    assert (
        await dispatch_mobile_push_batch(
            db_session, provider=provider, limit=20, now=now + timedelta(seconds=120)
        )
        == 1
    )
    await db_session.commit()
    assert [item.registration_id for item in provider.calls[1]] == [str(retry_registration.id)]
    assert rows[accepted_registration.id].send_attempts == 1
    assert rows[retry_registration.id].status == "provider_accepted"
    assert rows[retry_registration.id].send_attempts == 2
    assert rows[uncertain_registration.id].status == "unknown"
    assert rows[uncertain_registration.id].send_attempts == 1
    assert all(row.delivered_at is None for row in rows.values())
    assert (
        await dispatch_mobile_push_batch(
            db_session, provider=provider, limit=20, now=now + timedelta(hours=1)
        )
        == 0
    )
    assert len(provider.calls) == 2


@pytest.mark.asyncio
async def test_multi_device_batch_boundary_eventually_attempts_every_device_once(db_session):
    now = datetime.now(UTC)
    first, notification = await _target(db_session, now)
    second = await _additional_device(db_session, first, now)
    provider = FcmProvider()
    assert await dispatch_mobile_push_batch(db_session, provider=provider, limit=1, now=now) == 1
    await db_session.commit()
    assert (
        await dispatch_mobile_push_batch(
            db_session, provider=provider, limit=1, now=now + timedelta(seconds=1)
        )
        == 1
    )
    await db_session.commit()
    assert {item.registration_id for batch in provider.calls for item in batch} == {
        str(first.id),
        str(second.id),
    }
    assert [len(batch) for batch in provider.calls] == [1, 1]
    deliveries = list(await db_session.scalars(select(MobilePushDeliveryModel)))
    assert len(deliveries) == 2
    assert all(row.status == "provider_accepted" and row.send_attempts == 1 for row in deliveries)
    assert all(row.delivered_at is None for row in deliveries)
    assert notification.status == "sent"
    assert (
        await dispatch_mobile_push_batch(
            db_session, provider=provider, limit=1, now=now + timedelta(hours=1)
        )
        == 0
    )
    assert len(provider.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("device_unavailable", ["revoked_registration", "expired_session"])
async def test_unavailable_device_retry_cannot_keep_an_accepted_parent_due_forever(
    db_session, device_unavailable
):
    now = datetime.now(UTC)
    first, notification = await _target(db_session, now)
    await _additional_device(db_session, first, now)
    provider = FcmProvider()
    # The second device receives a durable, definitely-unsent retry target when
    # this first wave accepts just one device.
    assert await dispatch_mobile_push_batch(db_session, provider=provider, limit=1, now=now) == 1
    await db_session.commit()
    retry = (
        await db_session.scalars(
            select(MobilePushDeliveryModel).where(MobilePushDeliveryModel.status == "retry")
        )
    ).one()
    registration = await db_session.get(MobilePushRegistrationModel, retry.registration_id)
    if device_unavailable == "revoked_registration":
        registration.status = "revoked"
        registration.notifications_authorized = False
        registration.revoked_at = now
    else:
        device = await db_session.get(MobileDeviceSessionModel, registration.session_id)
        device.expires_at = now + timedelta(seconds=1)
    await db_session.commit()
    assert (
        await dispatch_mobile_push_batch(
            db_session, provider=provider, limit=1, now=now + timedelta(seconds=2)
        )
        == 0
    )
    await db_session.commit()
    await db_session.refresh(retry)
    assert retry.status == "cancelled"
    assert retry.send_attempts == 0 and retry.provider_ticket_id is None
    assert notification.status == "sent"
    assert len(provider.calls) == 1
