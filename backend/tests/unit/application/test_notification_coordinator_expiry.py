"""Current trip authority must still hold when a queued staff push is dispatched."""

import uuid
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.application.mobile import fcm_dispatch_intents
from app.application.mobile.authored_notification_audience import collect_notification_audience
from app.application.mobile.notification_service import (
    dispatch_mobile_push_batch,
    enqueue_personal_document_change_notifications,
)
from app.core.security.mobile_push_crypto import mobile_push_fernet
from app.infrastructure.database.gc_mobile_models import (
    ClientManagerGroupAssignmentModel,
    ClientManagerProfileModel,
    MobileDeviceSessionModel,
    MobileNotificationModel,
    MobilePushDeliveryModel,
    MobilePushRegistrationModel,
)
from app.infrastructure.database.models import CoordinatorGroupAssignmentModel, UserModel
from tests.unit.application.test_fcm_dispatch_intents import FcmProvider
from tests.unit.application.test_mobile_notification_service import (
    _access,
    _group,
    _persist_notification_records,
)


async def _staff_document_target(session, *, timezone_name, elapsed, role="coordinator"):
    zone = ZoneInfo(timezone_name)
    # Keep the controlled decision time ahead of the real handoff clock, without
    # sleeping or replacing the dispatcher's actual expiry/recheck functions.
    midnight_date = (datetime.now(UTC) + timedelta(days=3)).astimezone(zone).date()
    midnight = datetime.combine(midnight_date, time.min, tzinfo=zone)
    current = (midnight + timedelta(minutes=1 if elapsed else -1)).astimezone(UTC)
    access = _access()
    access.passenger_access_enabled = False
    access.coordinator_access_enabled = role == "coordinator"
    access.client_manager_access_enabled = role == "client_manager"
    group = _group(access, travel_date=midnight_date - timedelta(days=4))
    group.return_date = midnight_date - timedelta(days=1)
    group.timezone = timezone_name
    user = UserModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        full_name="Synthetic staff recipient",
        email=f"{uuid.uuid4()}@example.test",
        hashed_password="synthetic-no-login",
        role="agency_coordinator" if role == "coordinator" else role,
        is_active=True,
    )
    if role == "coordinator":
        assignment = CoordinatorGroupAssignmentModel(
            id=uuid.uuid4(),
            agency_id=access.agency_id,
            coordinator_user_id=user.id,
            group_id=group.id,
            active=True,
        )
        other_records = []
    else:
        profile = ClientManagerProfileModel(
            id=uuid.uuid4(),
            agency_id=access.agency_id,
            organization_id=access.client_organization_id,
            user_id=user.id,
            normalized_phone_number="+919876543219",
            status="active",
            activated_at=current,
        )
        assignment = ClientManagerGroupAssignmentModel(
            id=uuid.uuid4(),
            agency_id=access.agency_id,
            organization_id=access.client_organization_id,
            profile_id=profile.id,
            group_id=group.id,
            gc_group_access_id=access.id,
            is_active=True,
        )
        other_records = [profile]
    device = MobileDeviceSessionModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        subject_role=role,
        user_id=user.id,
        account_id=user.id,
        selected_gc_group_access_id=access.id,
        selected_group_id=group.id,
        device_identifier_hash=uuid.uuid4().hex * 2,
        platform="android",
        app_version="synthetic",
        status="active",
        expires_at=current + timedelta(days=1),
    )
    registration = MobilePushRegistrationModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        session_id=device.id,
        provider="fcm",
        platform="android",
        environment="development",
        app_bundle_id="com.globalconnects.groupcompanion",
        token_ciphertext=mobile_push_fernet().encrypt(b"synthetic-staff-fcm-token"),
        token_lookup_hash=uuid.uuid4().hex * 2,
        token_key_version=1,
        status="active",
        notifications_authorized=True,
    )
    await _persist_notification_records(
        session, [group, access, user, *other_records, assignment, device, registration]
    )
    counts = await enqueue_personal_document_change_notifications(
        session,
        access=access,
        passenger_identity_ids=[],
        operation="upsert",
        dedupe_token=f"synthetic-staff-document:{uuid.uuid4()}",
        now=current - timedelta(minutes=2),
    )
    assert counts.total == 1
    notification = (await session.scalars(select(MobileNotificationModel))).one()
    assert notification.recipient_user_id == user.id
    assert notification.recipient_type == role and notification.status == "queued"
    await session.commit()
    return current, user, group, assignment, device, notification


