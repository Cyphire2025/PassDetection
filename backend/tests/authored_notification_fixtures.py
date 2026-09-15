"""Synthetic multi-trip, same-contact alert recipients without provider traffic."""

import uuid
from datetime import UTC, datetime

from app.application.mobile.authored_notification_service import (
    preview_notification,
    save_notification_draft,
)
from app.core.security.mobile_jwt import MobileAccessClaims
from app.infrastructure.database.gc_mobile_models import (
    GCGroupAccessModel,
    MobilePushRegistrationModel,
)
from app.infrastructure.database.models import ClientGroupModel
from app.presentation.api.v1.schemas.gc_notification_schemas import (
    NotificationDraftInput,
    NotificationSendRequest,
)
from tests.gc_app_workflow_fixtures import workflow_group, workflow_passenger, workflow_session


async def authored_audience(session, *, device=True):
    actor, group, access = await workflow_group(session)
    second_group = ClientGroupModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        name="Second trip",
        token=uuid.uuid4().hex,
        status="active",
    )
    session.add(second_group)
    await session.flush()
    second_access = GCGroupAccessModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        group_id=second_group.id,
        is_enabled=True,
        passenger_access_enabled=True,
    )
    session.add(second_access)
    await session.flush()
    submission, identity = await workflow_passenger(session, access)
    other_submission, other_identity = await workflow_passenger(session, second_access)
    other_person, _ = await workflow_passenger(session, second_access, phone="+919876543211")
    claims = registration = None
    if device:
        current_device, _ = await workflow_session(session, [identity, other_identity])
        registration = MobilePushRegistrationModel(
            id=uuid.uuid4(),
            agency_id=access.agency_id,
            session_id=current_device.id,
            provider="fcm",
            platform="android",
            environment="development",
            app_bundle_id="com.globalconnects.groupcompanion",
            token_ciphertext=b"synthetic-encrypted-token",
            token_lookup_hash=uuid.uuid4().hex * 2,
            token_key_version=1,
            status="active",
            notifications_authorized=True,
        )
        session.add(registration)
        claims = MobileAccessClaims(
            principal_id=identity.id,
            account_id=identity.id,
            principal_type="passenger",
            agency_id=access.agency_id,
            session_id=current_device.id,
            session_generation=current_device.session_generation,
            password_change_required=False,
            expires_at=current_device.expires_at,
        )
    await session.commit()
    return (
        actor,
        [access, second_access],
        [submission, other_submission, other_person],
        claims,
        registration,
    )


async def reviewed_draft(session, actor, *, group_ids=None, now=None):
    current = now or datetime.now(UTC)
    body = NotificationDraftInput(
        title="Meet at reception",
        body="Please arrive at 09:00.",
        audience="selected_groups" if group_ids else "all_active_trips",
        group_ids=group_ids or [],
    )
    draft = await save_notification_draft(
        session, agency_id=actor.agency_id, actor_id=actor.id, body=body, now=current
    )
    preview = await preview_notification(
        session,
        agency_id=actor.agency_id,
        actor_id=actor.id,
        draft_id=draft.id,
        revision=draft.revision,
        now=current,
    )
    request = NotificationSendRequest(
        expected_revision=draft.revision,
        preview_token=preview.preview_token,
        request_id=uuid.uuid4(),
    )
    return draft, preview, request
