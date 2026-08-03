from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.application.mobile.passenger_change_propagation as propagation_module
from app.application.mobile.passenger_change_propagation import (
    plan_mobile_passenger_change_events,
    propagate_mobile_passenger_change,
)
from app.infrastructure.database.gc_mobile_models import (
    GCGroupAccessModel,
    MobileNotificationModel,
    MobilePassengerIdentityModel,
    MobileSyncChangeModel,
)


def test_plans_targeted_role_scoped_events_without_pii() -> None:
    group_id = uuid.uuid4()
    passenger_id = uuid.uuid4()
    identity_id = uuid.uuid4()

    events = plan_mobile_passenger_change_events(
        group_id=group_id,
        passenger_submission_ids=[passenger_id],
        passenger_identities=[(identity_id, passenger_id)],
        operation="upsert",
        change_kind="documents",
        passenger_access_enabled=True,
        client_manager_access_enabled=True,
        coordinator_access_enabled=True,
    )

    assert [event.audience for event in events] == [
        "coordinator",
        "client_manager",
        "passenger",
    ]
    assert [event.entity_type for event in events] == [
        "coordinator_passenger",
        "passenger_readiness",
        "personal_document",
    ]
    assert events[-1].passenger_identity_id == identity_id
    assert all(set(event.payload) == {"resource_path"} for event in events)
    assert all(str(passenger_id) not in str(event.payload) or event.audience == "coordinator" for event in events)


def test_document_delete_targets_only_the_owned_passenger_and_coordinator() -> None:
    passenger_id = uuid.uuid4()
    events = plan_mobile_passenger_change_events(
        group_id=uuid.uuid4(),
        passenger_submission_ids=[passenger_id],
        passenger_identities=[(uuid.uuid4(), passenger_id)],
        operation="delete",
        change_kind="documents",
        passenger_access_enabled=True,
        client_manager_access_enabled=False,
        coordinator_access_enabled=True,
    )

    assert len(events) == 2
    assert events[0].audience == "coordinator"
    assert events[0].operation == "delete"
    assert events[1].audience == "passenger"
    assert events[1].operation == "delete"


def test_large_import_collapses_to_one_full_roster_event() -> None:
    passenger_ids = [uuid.uuid4() for _ in range(101)]
    events = plan_mobile_passenger_change_events(
        group_id=uuid.uuid4(),
        passenger_submission_ids=passenger_ids,
        passenger_identities=[],
        operation="upsert",
        change_kind="profile",
        passenger_access_enabled=False,
        client_manager_access_enabled=False,
        coordinator_access_enabled=True,
    )

    assert len(events) == 1
    assert events[0].entity_type == "passenger_roster"
    assert events[0].entity_id is None


def test_disabled_roles_receive_no_events() -> None:
    events = plan_mobile_passenger_change_events(
        group_id=uuid.uuid4(),
        passenger_submission_ids=[uuid.uuid4()],
        passenger_identities=[],
        operation="upsert",
        change_kind="profile",
        passenger_access_enabled=False,
        client_manager_access_enabled=False,
        coordinator_access_enabled=False,
    )

    assert events == ()


