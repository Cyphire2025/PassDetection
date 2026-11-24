"""Removed app setups remain restorable after their company is unassigned."""

import pytest
from sqlalchemy import select

from app.infrastructure.database.gc_mobile_models import GCGroupAccessModel
from app.presentation.dependencies.auth import get_current_active_user
from tests.unit.presentation.test_gc_app_group_removal import configured_group, remove

pytestmark = pytest.mark.asyncio
PREFIX = "/api/v1/gc-app/admin/groups"


async def test_picker_retains_restore_state_without_company(client, db_session):
    actor, organization, group, configured = await configured_group(db_session)
    await remove(db_session, actor, group.id, configured.revision)
    access = await db_session.scalar(select(GCGroupAccessModel))
    group.company_id = None
    access.client_organization_id = None
    access.client_manager_access_enabled = False
    await db_session.commit()
    client._transport.app.dependency_overrides[get_current_active_user] = lambda: actor

    response = await client.get(PREFIX, params={"eligible_only": True, "unconfigured_only": True})
    assert response.status_code == 200
    candidate = response.json()["items"][0]
    assert candidate["id"] == str(group.id)
    assert candidate["client_organization_id"] is None
    assert candidate["access"] is not None
    assert candidate["access"]["removed_at"] is not None
    assert candidate["access"]["revision"] == access.revision
    assert candidate["access"]["client_organization_name"] is None
    payload = {
        "client_organization_id": str(organization.id),
        "enabled": True,
        "restore_removed": True,
        "expected_revision": candidate["access"]["revision"],
    }
    stale = await client.put(f"{PREFIX}/{group.id}", json={**payload, "expected_revision": 1})
    assert stale.status_code == 409
    restored = await client.put(f"{PREFIX}/{group.id}", json=payload)
    assert restored.status_code == 200
    assert restored.json()["removed_at"] is None
    assert restored.json()["enabled"] is True
    assert restored.json()["client_organization_id"] == str(organization.id)
    assert group.company_id == organization.id
