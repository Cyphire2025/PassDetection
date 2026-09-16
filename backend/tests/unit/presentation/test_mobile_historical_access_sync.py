"""Old session invalidations must not revoke a newly authorized trip reader."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from starlette.requests import Request

from app.application.security.mobile_access_policy import AuthorizedMobileTrip
from app.core.security.mobile_jwt import create_mobile_access_token
from app.infrastructure.database.gc_mobile_models import (
    ClientOrganizationModel,
    MobileSyncChangeModel,
)
from app.presentation.api.v1.routes.gc_app import configure_gc_group_access
from app.presentation.api.v1.routes.mobile_sync_projection import authorized_mobile_sync_operation
from app.presentation.api.v1.schemas.gc_app_schemas import GCGroupAccessUpdateRequest
from tests.gc_app_workflow_fixtures import workflow_group, workflow_passenger, workflow_session


def event(access, kind, operation="revoke", *, identity=None, generation=None, audience="passenger"):
    return MobileSyncChangeModel(
        id=uuid.uuid4(), agency_id=access.agency_id, group_id=access.group_id,
        gc_group_access_id=access.id, access_generation=generation or access.access_generation,
        entity_type=kind, entity_id=identity.id if identity is not None else access.id,
        passenger_identity_id=identity.id if identity is not None else None,
        audience=audience, operation=operation, version=1,
        occurred_at=datetime.now(UTC) - timedelta(minutes=10),
        payload={"resource_path": f"/api/v1/mobile/trips/{access.group_id}/manifest",
                 "purge_required": operation == "revoke", "enabled": operation != "revoke"},
    )


def headers(device, identity):
    token, _ = create_mobile_access_token(
        principal_id=identity.id, account_id=device.account_id, principal_type="passenger",
        agency_id=device.agency_id, session_id=device.id,
        session_generation=device.session_generation, password_change_required=False,
    )
    return {"Authorization": f"Bearer {token}"}


async def seeded_history(session, *, reactivated=False):
    _, group, access = await workflow_group(session)
    access.access_generation = 2
    _, identity = await workflow_passenger(session, access)
    rows = [event(access, "group_access", "upsert", generation=1),
            event(access, "group_access", "upsert"), event(access, "role_access"),
            event(access, "group_access"), event(access, "gc_group_access")]
    if reactivated:
        rows.append(event(access, "passenger_identity", identity=identity))
        identity.claim_generation += 1
    rows.append(event(access, "passenger_identity", "upsert", identity=identity))
    session.add_all(rows)
    device, _ = await workflow_session(session, [identity])
    device.session_generation = 1
    device.last_seen_at = datetime.now(UTC)
    await session.commit()
    return group, access, identity, device, rows


@pytest.mark.asyncio
@pytest.mark.parametrize("reactivated", [False, True])
async def test_new_session_passes_historical_revokes_and_advances_without_rewriting_history(
    db_session, client, reactivated,
):
    group, _, identity, device, rows = await seeded_history(db_session, reactivated=reactivated)
    before = [(row.id, row.sequence, row.operation, dict(row.payload), row.occurred_at) for row in rows]
    response = await client.get(f"/api/v1/mobile/sync/changes?trip_id={group.id}&cursor=0",
                                headers=headers(device, identity))
    assert response.status_code == 200, response.text
    data = response.json()
    assert [item["operation"] for item in data["changes"]] == ["upsert"] * (len(rows) - 1)
    assert [item["sequence"] for item in data["changes"]] == [row.sequence for row in rows[1:]]
    assert [item["entity_id"] for item in data["changes"]] == [str(row.entity_id) for row in rows[1:]]
    assert all("enabled" not in item["payload"] and "purge_required" not in item["payload"] for item in data["changes"])
    assert data["next_cursor"] == rows[-1].sequence and data["has_more"] is False
    next_page = await client.get(
        f"/api/v1/mobile/sync/changes?trip_id={group.id}&cursor={data['next_cursor']}",
        headers=headers(device, identity),
    )
    assert next_page.status_code == 200 and next_page.json()["changes"] == []
    persisted = list(await db_session.scalars(select(MobileSyncChangeModel).order_by(MobileSyncChangeModel.sequence)))
    assert [(row.id, row.sequence, row.operation, dict(row.payload), row.occurred_at) for row in persisted] == before


@pytest.mark.asyncio
@pytest.mark.parametrize("revocation", ["session", "group", "role", "identity", "claim_generation"])
async def test_current_revocation_is_denied_before_historical_projection(db_session, client, revocation):
    group, access, identity, device, rows = await seeded_history(db_session)
    auth = headers(device, identity)
    allowed = await client.get(f"/api/v1/mobile/sync/changes?trip_id={group.id}&cursor=0", headers=auth)
    assert allowed.status_code == 200
    if revocation == "session":
        device.status = "revoked"
        device.revoked_at = datetime.now(UTC)
    elif revocation == "group":
        access.is_enabled = False
    elif revocation == "role":
        access.passenger_access_enabled = False
    elif revocation == "identity":
        identity.status = "revoked"
        identity.revoked_at = datetime.now(UTC)
    else:
        identity.claim_generation += 1
    await db_session.commit()
    response = await client.get(f"/api/v1/mobile/sync/changes?trip_id={group.id}&cursor=0", headers=auth)
    assert response.status_code == (403 if revocation in {"group", "role"} else 401)
    assert "changes" not in response.json()
    assert (await db_session.get(MobileSyncChangeModel, rows[2].sequence)).operation == "revoke"


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["agency", "group", "access", "generation", "role", "entity", "unknown"])
async def test_projection_keeps_unrelated_or_unknown_revocations(db_session, mismatch):
    _, group, access = await workflow_group(db_session)
    _, identity = await workflow_passenger(db_session, access)
    change = event(access, "role_access")
    if mismatch in {"agency", "group", "entity"}:
        setattr(change, f"{mismatch}_id", uuid.uuid4())
    elif mismatch == "access":
        change.gc_group_access_id = uuid.uuid4()
    elif mismatch == "generation":
        change.access_generation += 1
    elif mismatch == "role":
        change.audience = "coordinator"
    else:
        change.entity_type = "future_unknown_access"
    trip = AuthorizedMobileTrip(group=group, access=access, principal_type="passenger", passenger_identity=identity)
    assert authorized_mobile_sync_operation(change, trip) == "revoke"


@pytest.mark.asyncio
@pytest.mark.parametrize("disable_role", [False, True])
async def test_window_edit_invalidates_old_session_but_only_revokes_disabled_role(db_session, client, disable_role):
    actor, group, access = await workflow_group(db_session)
    organization = ClientOrganizationModel(
        id=uuid.uuid4(), agency_id=access.agency_id, name="Synthetic company", normalized_name="synthetic company",
    )
    db_session.add(organization)
    await db_session.flush()
    access.client_organization_id = organization.id
    _, identity = await workflow_passenger(db_session, access)
    device, _ = await workflow_session(db_session, [identity])
    device_id = device.id
    body = GCGroupAccessUpdateRequest(
        enabled=True, passenger_access_enabled=not disable_role,
        client_manager_access_enabled=False, coordinator_access_enabled=False,
        client_organization_id=organization.id, expected_revision=access.revision,
        access_starts_at=datetime.now(UTC) - timedelta(days=1),
        access_expires_at=datetime.now(UTC) + timedelta(days=10),
    )
    await configure_gc_group_access(group.id, body, Request({"type": "http", "method": "PUT", "path": "/", "headers": []}),
                                    None, actor, db_session)
    await db_session.flush()
    await db_session.refresh(device)
    assert device.id == device_id and device.status == "revoked"
    rows = list(await db_session.scalars(select(MobileSyncChangeModel).where(
        MobileSyncChangeModel.entity_type == "role_access",
        MobileSyncChangeModel.audience == "passenger",
    )))
    assert len(rows) == 1
    assert rows[0].operation == ("revoke" if disable_role else "upsert")
    assert rows[0].payload["purge_required"] is disable_role
    if not disable_role:
        # Reconciliation may change the identity generation; a newly proven
        # session receives that current generation rather than reviving the old grant.
        fresh, _ = await workflow_session(db_session, [identity])
        fresh.session_generation = 1
        fresh.last_seen_at = datetime.now(UTC)
        await db_session.commit()
        response = await client.get(f"/api/v1/mobile/sync/changes?trip_id={group.id}&cursor=0",
                                    headers=headers(fresh, identity))
        assert response.status_code == 200, response.text
        assert all(change["operation"] == "upsert" for change in response.json()["changes"])
