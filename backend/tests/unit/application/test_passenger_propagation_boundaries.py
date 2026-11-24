"""Preserve shared dashboard identity thresholds and event-time version fencing."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile import passenger_change_identities as identity_changes
from app.application.mobile import passenger_change_propagation as propagation
from app.application.mobile.passenger_identity_reconciliation import (
    PassengerIdentityReconciliationResult,
)
from app.infrastructure.database.gc_mobile_models import (
    GCGroupAccessModel,
    MobilePassengerIdentityModel,
    MobileSyncChangeModel,
)
from app.infrastructure.database.models import PassportSubmissionModel
from tests.persistence import persist_mobile_access_graph


def enabled_access() -> GCGroupAccessModel:
    return GCGroupAccessModel(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        client_organization_id=uuid.uuid4(),
        is_enabled=True,
        passenger_access_enabled=True,
        client_manager_access_enabled=False,
        coordinator_access_enabled=False,
    )


@pytest.mark.parametrize("count", [0, 1, 8, 9])
async def test_identity_reconciliation_uses_bounded_seed_or_full_group(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    count: int,
) -> None:
    access = enabled_access()
    await persist_mobile_access_graph(db_session, access)
    identity_result = PassengerIdentityReconciliationResult(0, 0, 0, 0, 0, 0)
    targeted, full = (
        AsyncMock(return_value=identity_result),
        AsyncMock(return_value=identity_result),
    )
    monkeypatch.setattr(identity_changes, "reconcile_passenger_identities_for_changes", targeted)
    monkeypatch.setattr(identity_changes, "reconcile_passenger_identities", full)
    monkeypatch.setattr(propagation, "sync_group_broadcast_contacts", AsyncMock())
    ids = [uuid.uuid4() for _ in range(count)]
    result = await propagation.propagate_mobile_passenger_change(
        db_session,
        agency_id=access.agency_id,
        group_id=access.group_id,
        passenger_submission_ids=[*reversed(ids), *ids],
        actor_user_id=None,
    )
    assert result.identity_reconciliation is identity_result
    assert result.sync_changes == 0 and result.push_notifications == 0
    if count in {1, 8}:
        targeted.assert_awaited_once_with(
            db_session,
            access=access,
            actor_user_id=None,
            passenger_submission_ids=tuple(sorted(ids, key=str)),
        )
        full.assert_not_awaited()
    else:
        full.assert_awaited_once_with(db_session, access=access, actor_user_id=None)
        targeted.assert_not_awaited()


async def test_identity_version_is_not_bumped_twice_before_profile_event(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    access = enabled_access()
    passenger_id = uuid.uuid4()
    identity = MobilePassengerIdentityModel(
        id=uuid.uuid4(),
        agency_id=access.agency_id,
        group_id=access.group_id,
        gc_group_access_id=access.id,
        passenger_submission_id=passenger_id,
        normalized_phone_number="+919111111111",
        phone_lookup_hash="a" * 64,
        status="eligible",
    )
    submission = PassportSubmissionModel(
        id=passenger_id,
        agency_id=access.agency_id,
        group_id=access.group_id,
        client_name="Synthetic traveller",
        client_phone="+919111111111",
        status="client_submitted",
        image_s3_key="synthetic/passport.jpg",
    )
    await persist_mobile_access_graph(db_session, access, [submission, identity])
    version, revision = access.manifest_version, access.revision
    reconciled = PassengerIdentityReconciliationResult(0, 1, 0, 0, 0, 0)

    async def reconcile(*args, **kwargs):
        access.manifest_version += 1
        access.revision += 1
        await db_session.flush()
        return reconciled

    targeted = AsyncMock(side_effect=reconcile)
    monkeypatch.setattr(identity_changes, "reconcile_passenger_identities_for_changes", targeted)
    monkeypatch.setattr(propagation, "sync_group_broadcast_contacts", AsyncMock())
    result = await propagation.propagate_mobile_passenger_change(
        db_session,
        agency_id=access.agency_id,
        group_id=access.group_id,
        passenger_submission_ids=[passenger_id],
        actor_user_id=None,
    )
    assert result.identity_reconciliation is reconciled
    assert result.sync_changes == 1 and result.push_notifications == 0
    assert access.manifest_version == version + 1
    assert access.revision == revision + 1
    change = (await db_session.scalars(select(MobileSyncChangeModel))).one()
    assert change.version == version + 1
    assert change.passenger_identity_id == identity.id
    assert change.entity_id == passenger_id
    assert change.entity_type == "passenger_profile" and change.operation == "upsert"
    targeted.assert_awaited_once()
    assert db_session.in_transaction()  # The caller retains commit ownership.