@pytest.mark.asyncio
async def test_targeted_coordinator_change_carries_authoritative_roster_proof(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access = GCGroupAccessModel(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        client_organization_id=uuid.uuid4(),
        is_enabled=True,
        passenger_access_enabled=False,
        client_manager_access_enabled=False,
        coordinator_access_enabled=True,
    )
    db_session.add(access)
    await db_session.flush()
    revision = AsyncMock(return_value=4242)
    monkeypatch.setattr(propagation_module, "coordinator_roster_revision", revision)
    passenger_id = uuid.uuid4()

    result = await propagate_mobile_passenger_change(
        db_session,
        agency_id=access.agency_id,
        group_id=access.group_id,
        passenger_submission_ids=[passenger_id],
        actor_user_id=None,
        reconcile_identities=False,
    )

    assert result.sync_changes == 1
    change = (
        await db_session.execute(select(MobileSyncChangeModel))
    ).scalar_one()
    assert change.audience == "coordinator"
    assert change.entity_type == "coordinator_passenger"
    assert change.entity_id == passenger_id
    assert change.payload["roster_revision"] == 4242
    revision.assert_awaited_once_with(
        db_session,
        agency_id=access.agency_id,
        group_id=access.group_id,
    )


@pytest.mark.asyncio
async def test_document_availability_and_revocation_are_incremental_and_idempotent(
    db_session: AsyncSession,
) -> None:
    access = GCGroupAccessModel(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        client_organization_id=uuid.uuid4(),
        is_enabled=True,
        passenger_access_enabled=True,
        client_manager_access_enabled=False,
        coordinator_access_enabled=False,
    )
    identity = MobilePassengerIdentityModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        group_id=access.group_id,
        gc_group_access_id=access.id,
        passenger_submission_id=uuid.uuid4(),
        normalized_phone_number="+919999999981",
        phone_lookup_hash="8" * 64,
        status="eligible",
    )
    db_session.add_all([access, identity])
    await db_session.flush()
    initial_manifest_version = access.manifest_version

    available = await propagate_mobile_passenger_change(
        db_session,
        agency_id=access.agency_id,
        group_id=access.group_id,
        passenger_submission_ids=[identity.passenger_submission_id],
        actor_user_id=None,
        change_kind="documents",
        reconcile_identities=False,
        propagation_key="worker-batch:stable-1",
    )
    assert available.sync_changes == 1
    assert available.push_notifications == 1
    assert access.manifest_version == initial_manifest_version + 1

    # Simulate a retried worker using a fresh unit-of-work cache. The durable
    # deterministic journal id prevents another version bump or notification.
    db_session.info.pop("mobile_passenger_propagation", None)
    replay = await propagate_mobile_passenger_change(
        db_session,
        agency_id=access.agency_id,
        group_id=access.group_id,
        passenger_submission_ids=[identity.passenger_submission_id],
        actor_user_id=None,
        change_kind="documents",
        reconcile_identities=False,
        propagation_key="worker-batch:stable-1",
    )
    assert replay.sync_changes == 0
    assert replay.push_notifications == 0
    assert access.manifest_version == initial_manifest_version + 1

    db_session.info.pop("mobile_passenger_propagation", None)
    revoked = await propagate_mobile_passenger_change(
        db_session,
        agency_id=access.agency_id,
        group_id=access.group_id,
        passenger_submission_ids=[identity.passenger_submission_id],
        actor_user_id=None,
        operation="delete",
        change_kind="documents",
        reconcile_identities=False,
        propagation_key="document-revocation:stable-1",
    )
    assert revoked.sync_changes == 1
    assert revoked.push_notifications == 1
    assert access.manifest_version == initial_manifest_version + 2

    changes = list(
        (
            await db_session.execute(
                select(MobileSyncChangeModel).order_by(
                    MobileSyncChangeModel.sequence.asc()
                )
            )
        ).scalars()
    )
    notifications = list(
        (
            await db_session.execute(
                select(MobileNotificationModel).order_by(
                    MobileNotificationModel.created_at.asc()
                )
            )
        ).scalars()
    )
    assert [change.operation for change in changes] == ["upsert", "delete"]
    assert all(change.audience == "passenger" for change in changes)
    assert all(
        change.passenger_identity_id == identity.id for change in changes
    )
    assert [item.status for item in notifications] == ["queued", "queued"]
    assert all(item.lock_screen_body is None for item in notifications)
    assert all(
        set(item.public_payload) == {"route", "trip_id"}
        for item in notifications
    )
    assert all(
        str(identity.passenger_submission_id) not in str(item.public_payload)
        for item in notifications
    )


@pytest.mark.asyncio
async def test_document_only_change_never_reconciles_identity_bindings(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access = GCGroupAccessModel(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        client_organization_id=uuid.uuid4(),
        is_enabled=True,
        passenger_access_enabled=True,
        client_manager_access_enabled=False,
        coordinator_access_enabled=False,
    )
    db_session.add(access)
    await db_session.flush()
    targeted = AsyncMock()
    full = AsyncMock()
    monkeypatch.setattr(
        propagation_module,
        "reconcile_passenger_identities_for_changes",
        targeted,
    )
    monkeypatch.setattr(
        propagation_module,
        "reconcile_passenger_identities",
        full,
    )

    await propagate_mobile_passenger_change(
        db_session,
        agency_id=access.agency_id,
        group_id=access.group_id,
        passenger_submission_ids=[uuid.uuid4()],
        actor_user_id=None,
        change_kind="documents",
    )

    targeted.assert_not_awaited()
    full.assert_not_awaited()
