"""Device rotation and recovery exercise the real dispatcher with fake providers."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.application.mobile.notification_service import dispatch_mobile_push_batch
from app.core.security.mobile_push_crypto import mobile_push_fernet
from app.infrastructure.database.gc_mobile_models import (
    MobileDeviceSessionModel,
    MobilePushDeliveryModel,
    MobilePushRegistrationModel,
)
from tests.authored_notification_fixtures import authored_audience, reviewed_draft
from tests.unit.application.test_authored_notifications import _send
from tests.unit.application.test_fcm_dispatch_intents import FcmProvider, _additional_device

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("first_outcome", ["accepted", "unknown", "retry"])
async def test_rotated_registration_does_not_repeat_accepted_or_uncertain_physical_device_attempt(
    db_session, first_outcome
):
    actor, accesses, _, _, registration = await authored_audience(db_session)
    now = datetime.now(UTC)
    registration.token_ciphertext = mobile_push_fernet().encrypt(b"synthetic-native-token")
    await _additional_device(db_session, registration, now)
    draft, _, request = await reviewed_draft(db_session, actor, group_ids=[accesses[0].group_id])
    await _send(db_session, actor, draft, request)
    await db_session.commit()
    first = FcmProvider(unknown=first_outcome == "unknown", retry=first_outcome == "retry")
    await dispatch_mobile_push_batch(
        db_session, provider=first, limit=1, now=now + timedelta(seconds=1)
    )
    await db_session.commit()
    assert sum(map(len, first.calls)) == 1
    old_id = uuid.UUID(first.calls[0][0].registration_id)
    old = await db_session.get(MobilePushRegistrationModel, old_id)
    old_device = await db_session.get(MobileDeviceSessionModel, old.session_id)
    rotated = await _additional_device(db_session, old, now + timedelta(seconds=2))
    rotated_device = await db_session.get(MobileDeviceSessionModel, rotated.session_id)
    old.status, old.revoked_at = "revoked", now + timedelta(seconds=2)
    old_device.status, old_device.revoked_at = "revoked", now + timedelta(seconds=2)
    await db_session.flush()
    rotated_device.device_identifier_hash = old_device.device_identifier_hash
    await db_session.commit()
    remaining = FcmProvider()
    await dispatch_mobile_push_batch(
        db_session, provider=remaining, limit=20, now=now + timedelta(minutes=3)
    )
    await db_session.commit()
    retried_ids = {
        uuid.UUID(message.registration_id) for wave in remaining.calls for message in wave
    }
    if first_outcome == "retry":
        assert rotated.id in retried_ids
    else:
        assert rotated.id not in retried_ids
        assert len(retried_ids) == 1  # sibling still receives its first automatic attempt
        assert (
            await db_session.scalar(
                select(func.count())
                .select_from(MobilePushDeliveryModel)
                .where(MobilePushDeliveryModel.registration_id == rotated.id)
            )
            == 0
        )


async def test_definitive_preview_rejection_never_hides_prior_committed_request(db_session):
    actor, _, _, _, _ = await authored_audience(db_session, device=False)
    draft, _, request = await reviewed_draft(db_session, actor)
    invalid = request.model_copy(update={"preview_token": "corrupted.token"})
    with pytest.raises(HTTPException) as before:
        await _send(db_session, actor, draft, invalid)
    assert before.value.detail == "stale_preview"
    await _send(db_session, actor, draft, request)
    await db_session.commit()
    with pytest.raises(HTTPException) as after:
        await _send(db_session, actor, draft, invalid)
    assert after.value.detail == "idempotency_conflict"
