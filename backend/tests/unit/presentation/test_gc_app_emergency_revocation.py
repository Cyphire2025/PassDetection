"""Legacy emergency revocation remains distinct from removal of an app setup."""

import pytest
from sqlalchemy import select

from app.core.config.settings import get_settings
from app.domain.entities.entities import UserRole
from app.infrastructure.database.gc_mobile_models import (
    GCGroupAccessModel,
    MobileDeviceSessionModel,
    MobileRefreshTokenModel,
    MobileSyncChangeModel,
)
from app.infrastructure.database.models import AuditLogModel
from app.presentation.dependencies.auth import get_current_active_user
from tests.authored_notification_fixtures import authored_audience
from tests.unit.presentation.test_gc_app_group_removal import PREFIX, configured_group, remove


@pytest.mark.parametrize("include_revision", [False, True])
async def test_emergency_path_keeps_setup_and_invalidates_sessions(client, db_session, include_revision):
    actor, accesses, _, claims, _ = await authored_audience(db_session)
    access, other_access = accesses
    group_id, revision = access.group_id, access.revision
    client._transport.app.dependency_overrides[get_current_active_user] = lambda: actor
    params = {"expected_revision": revision} if include_revision else {}
    response = await client.delete(f"{PREFIX}/{group_id}", params=params)
    assert response.status_code == 204
    await db_session.refresh(access)
    assert access.removed_at is None and not access.is_enabled
    assert not access.passenger_access_enabled and not access.client_manager_access_enabled
    assert not access.coordinator_access_enabled and access.revoked_at is not None
    assert access.revision == revision + 1
    device = await db_session.get(MobileDeviceSessionModel, claims.session_id)
    assert device.status == "revoked" and device.revoke_reason == "group_access_revoked"
    assert (await db_session.scalar(select(MobileRefreshTokenModel))).revoked_at is not None
    assert other_access.is_enabled and other_access.removed_at is None
    listed = await client.get(PREFIX, params={"configured_only": "true"})
    assert listed.status_code == 200 and listed.json()["total"] == 2
    changes = list(await db_session.scalars(select(MobileSyncChangeModel)))
    assert len(changes) == 4
    assert {row.entity_type for row in changes} == {"group_access", "role_access"}
    assert {row.audience for row in changes} == {"all", "passenger", "client_manager", "coordinator"}
    assert all(row.operation == "revoke" for row in changes)
    assert await db_session.scalar(select(AuditLogModel.id).where(AuditLogModel.action == "gc_app.group_revoked"))


async def test_emergency_revoke_checks_revision_role_tenant_csrf_and_removed_state(client, db_session):
    actor, _, group, configured = await configured_group(db_session)
    other, _, _, _ = await configured_group(db_session)
    client._transport.app.dependency_overrides[get_current_active_user] = lambda: actor
    assert (await client.delete(f"{PREFIX}/{group.id}", params={"expected_revision": configured.revision + 1})).status_code == 409
    assert (await client.delete(f"{PREFIX}/{group.id}", params={"agency_id": str(other.agency_id)})).status_code == 403
    actor.role = UserRole.AGENCY_STAFF
    assert (await client.delete(f"{PREFIX}/{group.id}")).status_code == 403
    actor.role = UserRole.AGENCY_ADMIN
    client.cookies.set(get_settings().jwt.access_cookie_name, "synthetic-session-cookie")
    assert (await client.delete(f"{PREFIX}/{group.id}", headers={"origin": "https://untrusted.example"})).status_code == 403
    client.cookies.clear()
    access = await db_session.scalar(select(GCGroupAccessModel).where(GCGroupAccessModel.group_id == group.id))
    assert access.is_enabled and access.revision == configured.revision
    await remove(db_session, actor, group.id, configured.revision)
    assert (await client.delete(f"{PREFIX}/{group.id}")).status_code == 404
    assert access.removed_at is not None
