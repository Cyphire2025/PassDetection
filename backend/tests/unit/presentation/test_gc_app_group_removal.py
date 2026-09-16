"""GC App removal is scoped, durable, reversible, and leaves original data intact."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.application.mobile.passenger_session_authority import (
    ensure_current_passenger_session_bindings,
)
from app.application.security.mobile_access_policy import MobileAccessPolicy
from app.core.config.settings import get_settings
from app.domain.entities.entities import UserRole
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.gc_mobile_models import (
    GCAnnouncementModel,
    GCGroupAccessModel,
    MobileDeviceSessionModel,
    MobileRefreshTokenModel,
    MobileSyncChangeModel,
)
from app.infrastructure.database.models import AuditLogModel, Base, ClientGroupModel
from app.presentation.api.v1.routes.gc_app import get_gc_group_access
from app.presentation.api.v1.routes.gc_app_content import create_announcement
from app.presentation.api.v1.routes.gc_app_group_removal import remove_gc_group_access
from app.presentation.dependencies.auth import get_current_active_user
from tests.authored_notification_fixtures import authored_audience, reviewed_draft
from tests.unit.presentation.test_gc_app_announcement_atomic_publish import body, request
from tests.unit.presentation.test_gc_app_availability import _search
from tests.unit.presentation.test_gc_app_closed_collection_groups import _configure, _context

pytestmark = pytest.mark.asyncio
PREFIX = "/api/v1/gc-app/admin/groups"


async def configured_group(session):
    actor, organization, group = await _context(session)
    response = await _configure(session, actor, organization, group)
    await session.commit()
    return actor, organization, group, response


async def remove(session, actor, group_id, revision):
    return await remove_gc_group_access(group_id, request(), revision, None, actor, session)


@pytest.mark.parametrize("role", [UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER])
@pytest.mark.parametrize("lifecycle", ["closed", "archived", "deleted"])
async def test_authorized_operator_can_remove_old_group_from_list(client, db_session, role, lifecycle):
    actor, _, group, configured = await configured_group(db_session)
    group.status = lifecycle
    group.deleted_at = datetime.now(UTC) if lifecycle == "deleted" else None
    actor.role = role
    await db_session.commit()
    client._transport.app.dependency_overrides[get_current_active_user] = lambda: actor
    scope = {"agency_id": str(actor.agency_id)} if role == UserRole.SUPER_ADMIN else {}
    deleted = await client.delete(f"{PREFIX}/{group.id}/app-setup", params={**scope, "expected_revision": configured.revision})
    assert deleted.status_code == 204 and not deleted.content
    listed = await client.get(PREFIX, params={**scope, "configured_only": "true"})
    assert listed.status_code == 200 and listed.json()["total"] == 0
    access = (await db_session.scalars(select(GCGroupAccessModel))).one()
    assert access.removed_at is not None and not access.is_enabled and access.revoked_at is not None
    assert access.access_generation == configured.access_generation + 1
    assert group.status == lifecycle
    assert (await db_session.scalars(select(ClientGroupModel))).one().id == group.id
    assert (await client.delete(f"{PREFIX}/{group.id}/app-setup", params={**scope, "expected_revision": access.revision})).status_code == 204
    audits = list(await db_session.scalars(select(AuditLogModel).where(AuditLogModel.action == "gc_app.group_removed")))
    assert len(audits) == 1 and audits[0].user_id == actor.id
    changes = list(await db_session.scalars(select(MobileSyncChangeModel).where(MobileSyncChangeModel.operation == "revoke")))
    assert len(changes) == 1 and changes[0].entity_type == "group_access"
    assert changes[0].payload["purge_required"] is True


@pytest.mark.parametrize("role", [UserRole.AGENCY_STAFF, UserRole.AGENCY_COORDINATOR, UserRole.CLIENT_MANAGER])
async def test_normal_staff_cannot_remove_group(client, db_session, role):
    actor, _, group, configured = await configured_group(db_session)
    actor.role = role
    client._transport.app.dependency_overrides[get_current_active_user] = lambda: actor
    response = await client.delete(f"{PREFIX}/{group.id}/app-setup", params={"expected_revision": configured.revision})
    assert response.status_code == 403
    assert (await db_session.scalar(select(GCGroupAccessModel))).removed_at is None


async def test_delete_checks_tenant_revision_and_cookie_csrf(client, db_session):
    actor, _, group, configured = await configured_group(db_session)
    other, _, _ = await _context(db_session)
    client._transport.app.dependency_overrides[get_current_active_user] = lambda: other
    assert (await client.delete(f"{PREFIX}/{group.id}/app-setup", params={"expected_revision": 1})).status_code == 404
    client._transport.app.dependency_overrides[get_current_active_user] = lambda: actor
    assert (await client.delete(f"{PREFIX}/{group.id}/app-setup", params={"expected_revision": 1, "agency_id": str(other.agency_id)})).status_code == 403
    for params in ({}, {"expected_revision": 0}):
        assert (await client.delete(f"{PREFIX}/{group.id}/app-setup", params=params)).status_code == 422
    assert (await client.delete(f"{PREFIX}/{group.id}/app-setup", params={"expected_revision": 2})).status_code == 409
    client.cookies.set(get_settings().jwt.access_cookie_name, "synthetic-session-cookie")
    assert (await client.delete(f"{PREFIX}/{group.id}/app-setup", params={"expected_revision": configured.revision}, headers={"origin": "https://untrusted.example"})).status_code == 403
    assert (await db_session.scalar(select(GCGroupAccessModel))).removed_at is None


async def test_deliberate_readd_preserves_history_and_rejects_old_delete_or_ordinary_edit(db_session):
    actor, organization, group, configured = await configured_group(db_session)
    await remove(db_session, actor, group.id, configured.revision)
    removed = await get_gc_group_access(group.id, None, actor, db_session)
    assert removed.removed_at is not None and removed.app_availability_reason == "not_configured"
    candidates = await _search(db_session, actor, eligible_only=True, unconfigured_only=True)
    assert candidates.total == 1 and candidates.items[0].access.revision == removed.revision
    for changes in ({}, {"restore_removed": True, "enabled": False}):
        with pytest.raises(HTTPException) as ordinary:
            await _configure(db_session, actor, organization, group, expected_revision=removed.revision, **changes)
        assert ordinary.value.status_code == 409
    with pytest.raises(HTTPException) as content:
        await create_announcement(group.id, body(removed.revision), request(), None, actor, db_session)
    assert content.value.status_code == 404
    restored = await _configure(db_session, actor, organization, group, expected_revision=removed.revision, restore_removed=True)
    await db_session.commit()
    assert restored.removed_at is None and restored.enabled
    assert restored.access_generation == removed.access_generation + 1
    with pytest.raises(HTTPException) as stale:
        await remove(db_session, actor, group.id, removed.revision)
    assert stale.value.status_code == 409
    assert (await _search(db_session, actor, configured_only=True)).total == 1
    assert (await _search(db_session, actor, unconfigured_only=True)).total == 0
    assert (await db_session.scalar(select(GCGroupAccessModel))).id is not None


@pytest.mark.parametrize("lifecycle", ["archived", "deleted"])
async def test_readd_rejects_unavailable_original_group(db_session, lifecycle):
    actor, organization, group, configured = await configured_group(db_session)
    await remove(db_session, actor, group.id, configured.revision)
    group.status = lifecycle
    await db_session.commit()
    with pytest.raises(HTTPException) as rejected:
        await _configure(db_session, actor, organization, group, expected_revision=configured.revision + 1, restore_removed=True)
    assert rejected.value.status_code == 409


async def test_removal_preserves_all_rows_send_history_and_other_trip_session(client, db_session):
    actor, accesses, _, claims, _ = await authored_audience(db_session)
    access, other_access = accesses
    announcement = GCAnnouncementModel(
        agency_id=access.agency_id, group_id=access.group_id, gc_group_access_id=access.id,
        category="general", priority="normal", title="Retained draft", body="Synthetic",
        version=1, status="draft",
    )
    db_session.add(announcement)
    draft, _, send = await reviewed_draft(db_session, actor)
    await db_session.commit()
    client._transport.app.dependency_overrides[get_current_active_user] = lambda: actor
    sent = await client.post(f"/api/v1/gc-app/admin/notifications/{draft.id}/send", json=send.model_dump(mode="json"))
    assert sent.status_code == 202
    before = {
        table.name: (await db_session.execute(select(table).order_by(*table.primary_key.columns))).mappings().all()
        for table in Base.metadata.sorted_tables
    }
    assert (await remove(db_session, actor, access.group_id, access.revision)).status_code == 204
    for table in Base.metadata.sorted_tables:
        after = (await db_session.execute(select(table).order_by(*table.primary_key.columns))).mappings().all()
        assert len(after) >= len(before[table.name]), table.name
        if table.name not in {"gc_group_access", "audit_logs", "audit_chain_heads", "mobile_sync_changes"}:
            assert after == before[table.name], table.name
    device = await db_session.get(MobileDeviceSessionModel, claims.session_id)
    assert device.status == "active" and await ensure_current_passenger_session_bindings(db_session, device)
    assert (await db_session.scalar(select(MobileRefreshTokenModel))).revoked_at is None
    with pytest.raises(AuthorizationError):
        await MobileAccessPolicy(db_session).require_trip_access(claims, access.group_id)
    # The other identity is discovered and selected through existing normal
    # session authorization, without touching the revoked trip's generation.
    from dataclasses import replace

    from app.infrastructure.database.gc_mobile_models import MobilePassengerIdentityModel
    identity = await db_session.scalar(select(MobilePassengerIdentityModel).where(MobilePassengerIdentityModel.group_id == other_access.group_id, MobilePassengerIdentityModel.normalized_phone_number == "+919876543210"))
    other_claims = replace(claims, principal_id=identity.id)
    assert (await MobileAccessPolicy(db_session).require_trip_access(other_claims, other_access.group_id)).group.id == other_access.group_id


async def test_failed_commit_does_not_acknowledge_or_partially_remove(db_session, monkeypatch):
    actor, _, group, configured = await configured_group(db_session)
    group_id = group.id
    commit = db_session.commit
    monkeypatch.setattr(db_session, "commit", AsyncMock(side_effect=RuntimeError("commit unavailable")))
    with pytest.raises(RuntimeError, match="commit unavailable"):
        await remove(db_session, actor, group_id, configured.revision)
    await db_session.rollback()
    access = await db_session.scalar(select(GCGroupAccessModel))
    assert access.removed_at is None and access.is_enabled and access.revision == configured.revision
    monkeypatch.setattr(db_session, "commit", commit)
    assert (await remove(db_session, actor, group_id, configured.revision)).status_code == 204


async def test_missing_group_does_not_create_setup(client, db_session):
    actor, _, _, _ = await configured_group(db_session)
    client._transport.app.dependency_overrides[get_current_active_user] = lambda: actor
    assert (await client.delete(f"{PREFIX}/{uuid.uuid4()}/app-setup", params={"expected_revision": 1})).status_code == 404
