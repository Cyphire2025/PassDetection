"""HTTP contract, role/tenant boundaries and exact reviewed-send recovery."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.domain.entities.entities import UserRole
from app.infrastructure.database.gc_notification_models import GCNotificationBatchModel
from app.presentation.dependencies.auth import get_current_active_user
from tests.authored_notification_fixtures import authored_audience

pytestmark = pytest.mark.asyncio
_PREFIX = "/api/v1/gc-app/admin/notifications"


async def test_draft_review_explicit_send_history_and_request_recovery_http(client, db_session):
    actor, accesses, _, _, _ = await authored_audience(db_session)
    client._transport.app.dependency_overrides[get_current_active_user] = lambda: actor
    response = await client.post(
        _PREFIX,
        json={
            "title": "Lobby",
            "body": "Meet downstairs.",
            "audience": "selected_groups",
            "group_ids": [str(access.group_id) for access in accesses],
        },
    )
    assert response.status_code == 201, response.text
    draft = response.json()
    assert draft["status"] == "draft" and len(draft["group_names"]) == 2
    restored = (await client.get(f"{_PREFIX}/{draft['id']}")).json()
    for key in ("created_at", "updated_at"):
        assert datetime.fromisoformat(restored.pop(key)).replace(
            tzinfo=UTC
        ) == datetime.fromisoformat(draft[key])
    assert restored == {
        key: value for key, value in draft.items() if key not in {"created_at", "updated_at"}
    }
    saved = (await client.get(_PREFIX, params={"limit": 1})).json()
    assert saved["items"][0]["id"] == draft["id"] and saved["next_cursor"] is None
    preview = await client.post(f"{_PREFIX}/{draft['id']}/preview", json={"expected_revision": 1})
    assert preview.status_code == 200, preview.text
    assert preview.json()["recipient_count"] == 2
    assert await db_session.scalar(select(func.count()).select_from(GCNotificationBatchModel)) == 0
    request_id = str(uuid.uuid4())
    body = {
        "expected_revision": 1,
        "preview_token": preview.json()["preview_token"],
        "request_id": request_id,
    }
    sent = await client.post(f"{_PREFIX}/{draft['id']}/send", json=body)
    assert sent.status_code == 202, sent.text
    assert sent.json()["recipient_counts"]["queued"] == 2
    assert (await client.post(f"{_PREFIX}/{draft['id']}/send", json=body)).json()[
        "id"
    ] == sent.json()["id"]
    assert (await client.get(f"{_PREFIX}/batches/by-request/{request_id}")).json()[
        "id"
    ] == sent.json()["id"]
    assert (await client.get(f"{_PREFIX}/batches/{sent.json()['id']}")).status_code == 200
    history = await client.get(f"{_PREFIX}/batches", params={"limit": 1})
    assert history.status_code == 200 and history.json()["items"][0]["id"] == sent.json()["id"]


@pytest.mark.parametrize(
    "role", [UserRole.AGENCY_STAFF, UserRole.AGENCY_COORDINATOR, UserRole.CLIENT_MANAGER]
)
async def test_non_operator_cannot_use_authored_admin_routes(client, db_session, role):
    actor, _, _, _, _ = await authored_audience(db_session, device=False)
    actor.role = role
    client._transport.app.dependency_overrides[get_current_active_user] = lambda: actor
    response = await client.get(_PREFIX)
    assert response.status_code == 403


async def test_cross_tenant_draft_group_and_idempotency_lookup_do_not_leak(client, db_session):
    actor, _, _, _, _ = await authored_audience(db_session, device=False)
    other_actor, other_accesses, _, _, _ = await authored_audience(db_session, device=False)
    client._transport.app.dependency_overrides[get_current_active_user] = lambda: actor
    foreign = await client.post(
        _PREFIX,
        json={
            "title": "Title",
            "body": "Body",
            "audience": "selected_groups",
            "group_ids": [str(other_accesses[0].group_id)],
        },
    )
    assert foreign.status_code == 422
    mismatch = await client.get(_PREFIX, params={"agency_id": str(other_actor.agency_id)})
    assert mismatch.status_code == 403
    draft = (
        await client.post(
            _PREFIX, json={"title": "Title", "body": "Body", "audience": "all_active_trips"}
        )
    ).json()
    client._transport.app.dependency_overrides[get_current_active_user] = lambda: other_actor
    assert (await client.get(f"{_PREFIX}/{draft['id']}")).status_code == 404
    assert (await client.get(f"{_PREFIX}/batches/by-request/{uuid.uuid4()}")).status_code == 404


async def test_super_admin_requires_explicit_tenant_and_schema_rejects_bypass_fields(
    client, db_session
):
    actor, _, _, _, _ = await authored_audience(db_session, device=False)
    actor.role = UserRole.SUPER_ADMIN
    client._transport.app.dependency_overrides[get_current_active_user] = lambda: actor
    assert (await client.get(_PREFIX)).status_code == 422
    assert (
        await client.get(_PREFIX, params={"agency_id": str(actor.agency_id)})
    ).status_code == 200
    response = await client.post(
        _PREFIX,
        params={"agency_id": str(actor.agency_id)},
        json={"title": "Title", "body": "Body", "audience": "all_active_trips", "send_now": True},
    )
    assert response.status_code == 422


async def test_cookie_authenticated_send_enforces_existing_csrf_origin(client, db_session):
    from app.core.config.settings import get_settings

    actor, _, _, _, _ = await authored_audience(db_session, device=False)
    client._transport.app.dependency_overrides[get_current_active_user] = lambda: actor
    client.cookies.set(get_settings().jwt.access_cookie_name, "synthetic-session-cookie")
    response = await client.post(
        _PREFIX,
        headers={"origin": "https://untrusted.example"},
        json={"title": "Title", "body": "Body", "audience": "all_active_trips"},
    )
    assert response.status_code == 403


async def test_send_route_commits_batch_before_returning_accepted_response(db_session):
    from app.presentation.api.v1.routes.gc_notifications import send_draft
    from tests.authored_notification_fixtures import reviewed_draft

    actor, _, _, _, _ = await authored_audience(db_session, device=False)
    draft, _, request = await reviewed_draft(db_session, actor)
    await db_session.commit()
    response = await send_draft(draft.id, request, None, actor, db_session)
    assert not db_session.in_transaction()
    assert response.request_id == request.request_id and response.recipient_counts.queued == 2
    assert await db_session.scalar(select(func.count()).select_from(GCNotificationBatchModel)) == 1


async def test_send_route_commit_failure_cannot_return_success_and_retry_is_safe(
    db_session, monkeypatch
):
    from unittest.mock import AsyncMock

    from app.presentation.api.v1.routes.gc_notifications import send_draft
    from tests.authored_notification_fixtures import reviewed_draft

    actor, _, _, _, _ = await authored_audience(db_session, device=False)
    draft, _, request = await reviewed_draft(db_session, actor)
    draft_id = draft.id
    await db_session.commit()
    actual_commit = db_session.commit
    monkeypatch.setattr(
        db_session, "commit", AsyncMock(side_effect=RuntimeError("synthetic commit unavailable"))
    )
    with pytest.raises(RuntimeError, match="synthetic commit unavailable"):
        await send_draft(draft_id, request, None, actor, db_session)
    # This is the rollback performed by get_db_session on the raised error.
    await db_session.rollback()
    assert await db_session.scalar(select(func.count()).select_from(GCNotificationBatchModel)) == 0
    monkeypatch.setattr(db_session, "commit", actual_commit)
    response = await send_draft(draft_id, request, None, actor, db_session)
    assert response.request_id == request.request_id
    assert not db_session.in_transaction()
