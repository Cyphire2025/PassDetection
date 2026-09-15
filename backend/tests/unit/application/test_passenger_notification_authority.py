"""Stale roster contacts and claim grants cannot receive background pushes."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.application.mobile.notification_service import (
    dispatch_mobile_push_batch,
    enqueue_announcement_notifications,
    enqueue_personal_document_change_notifications,
    schedule_trip_countdown_notifications,
)
from app.application.mobile.passenger_notification_authority import (
    authoritative_passenger_device_ids,
)
from app.infrastructure.database.gc_mobile_models import (
    GCAnnouncementModel,
    GCGroupAccessModel,
    MobileDeviceSessionModel,
    MobileNotificationModel,
    MobilePassengerIdentityModel,
    MobilePassengerSessionIdentityModel,
)
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from tests.unit.application.test_fcm_dispatch_intents import FcmProvider, _target
from tests.unit.application.test_mobile_notification_service import (
    _access,
    _announcement,
    _submission,
)


async def _change_authority(session, reason):
    submission = (await session.scalars(select(PassportSubmissionModel))).one()
    if reason == "phone_changed":
        submission.client_phone = "+919876543211"
    elif reason == "unreviewed":
        submission.client_reviewed_at = None
    elif reason == "imported":
        submission.confidence_score = {"source": "excel_import"}
    elif reason == "removed":
        await session.delete(submission)
    elif reason == "wrong_group":
        identity = (await session.scalars(select(MobilePassengerIdentityModel))).one()
        identity.group_id = uuid.uuid4()
    elif reason == "wrong_agency":
        identity = (await session.scalars(select(MobilePassengerIdentityModel))).one()
        identity.agency_id = uuid.uuid4()
    await session.flush()


@pytest.mark.parametrize(
    "reason", ["phone_changed", "unreviewed", "imported", "removed", "wrong_group", "wrong_agency"]
)
async def test_dispatch_cancels_obsolete_passenger_authority_without_provider_calls(
    db_session, reason
):
    now = datetime.now(UTC)
    _, notification = await _target(db_session, now)
    await _change_authority(db_session, reason)
    provider = FcmProvider()
    assert await dispatch_mobile_push_batch(db_session, provider=provider, limit=20, now=now) == 0
    assert provider.calls == [] and notification.status == "cancelled"


@pytest.mark.parametrize("reason", ["phone_changed", "unreviewed", "imported"])
async def test_all_passenger_producers_reject_stale_identity_before_adding_notifications(
    db_session, reason
):
    now = datetime.now(UTC)
    _, notification = await _target(db_session, now)
    identity_id = notification.recipient_passenger_identity_id
    await db_session.delete(notification)
    await _change_authority(db_session, reason)
    access = (await db_session.scalars(select(GCGroupAccessModel))).one()
    announcement = (await db_session.scalars(select(GCAnnouncementModel))).one()
    counts = await enqueue_announcement_notifications(
        db_session, access=access, announcement=announcement
    )
    documents = await enqueue_personal_document_change_notifications(
        db_session,
        access=access,
        passenger_identity_ids=[identity_id],
        operation="upsert",
        dedupe_token="synthetic:test",
    )
    group = (await db_session.scalars(select(ClientGroupModel))).one()
    group.travel_date = now.date() + timedelta(days=3)
    countdowns = await schedule_trip_countdown_notifications(
        db_session,
        timezone_name="UTC",
        send_hour=23,
        now=now,
    )
    assert counts.total == documents.total == countdowns.inserted == 0
    assert list(await db_session.scalars(select(MobileNotificationModel))) == []


@pytest.mark.parametrize("binding_change", ["missing", "stale_generation"])
async def test_current_contact_requires_the_device_exact_stored_claim_generation(
    db_session, binding_change
):
    now = datetime.now(UTC)
    _, notification = await _target(db_session, now)
    binding = (await db_session.scalars(select(MobilePassengerSessionIdentityModel))).one()
    if binding_change == "missing":
        await db_session.delete(binding)
    else:
        binding.identity_claim_generation += 1
    await db_session.flush()
    devices = list(await db_session.scalars(select(MobileDeviceSessionModel)))
    assert await authoritative_passenger_device_ids(db_session, devices) == set()
    provider = FcmProvider()
    assert await dispatch_mobile_push_batch(db_session, provider=provider, limit=20, now=now) == 0
    assert provider.calls == [] and notification.sent_at is None


async def test_fcm_commit_gap_rechecks_contact_before_any_provider_send(db_session, monkeypatch):
    now = datetime.now(UTC)
    _, notification = await _target(db_session, now)
    original_commit = db_session.commit
    changed = False

    async def commit_then_change_contact():
        nonlocal changed
        await original_commit()
        if not changed:
            changed = True
            await _change_authority(db_session, "phone_changed")
            await original_commit()

    monkeypatch.setattr(db_session, "commit", commit_then_change_contact)
    provider = FcmProvider()
    assert await dispatch_mobile_push_batch(db_session, provider=provider, limit=20, now=now) == 0
    assert changed and provider.calls == [] and notification.status == "cancelled"


async def test_recipient_pagination_continues_past_a_page_with_no_authoritative_contacts(
    db_session, monkeypatch
):
    monkeypatch.setattr("app.application.mobile.notification_service._RECIPIENT_PAGE_SIZE", 2)
    access = _access()
    access.client_manager_access_enabled = access.coordinator_access_enabled = False
    announcement = _announcement(access)
    identities = [
        MobilePassengerIdentityModel(
            id=uuid.UUID(f"aaaaaaaa-0000-0000-0000-{index + 1:012x}"),
            agency_id=access.agency_id,
            group_id=access.group_id,
            gc_group_access_id=access.id,
            passenger_submission_id=uuid.uuid4(),
            normalized_phone_number=f"+91987654321{index}",
            phone_lookup_hash=uuid.uuid4().hex * 2,
            status="eligible",
        )
        for index in range(3)
    ]
    submissions = [_submission(identity) for identity in identities]
    for submission in submissions[:2]:
        submission.client_reviewed_at = None
    db_session.add_all([access, announcement, *identities, *submissions])
    await db_session.flush()
    counts = await enqueue_announcement_notifications(
        db_session, access=access, announcement=announcement
    )
    notifications = list(await db_session.scalars(select(MobileNotificationModel)))
    assert counts.passengers == 1
    assert [item.recipient_passenger_identity_id for item in notifications] == [identities[-1].id]