@pytest.mark.parametrize("timezone_name", ["Asia/Kolkata", "America/Los_Angeles"])
@pytest.mark.parametrize("elapsed", [False, True])
async def test_queued_coordinator_push_obeys_trip_local_expiry(db_session, timezone_name, elapsed):
    current, user, group, _, _, notification = await _staff_document_target(
        db_session, timezone_name=timezone_name, elapsed=elapsed
    )
    audience = await collect_notification_audience(
        db_session, agency_id=user.agency_id, group_ids=[group.id], now=current
    )
    assert any(grant.principal_id == user.id for grant in audience.grants) is not elapsed
    provider = FcmProvider()
    submitted = await dispatch_mobile_push_batch(
        db_session, provider=provider, limit=20, now=current
    )
    assert submitted == (0 if elapsed else 1)
    assert sum(map(len, provider.calls)) == (0 if elapsed else 1)
    if elapsed:
        assert notification.status == "cancelled"
        assert notification.failure_code == "recipient_access_revoked"
    else:
        assert provider.calls[0][0].body is None


@pytest.mark.parametrize("revocation", ["assignment", "user", "device"])
async def test_queued_current_trip_keeps_existing_live_authority_revocation_guards(
    db_session, revocation
):
    current, _, _, assignment, device, _ = await _staff_document_target(
        db_session, timezone_name="Asia/Kolkata", elapsed=False
    )
    if revocation == "assignment":
        assignment.active = False
        assignment.unassigned_at = current
    elif revocation == "user":
        user = await db_session.get(UserModel, device.user_id)
        user.is_active = False
    else:
        device.status = "revoked"
        device.revoked_at = current
    await db_session.commit()
    provider = FcmProvider()
    assert (
        await dispatch_mobile_push_batch(db_session, provider=provider, limit=20, now=current) == 0
    )
    assert provider.calls == []


async def test_ended_trip_keeps_client_manager_document_refresh_authority(db_session):
    current, user, group, _, _, _ = await _staff_document_target(
        db_session, timezone_name="Asia/Kolkata", elapsed=True, role="client_manager"
    )
    audience = await collect_notification_audience(
        db_session, agency_id=user.agency_id, group_ids=[group.id], now=current
    )
    assert any(grant.principal_id == user.id for grant in audience.grants)
    provider = FcmProvider()
    assert (
        await dispatch_mobile_push_batch(db_session, provider=provider, limit=20, now=current) == 1
    )
    assert sum(map(len, provider.calls)) == 1


async def test_coordinator_expiry_in_durable_intent_commit_gap_prevents_provider_handoff(
    db_session, monkeypatch
):
    current, user, group, _, _, notification = await _staff_document_target(
        db_session, timezone_name="Asia/Kolkata", elapsed=False
    )
    after_midnight = current + timedelta(minutes=2)
    audience = await collect_notification_audience(
        db_session, agency_id=user.agency_id, group_ids=[group.id], now=after_midnight
    )
    assert not any(grant.principal_id == user.id for grant in audience.grants)

    class HandoffClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return after_midnight if tz is not None else after_midnight.replace(tzinfo=None)

    # The real sender reads this wall clock after the durable intent commit.
    # Initial parent claiming and authority checks still use the pre-expiry time.
    monkeypatch.setattr(fcm_dispatch_intents, "datetime", HandoffClock)
    provider = FcmProvider()
    assert (
        await dispatch_mobile_push_batch(db_session, provider=provider, limit=20, now=current) == 0
    )
    assert provider.calls == [] and notification.status == "cancelled"
    delivery = (await db_session.scalars(select(MobilePushDeliveryModel))).one()
    assert delivery.send_attempts == 1 and delivery.status == "cancelled"
