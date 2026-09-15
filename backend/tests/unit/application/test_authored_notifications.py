"""Real SQLite transactions for review, explicit send and original-grant union."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select

from app.application.mobile.authored_notification_access import (
    load_authored_recipient_registrations,
    retain_authorized_authored_notifications,
)
from app.application.mobile.authored_notification_history import batch_responses
from app.application.mobile.authored_notification_service import (
    preview_notification,
    save_notification_draft,
    send_notification,
)
from app.infrastructure.database.gc_mobile_models import (
    MobileNotificationModel,
    MobilePassengerIdentityModel,
    MobilePushDeliveryModel,
)
from app.infrastructure.database.gc_notification_models import (
    GCNotificationBatchModel,
    GCNotificationRecipientGrantModel,
    GCNotificationRecipientModel,
)
from app.infrastructure.database.models import ClientGroupModel
from app.presentation.api.v1.routes.mobile_ops import (
    list_mobile_notifications,
    mark_mobile_notification_read,
)
from app.presentation.api.v1.schemas.gc_notification_schemas import NotificationDraftUpdate
from tests.authored_notification_fixtures import authored_audience, reviewed_draft

pytestmark = pytest.mark.asyncio


async def _send(session, actor, draft, request, **kwargs):
    return await send_notification(
        session,
        agency_id=actor.agency_id,
        actor_id=actor.id,
        draft_id=draft.id,
        body=request,
        **kwargs,
    )


async def test_review_counts_same_person_once_across_open_and_closed_trips_and_never_queues(
    db_session,
):
    actor, accesses, _, _, _ = await authored_audience(db_session)
    draft, preview, _ = await reviewed_draft(db_session, actor)
    assert preview.group_count == 2 and set(preview.group_ids) == {
        access.group_id for access in accesses
    }
    assert preview.recipient_count == 2 and preview.role_counts.passengers == 2
    assert preview.eligible_device_count == 1 and preview.no_active_registration_count == 1
    assert draft.status == "draft"
    assert await db_session.scalar(select(func.count()).select_from(MobileNotificationModel)) == 0
    assert await db_session.scalar(select(func.count()).select_from(GCNotificationBatchModel)) == 0


async def test_explicit_batch_is_idempotent_and_new_request_is_deliberate_resend(db_session):
    actor, _, _, _, _ = await authored_audience(db_session)
    draft, _, request = await reviewed_draft(db_session, actor)
    batch = await _send(db_session, actor, draft, request)
    await db_session.commit()
    assert (await _send(db_session, actor, draft, request)).id == batch.id
    assert (
        await db_session.scalar(select(func.count()).select_from(GCNotificationRecipientModel)) == 2
    )
    assert (
        await db_session.scalar(select(func.count()).select_from(GCNotificationRecipientGrantModel))
        == 3
    )
    assert await db_session.scalar(select(func.count()).select_from(MobileNotificationModel)) == 2
    assert await db_session.scalar(select(func.count()).select_from(MobilePushDeliveryModel)) == 0
    new_batch = await _send(
        db_session, actor, draft, request.model_copy(update={"request_id": uuid.uuid4()})
    )
    assert new_batch.id != batch.id
    assert await db_session.scalar(select(func.count()).select_from(MobileNotificationModel)) == 4
    projection = (await batch_responses(db_session, [batch]))[0]
    assert projection.recipient_counts.queued == 2 and projection.device_delivery_counts.total == 0


async def test_completed_request_recovers_after_preview_expiry_and_later_draft_edit(db_session):
    actor, _, _, _, _ = await authored_audience(db_session)
    draft, _, request = await reviewed_draft(db_session, actor)
    batch = await _send(db_session, actor, draft, request)
    await db_session.commit()
    await save_notification_draft(
        db_session,
        agency_id=actor.agency_id,
        actor_id=actor.id,
        draft_id=draft.id,
        body=NotificationDraftUpdate(
            title="Edited", body="New text", audience="all_active_trips", expected_revision=1
        ),
    )
    recovered = await _send(
        db_session, actor, draft, request, now=datetime.now(UTC) + timedelta(hours=1)
    )
    assert (
        recovered.id == batch.id
        and recovered.title == "Meet at reception"
        and recovered.draft_revision == 1
    )


@pytest.mark.parametrize("change", ["phone", "generation", "paused"])
async def test_audience_change_between_review_and_send_requires_fresh_review(db_session, change):
    actor, accesses, submissions, _, _ = await authored_audience(db_session)
    draft, _, request = await reviewed_draft(db_session, actor)
    if change == "phone":
        submissions[0].client_phone = "+919876543299"
    elif change == "generation":
        identity = await db_session.scalar(
            select(MobilePassengerIdentityModel).where(
                MobilePassengerIdentityModel.passenger_submission_id == submissions[0].id
            )
        )
        identity.claim_generation += 1
    else:
        accesses[0].is_enabled = False
    await db_session.flush()
    with pytest.raises(HTTPException) as error:
        await _send(db_session, actor, draft, request)
    assert error.value.detail == "audience_changed"
    assert await db_session.scalar(select(func.count()).select_from(MobileNotificationModel)) == 0


async def test_one_revoked_trip_preserves_other_original_grant_and_device_union(db_session):
    actor, accesses, _, claims, registration = await authored_audience(db_session)
    draft, _, request = await reviewed_draft(db_session, actor)
    await _send(db_session, actor, draft, request)
    accesses[0].is_enabled = False
    await db_session.commit()
    notifications = list(await db_session.scalars(select(MobileNotificationModel)))
    allowed = await retain_authorized_authored_notifications(
        db_session, notifications=notifications, now=datetime.now(UTC)
    )
    assert len(allowed) == 2
    assert all(
        row.public_payload == {"route": "updates", "event_id": str(row.id)} for row in allowed
    )
    targets = await load_authored_recipient_registrations(
        db_session, notifications=allowed, provider_name="fcm", now=datetime.now(UTC)
    )
    assert [row.id for values in targets.values() for row in values] == [registration.id]
    page = await list_mobile_notifications(
        trip_id=None,
        cursor=None,
        unread_only=False,
        limit=100,
        claims=claims,
        session=db_session,
        notification_type="gc_alert",
    )
    assert len(page.items) == 1 and page.items[0].trip_id is None
    assert (
        await mark_mobile_notification_read(page.items[0].id, claims, db_session)
    ).read_at is not None
    general = await list_mobile_notifications(
        trip_id=None, cursor=None, unread_only=False, limit=100, claims=claims, session=db_session
    )
    assert general.items == []


async def test_deleted_trip_does_not_cascade_entire_other_trip_alert(db_session):
    from app.infrastructure.database.models import PassportSubmissionModel

    actor, accesses, _, _, _ = await authored_audience(db_session)
    draft, _, request = await reviewed_draft(db_session, actor)
    await _send(db_session, actor, draft, request)
    removed_group_id = accesses[0].group_id
    # The real schema restricts group removal while its passport rows exist.
    # Remove only this test's first-trip records in dependency order; frozen
    # recipient grants intentionally have no cascading FK to either record.
    await db_session.execute(
        delete(PassportSubmissionModel).where(
            PassportSubmissionModel.agency_id == actor.agency_id,
            PassportSubmissionModel.group_id == removed_group_id,
        )
    )
    await db_session.execute(
        delete(ClientGroupModel).where(
            ClientGroupModel.id == removed_group_id, ClientGroupModel.agency_id == actor.agency_id
        )
    )
    await db_session.commit()
    assert (
        await db_session.scalar(
            select(ClientGroupModel.id).where(ClientGroupModel.id == removed_group_id)
        )
        is None
    )
    assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 2
    assert (
        await db_session.scalar(select(func.count()).select_from(GCNotificationRecipientGrantModel))
        == 3
    )
    notifications = list(await db_session.scalars(select(MobileNotificationModel)))
    assert len(notifications) == 2
    assert (
        len(
            await retain_authorized_authored_notifications(
                db_session, notifications=notifications, now=datetime.now(UTC)
            )
        )
        == 2
    )


async def test_all_original_grants_lost_cancels_without_adding_new_group(db_session):
    actor, accesses, _, _, _ = await authored_audience(db_session)
    draft, _, request = await reviewed_draft(db_session, actor, group_ids=[accesses[0].group_id])
    await _send(db_session, actor, draft, request)
    accesses[0].is_enabled = False
    await db_session.commit()
    notifications = list(await db_session.scalars(select(MobileNotificationModel)))
    assert (
        await retain_authorized_authored_notifications(
            db_session, notifications=notifications, now=datetime.now(UTC)
        )
        == []
    )
    assert notifications[0].status == "cancelled"


async def test_selected_paused_trip_is_rejected_instead_of_silently_omitted(db_session):
    actor, accesses, _, _, _ = await authored_audience(db_session)
    draft, _, _ = await reviewed_draft(
        db_session, actor, group_ids=[access.group_id for access in accesses]
    )
    accesses[0].is_enabled = False
    await db_session.commit()
    with pytest.raises(HTTPException) as error:
        await preview_notification(
            db_session,
            agency_id=actor.agency_id,
            actor_id=actor.id,
            draft_id=draft.id,
            revision=draft.revision,
        )
    assert error.value.detail == "audience_changed"


async def test_no_device_can_be_sent_and_legacy_notifications_pass_through_unchanged(db_session):
    actor, _, _, _, _ = await authored_audience(db_session, device=False)
    draft, preview, request = await reviewed_draft(db_session, actor)
    assert preview.eligible_device_count == 0 and preview.no_active_registration_count == 2
    assert (await _send(db_session, actor, draft, request)).expires_at is not None
    legacy = MobileNotificationModel(
        id=uuid.uuid4(), notification_type="personal_document_changed", status="queued"
    )
    assert await retain_authorized_authored_notifications(
        db_session, notifications=[legacy], now=datetime.now(UTC)
    ) == [legacy]
    assert legacy.status == "queued"


async def test_claim_generation_change_blocks_old_device_binding_even_same_phone(db_session):
    actor, accesses, _, _, registration = await authored_audience(db_session)
    draft, _, request = await reviewed_draft(db_session, actor)
    await _send(db_session, actor, draft, request)
    identities = list(
        await db_session.scalars(
            select(MobilePassengerIdentityModel).where(
                MobilePassengerIdentityModel.normalized_phone_number == "+919876543210"
            )
        )
    )
    for identity in identities:
        identity.claim_generation += 1
    await db_session.commit()
    notifications = list(await db_session.scalars(select(MobileNotificationModel)))
    targets = await load_authored_recipient_registrations(
        db_session, notifications=notifications, provider_name="fcm", now=datetime.now(UTC)
    )
    assert all(registration.id not in {row.id for row in values} for values in targets.values())


async def test_separate_batches_for_same_phone_never_share_unrelated_trip_device_grants(db_session):
    from app.application.mobile.authored_notification_audience import passenger_person_key
    from app.infrastructure.database.gc_mobile_models import MobilePushRegistrationModel
    from tests.gc_app_workflow_fixtures import workflow_session

    actor, accesses, _, _, _ = await authored_audience(db_session, device=False)
    identities = list(
        await db_session.scalars(
            select(MobilePassengerIdentityModel).where(
                MobilePassengerIdentityModel.normalized_phone_number == "+919876543210"
            )
        )
    )
    registrations = {}
    notifications = []
    for identity in identities:
        device, _ = await workflow_session(db_session, [identity])
        registration = MobilePushRegistrationModel(
            id=uuid.uuid4(),
            agency_id=actor.agency_id,
            session_id=device.id,
            provider="fcm",
            platform="android",
            environment="development",
            app_bundle_id="com.globalconnects.groupcompanion",
            token_ciphertext=b"synthetic",
            token_lookup_hash=uuid.uuid4().hex * 2,
            token_key_version=1,
            status="active",
            notifications_authorized=True,
        )
        db_session.add(registration)
        await db_session.flush()
        draft, _, request = await reviewed_draft(db_session, actor, group_ids=[identity.group_id])
        batch = await _send(db_session, actor, draft, request)
        notification = await db_session.scalar(
            select(MobileNotificationModel)
            .join(
                GCNotificationRecipientModel,
                GCNotificationRecipientModel.id == MobileNotificationModel.authored_recipient_id,
            )
            .where(
                GCNotificationRecipientModel.batch_id == batch.id,
                GCNotificationRecipientModel.person_key
                == passenger_person_key(actor.agency_id, "+919876543210"),
            )
        )
        notifications.append(notification)
        registrations[notification.authored_recipient_id] = registration.id
    await db_session.commit()
    targets = await load_authored_recipient_registrations(
        db_session, notifications=notifications, provider_name="fcm", now=datetime.now(UTC)
    )
    assert len(targets) == 2
    for (_, recipient_id, _), rows in targets.items():
        assert [row.id for row in rows] == [registrations[recipient_id]]


async def test_all_three_roles_are_deduplicated_and_coordinator_local_expiry_is_immediate(
    db_session,
):
    from app.application.mobile.authored_notification_audience import collect_notification_audience
    from app.infrastructure.database.gc_mobile_models import (
        ClientManagerGroupAssignmentModel,
        ClientManagerProfileModel,
        ClientOrganizationModel,
    )
    from app.infrastructure.database.models import CoordinatorGroupAssignmentModel, UserModel

    actor, accesses, _, _, _ = await authored_audience(db_session, device=False)
    organization = ClientOrganizationModel(
        id=uuid.uuid4(),
        agency_id=actor.agency_id,
        name="Client company",
        normalized_name="client company",
        status="active",
    )
    manager = UserModel(
        id=uuid.uuid4(),
        agency_id=actor.agency_id,
        role="client_manager",
        full_name="Manager",
        email=f"{uuid.uuid4()}@example.test",
        hashed_password="synthetic",
        is_active=True,
    )
    coordinator = UserModel(
        id=uuid.uuid4(),
        agency_id=actor.agency_id,
        role="agency_coordinator",
        full_name="Coordinator",
        email=f"{uuid.uuid4()}@example.test",
        hashed_password="synthetic",
        is_active=True,
    )
    db_session.add_all([organization, manager, coordinator])
    await db_session.flush()
    profile = ClientManagerProfileModel(
        id=uuid.uuid4(),
        agency_id=actor.agency_id,
        organization_id=organization.id,
        user_id=manager.id,
        normalized_phone_number="+919876543299",
        status="active",
        activated_at=datetime.now(UTC),
    )
    db_session.add(profile)
    await db_session.flush()
    for access in accesses:
        access.client_organization_id = organization.id
        access.client_manager_access_enabled = access.coordinator_access_enabled = True
    # Assignment FKs include the access row's organization. Persist the parent
    # update before inserting child assignments (ORM has no relationships here).
    await db_session.flush()
    for access in accesses:
        db_session.add(
            ClientManagerGroupAssignmentModel(
                id=uuid.uuid4(),
                agency_id=actor.agency_id,
                organization_id=organization.id,
                profile_id=profile.id,
                group_id=access.group_id,
                gc_group_access_id=access.id,
                is_active=True,
            )
        )
        db_session.add(
            CoordinatorGroupAssignmentModel(
                id=uuid.uuid4(),
                agency_id=actor.agency_id,
                coordinator_user_id=coordinator.id,
                group_id=access.group_id,
                active=True,
            )
        )
    await db_session.flush()
    now = datetime.now(UTC)
    audience = await collect_notification_audience(
        db_session, agency_id=actor.agency_id, group_ids=None, now=now
    )
    assert audience.role_counts == {"passengers": 2, "client_managers": 1, "coordinators": 1}
    for access in accesses:
        group = await db_session.get(ClientGroupModel, access.group_id)
        group.return_date = now.date() - timedelta(days=2)
    await db_session.flush()
    audience = await collect_notification_audience(
        db_session, agency_id=actor.agency_id, group_ids=None, now=now
    )
    assert audience.role_counts == {"passengers": 2, "client_managers": 1, "coordinators": 0}
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(CoordinatorGroupAssignmentModel)
            .where(CoordinatorGroupAssignmentModel.active.is_(True))
        )
        == 2
    )
