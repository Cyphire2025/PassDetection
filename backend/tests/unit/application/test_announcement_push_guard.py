"""A stale queue never authorizes sending withdrawn announcement content."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.announcement_push_guard import (
    retain_dispatchable_announcement_notifications,
)
from app.application.mobile.notification_service import dispatch_mobile_push_batch
from app.application.mobile.push_provider import (
    MobilePushMessage,
    MobilePushReceipt,
    MobilePushTicket,
)
from app.infrastructure.database.gc_mobile_models import (
    GCAnnouncementModel,
    MobileNotificationModel,
    MobilePushDeliveryModel,
)
from tests.unit.application.test_mobile_notification_service import _persist_push_target


class RecordingProvider:
    name = "expo"
    enabled = True

    def __init__(self) -> None:
        self.calls = 0
        self.messages: list[MobilePushMessage] = []

    async def send(self, messages: list[MobilePushMessage]) -> list[MobilePushTicket]:
        self.calls += 1
        self.messages.extend(messages)
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

    async def get_receipts(self, provider_ticket_ids: list[str]) -> list[MobilePushReceipt]:
        raise AssertionError("Dispatch must not poll receipts")


@pytest.mark.parametrize("read_already", [False, True])
async def test_current_published_announcement_is_in_app_only_even_after_read(db_session, read_already):
    now = datetime.now(UTC)
    _, notification = await _persist_push_target(db_session, now=now, notification_type="group_announcement")
    if read_already:
        notification.read_at = now
    provider = RecordingProvider()
    assert await _legacy_guard_then_dispatch(db_session, provider=provider, limit=100, now=now) == 0
    assert await _legacy_guard_then_dispatch(db_session, provider=provider, limit=100, now=now) == 0
    assert provider.calls == 0
    assert await db_session.scalar(select(MobilePushDeliveryModel)) is None
    assert notification.status == "queued"  # Durable in-app state is preserved.


@pytest.mark.parametrize("source_state", ["revoked", "retired", "draft", "missing"])
async def test_nonpublished_or_missing_announcement_cancels_without_provider_call(
    db_session,
    source_state,
):
    now = datetime.now(UTC)
    _, notification = await _persist_push_target(db_session, now=now, notification_type="group_announcement")
    source = await db_session.scalar(select(GCAnnouncementModel))
    if source_state == "missing":
        await db_session.delete(source)
    else:
        source.status = source_state
        if source_state == "draft":
            source.published_at = None
        elif source_state == "revoked":
            source.revoked_at = now
        else:
            source.retired_at = now
    notification.read_at = now  # Reading a feed item does not establish push eligibility.
    await db_session.flush()
    provider = RecordingProvider()
    assert await _legacy_guard_then_dispatch(db_session, provider=provider, limit=100, now=now) == 0
    assert provider.calls == 0
    assert notification.status == "cancelled"
    assert notification.failure_code == "announcement_unpublished"
    assert (await db_session.scalars(select(MobilePushDeliveryModel))).all() == []


@pytest.mark.parametrize("scope_field", ["agency_id", "group_id", "gc_group_access_id"])
async def test_a_published_source_from_a_different_scope_cannot_authorize_push(
    db_session, scope_field
):
    now = datetime.now(UTC)
    _, notification = await _persist_push_target(db_session, now=now, notification_type="group_announcement")
    source = await db_session.scalar(select(GCAnnouncementModel))
    # Isolated SQLite permits a deliberately corrupted historical scope. The
    # PostgreSQL tests separately exercise real constraints and row locks.
    setattr(source, scope_field, uuid.uuid4())
    await db_session.flush()
    provider = RecordingProvider()
    assert await _legacy_guard_then_dispatch(db_session, provider=provider, limit=100, now=now) == 0
    assert provider.calls == 0
    assert notification.status == "cancelled"


@pytest.mark.parametrize("payload_problem", ["event", "trip", "route", "dedupe", "malformed_event"])
async def test_announcement_source_and_public_deep_link_must_agree(db_session, payload_problem):
    now = datetime.now(UTC)
    _, notification = await _persist_push_target(db_session, now=now, notification_type="group_announcement")
    if payload_problem == "dedupe":
        notification.dedupe_key = f"announcement:{uuid.uuid4()}"
    else:
        key, value = {
            "event": ("event_id", str(uuid.uuid4())),
            "trip": ("trip_id", str(uuid.uuid4())),
            "route": ("route", "documents"),
            "malformed_event": ("event_id", "not-a-uuid"),
        }[payload_problem]
        notification.public_payload = {**notification.public_payload, key: value}
    provider = RecordingProvider()
    assert await _legacy_guard_then_dispatch(db_session, provider=provider, limit=100, now=now) == 0
    assert provider.calls == 0
    assert notification.status == "cancelled"
    assert notification.failure_code == "invalid_public_payload"


@pytest.mark.parametrize("source_change", ["hidden", "expired", "retired_at", "revoked_at"])
async def test_current_source_visibility_and_window_are_rechecked(db_session, source_change):
    now = datetime.now(UTC)
    _, notification = await _persist_push_target(db_session, now=now, notification_type="group_announcement")
    source = await db_session.scalar(select(GCAnnouncementModel))
    if source_change == "hidden":
        source.passenger_visible = False
    elif source_change == "expired":
        source.availability_expires_at = now
    else:
        setattr(source, source_change, now)
    provider = RecordingProvider()
    assert await _legacy_guard_then_dispatch(db_session, provider=provider, limit=100, now=now) == 0
    assert provider.calls == 0
    assert notification.status == "cancelled"


async def test_future_source_is_deferred_then_remains_in_app_only(db_session):
    now = datetime.now(UTC)
    _, notification = await _persist_push_target(db_session, now=now, notification_type="group_announcement")
    source = await db_session.scalar(select(GCAnnouncementModel))
    future = now + timedelta(hours=1)
    source.availability_starts_at = future
    provider = RecordingProvider()
    assert await _legacy_guard_then_dispatch(db_session, provider=provider, limit=100, now=now) == 0
    assert provider.calls == 0
    assert notification.status == "queued"
    assert notification.available_at == future
    assert (
        await _legacy_guard_then_dispatch(db_session, provider=provider, limit=100, now=future) == 0
    )


async def test_moved_source_window_cannot_violate_notification_expiry(db_session):
    now = datetime.now(UTC)
    _, notification = await _persist_push_target(db_session, now=now, notification_type="group_announcement")
    source = await db_session.scalar(select(GCAnnouncementModel))
    notification.expires_at = now + timedelta(minutes=30)
    source.availability_starts_at = now + timedelta(hours=1)
    provider = RecordingProvider()
    assert await _legacy_guard_then_dispatch(db_session, provider=provider, limit=100, now=now) == 0
    assert provider.calls == 0
    assert notification.status == "cancelled"
    await db_session.flush()


@pytest.mark.parametrize("delivery_status", ["retry", "submitting", "receipt_pending", "delivered"])
async def test_withdrawal_cancels_unsent_attempts_and_preserves_provider_evidence(
    db_session: AsyncSession,
    delivery_status: str,
) -> None:
    now = datetime.now(UTC)
    registration, notification = await _persist_push_target(db_session, now=now, notification_type="group_announcement")
    source = await db_session.scalar(select(GCAnnouncementModel))
    source.status = "retired"
    source.retired_at = now
    accepted = delivery_status in {"receipt_pending", "delivered"}
    delivery = MobilePushDeliveryModel(
        id=uuid.uuid4(),
        agency_id=notification.agency_id,
        notification_id=notification.id,
        registration_id=registration.id,
        provider="expo",
        status=delivery_status,
        provider_ticket_id="accepted-ticket" if accepted else None,
        send_attempts=1,
        receipt_attempts=0,
        next_attempt_at=now,
        submitted_at=now if accepted else None,
        delivered_at=now if delivery_status == "delivered" else None,
    )
    db_session.add(delivery)
    await db_session.flush()
    provider = RecordingProvider()
    assert await _legacy_guard_then_dispatch(db_session, provider=provider, limit=100, now=now) == 0
    assert provider.calls == 0
    assert notification.status == "cancelled"
    await db_session.refresh(delivery)
    if accepted:
        assert delivery.status == delivery_status
        assert delivery.provider_ticket_id == "accepted-ticket"
    else:
        assert delivery.status == "cancelled"
        assert delivery.last_error_code == "announcement_unpublished"


async def test_other_notification_types_do_not_require_an_announcement_source(db_session):
    now = datetime.now(UTC)
    _, notification = await _persist_push_target(db_session, now=now, notification_type="group_announcement")
    source = await db_session.scalar(select(GCAnnouncementModel))
    await db_session.delete(source)
    notification.notification_type = "trip_countdown"
    notification.dedupe_key = f"countdown:{notification.group_id}:1"
    notification.public_payload = {"route": "trip", "trip_id": str(notification.group_id)}
    provider = RecordingProvider()
    assert await _legacy_guard_then_dispatch(db_session, provider=provider, limit=100, now=now) == 1
    assert provider.calls == 1


async def _legacy_guard_then_dispatch(session, *, provider, limit, now):
    """Retain source-guard regressions; the dispatcher independently forbids announcement push."""
    notifications = list(await session.scalars(select(MobileNotificationModel)))
    await retain_dispatchable_announcement_notifications(session, notifications=notifications, now=now)
    return await dispatch_mobile_push_batch(session, provider=provider, limit=limit, now=now)
