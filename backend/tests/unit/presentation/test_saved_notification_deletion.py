"""Deletion is an authorized, revision-checked saved-list action; history survives."""

import uuid

import pytest
from sqlalchemy import select

from app.domain.entities.entities import UserRole
from app.infrastructure.database.gc_notification_models import GCNotificationDraftModel
from app.presentation.dependencies.auth import get_current_active_user
from tests.authored_notification_fixtures import authored_audience, reviewed_draft

pytestmark = pytest.mark.asyncio
_PREFIX = "/api/v1/gc-app/admin/notifications"


@pytest.mark.parametrize(
    "role", [UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER, UserRole.SUPER_ADMIN]
)
async def test_authorized_delete_hides_saved_message_but_preserves_send_log(
    client, db_session, role
):
    actor, _, _, _, _ = await authored_audience(db_session, device=False)
    actor.role = role
    client._transport.app.dependency_overrides[get_current_active_user] = lambda: actor
    draft, _, request = await reviewed_draft(db_session, actor)
    await db_session.commit()
    scope = {"agency_id": str(actor.agency_id)} if role == UserRole.SUPER_ADMIN else {}
    sent = await client.post(
        f"{_PREFIX}/{draft.id}/send", params=scope, json=request.model_dump(mode="json")
    )
    assert sent.status_code == 202, sent.text
    params = {**scope, "expected_revision": 1}
    deleted = await client.delete(f"{_PREFIX}/{draft.id}", params=params)
    assert deleted.status_code == 204 and not deleted.content
    assert (await client.get(_PREFIX, params=scope)).json()["items"] == []
    assert (await client.get(f"{_PREFIX}/{draft.id}", params=scope)).status_code == 404
    history = (await client.get(f"{_PREFIX}/batches", params=scope)).json()
    assert history["items"][0]["id"] == sent.json()["id"]
    assert history["items"][0]["recipient_counts"]["queued"] == 2
    assert (await client.delete(f"{_PREFIX}/{draft.id}", params=params)).status_code == 204
    restored = await client.post(
        f"{_PREFIX}/{draft.id}/send", params=scope, json=request.model_dump(mode="json")
    )
    assert restored.status_code == 202 and restored.json()["id"] == sent.json()["id"]
    recovered = await client.get(
        f"{_PREFIX}/batches/by-request/{request.request_id}",
        params={**scope, "draft_id": str(draft.id)},
    )
    assert recovered.status_code == 200 and recovered.json()["id"] == sent.json()["id"]
    assert (await db_session.scalar(select(GCNotificationDraftModel))).deleted_at is not None


@pytest.mark.parametrize(
    "role", [UserRole.AGENCY_STAFF, UserRole.AGENCY_COORDINATOR, UserRole.CLIENT_MANAGER]
)
async def test_non_operator_cannot_delete_saved_notifications(client, db_session, role):
    actor, _, _, _, _ = await authored_audience(db_session, device=False)
    draft, _, _ = await reviewed_draft(db_session, actor)
    actor.role = role
    client._transport.app.dependency_overrides[get_current_active_user] = lambda: actor
    response = await client.delete(f"{_PREFIX}/{draft.id}", params={"expected_revision": 1})
    assert response.status_code == 403
    assert draft.deleted_at is None


async def test_delete_enforces_tenant_revision_and_cookie_csrf(client, db_session):
    from app.core.config.settings import get_settings

    actor, _, _, _, _ = await authored_audience(db_session, device=False)
    other, _, _, _, _ = await authored_audience(db_session, device=False)
    draft, _, _ = await reviewed_draft(db_session, actor)
    client._transport.app.dependency_overrides[get_current_active_user] = lambda: other
    assert (
        await client.delete(f"{_PREFIX}/{draft.id}", params={"expected_revision": 1})
    ).status_code == 404
    client._transport.app.dependency_overrides[get_current_active_user] = lambda: actor
    assert (await client.delete(f"{_PREFIX}/{draft.id}")).status_code == 422
    assert (
        await client.delete(f"{_PREFIX}/{draft.id}", params={"expected_revision": 0})
    ).status_code == 422
    assert (
        await client.delete(f"{_PREFIX}/{draft.id}", params={"expected_revision": 2})
    ).status_code == 409
    client.cookies.set(get_settings().jwt.access_cookie_name, "synthetic-session-cookie")
    response = await client.delete(
        f"{_PREFIX}/{draft.id}",
        params={"expected_revision": 1},
        headers={"origin": "https://untrusted.example"},
    )
    assert response.status_code == 403 and draft.deleted_at is None


async def test_failed_delete_commit_returns_error_and_keeps_message_available(
    db_session, monkeypatch
):
    from unittest.mock import AsyncMock

    from app.application.mobile.authored_notification_service import require_draft
    from app.presentation.api.v1.routes.gc_notifications import delete_draft

    actor, _, _, _, _ = await authored_audience(db_session, device=False)
    draft, _, _ = await reviewed_draft(db_session, actor)
    draft_id, agency_id = draft.id, actor.agency_id
    await db_session.commit()
    real_commit = db_session.commit
    monkeypatch.setattr(
        db_session, "commit", AsyncMock(side_effect=RuntimeError("commit unavailable"))
    )
    with pytest.raises(RuntimeError, match="commit unavailable"):
        await delete_draft(draft_id, 1, None, actor, db_session)
    await db_session.rollback()
    stored = await require_draft(db_session, agency_id=agency_id, draft_id=draft_id)
    assert stored.deleted_at is None and stored.revision == 1
    monkeypatch.setattr(db_session, "commit", real_commit)
    assert (await delete_draft(draft_id, 1, None, actor, db_session)).status_code == 204
    assert not db_session.in_transaction()


async def test_recovery_only_proves_no_send_for_scoped_deleted_saved_message(client, db_session):
    actor, _, _, _, _ = await authored_audience(db_session, device=False)
    other, _, _, _, _ = await authored_audience(db_session, device=False)
    draft, _, request = await reviewed_draft(db_session, actor)
    client._transport.app.dependency_overrides[get_current_active_user] = lambda: actor
    path = f"{_PREFIX}/batches/by-request/{request.request_id}"
    assert (await client.get(path, params={"draft_id": str(draft.id)})).status_code == 404
    assert (
        await client.delete(f"{_PREFIX}/{draft.id}", params={"expected_revision": 1})
    ).status_code == 204
    # Ordinary legacy lookup has no authoritative deletion proof and stays ambiguous.
    assert (await client.get(path)).status_code == 404
    proof = await client.get(path, params={"draft_id": str(draft.id)})
    assert (
        proof.status_code == 410 and proof.json()["detail"] == "notification_deleted_without_send"
    )
    assert (await client.get(path, params={"draft_id": str(uuid.uuid4())})).status_code == 404
    client._transport.app.dependency_overrides[get_current_active_user] = lambda: other
    assert (await client.get(path, params={"draft_id": str(draft.id)})).status_code == 404
