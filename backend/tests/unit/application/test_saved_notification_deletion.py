"""Saved removal keeps immutable sends, recipient access and delivery evidence."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.application.mobile.authored_notification_access import (
    retain_authorized_authored_notifications,
)
from app.application.mobile.authored_notification_history import batch_responses
from app.application.mobile.authored_notification_service import (
    delete_notification_draft,
    preview_notification,
    require_draft,
    save_notification_draft,
    send_notification,
)
from app.application.mobile.notification_service import dispatch_mobile_push_batch
from app.core.security.mobile_push_crypto import mobile_push_fernet
from app.infrastructure.database.gc_mobile_models import (
    MobileNotificationModel,
    MobilePushDeliveryModel,
)
from app.infrastructure.database.gc_notification_models import (
    GCNotificationBatchModel,
    GCNotificationDraftModel,
    GCNotificationRecipientGrantModel,
    GCNotificationRecipientModel,
)
from app.presentation.api.v1.schemas.gc_notification_schemas import NotificationDraftUpdate
from tests.authored_notification_fixtures import authored_audience, reviewed_draft
from tests.unit.application.test_fcm_dispatch_intents import FcmProvider

pytestmark = pytest.mark.asyncio


async def test_delete_retains_history_outbox_grants_and_committed_request_recovery(db_session):
    actor, _, _, _, _ = await authored_audience(db_session)
    draft, _, request = await reviewed_draft(db_session, actor)
    scope = {"agency_id": actor.agency_id, "actor_id": actor.id, "draft_id": draft.id}
    batch = await send_notification(db_session, **scope, body=request)
    await db_session.commit()
    models = (
        GCNotificationDraftModel,
        GCNotificationBatchModel,
        GCNotificationRecipientModel,
        GCNotificationRecipientGrantModel,
        MobileNotificationModel,
    )
    before = [await db_session.scalar(select(func.count()).select_from(model)) for model in models]
    await delete_notification_draft(db_session, **scope, expected_revision=1)
    await db_session.commit()
    assert draft.deleted_at is not None and draft.deleted_by_user_id == actor.id
    assert draft.revision == 2
    after = [await db_session.scalar(select(func.count()).select_from(model)) for model in models]
    assert before == after == [1, 1, 2, 3, 2]
    notifications = list(await db_session.scalars(select(MobileNotificationModel)))
    assert all(row.status == "queued" for row in notifications)
    assert (
        len(
            await retain_authorized_authored_notifications(
                db_session, notifications=notifications, now=datetime.now(UTC)
            )
        )
        == 2
    )
    history = (await batch_responses(db_session, [batch]))[0]
    assert history.title == "Meet at reception" and history.recipient_counts.queued == 2
    recovered = await send_notification(
        db_session, **scope, body=request, now=datetime.now(UTC) + timedelta(hours=1)
    )
    assert recovered.id == batch.id
    await delete_notification_draft(db_session, **scope, expected_revision=1)
    assert draft.revision == 2
    for operation in (
        require_draft(db_session, agency_id=actor.agency_id, draft_id=draft.id),
        preview_notification(db_session, **scope, revision=2),
        save_notification_draft(
            db_session,
            **scope,
            body=NotificationDraftUpdate(
                title="Changed", body="Changed", audience="all_active_trips", expected_revision=2
            ),
        ),
        send_notification(
            db_session, **scope, body=request.model_copy(update={"request_id": uuid.uuid4()})
        ),
    ):
        with pytest.raises(HTTPException) as failure:
            await operation
        assert failure.value.status_code == 404
    assert await db_session.scalar(select(func.count()).select_from(GCNotificationBatchModel)) == 1


async def test_delete_stale_revision_preserves_saved_content(db_session):
    actor, _, _, _, _ = await authored_audience(db_session, device=False)
    draft, _, _ = await reviewed_draft(db_session, actor)
    scope = {"agency_id": actor.agency_id, "actor_id": actor.id, "draft_id": draft.id}
    await save_notification_draft(
        db_session,
        **scope,
        body=NotificationDraftUpdate(
            title="New content", body="Changed", audience="all_active_trips", expected_revision=1
        ),
    )
    with pytest.raises(HTTPException) as failure:
        await delete_notification_draft(db_session, **scope, expected_revision=1)
    assert failure.value.status_code == 409 and failure.value.detail == "draft_conflict"
    assert draft.title == "New content" and draft.deleted_at is None
    await delete_notification_draft(db_session, **scope, expected_revision=2)
    with pytest.raises(HTTPException) as stale_retry:
        await delete_notification_draft(db_session, **scope, expected_revision=1)
    assert stale_retry.value.status_code == 409


async def test_saved_removal_does_not_cancel_an_already_queued_send(db_session):
    actor, _, _, _, registration = await authored_audience(db_session)
    registration.token_ciphertext = mobile_push_fernet().encrypt(b"synthetic-native-token")
    draft, _, request = await reviewed_draft(db_session, actor)
    scope = {"agency_id": actor.agency_id, "actor_id": actor.id, "draft_id": draft.id}
    batch = await send_notification(db_session, **scope, body=request)
    await db_session.commit()
    await delete_notification_draft(db_session, **scope, expected_revision=1)
    await db_session.commit()
    provider = FcmProvider()
    await dispatch_mobile_push_batch(
        db_session, provider=provider, limit=20, now=datetime.now(UTC) + timedelta(seconds=1)
    )
    await db_session.commit()
    assert sum(map(len, provider.calls)) == 1
    delivery = await db_session.scalar(select(MobilePushDeliveryModel))
    assert delivery.status == "provider_accepted" and delivery.provider_ticket_id
    history = (await batch_responses(db_session, [batch]))[0]
    assert history.device_delivery_counts.provider_accepted == 1
    assert history.recipient_counts.cancelled == 0
