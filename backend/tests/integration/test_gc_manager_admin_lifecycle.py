"""Exercise scoped manager administration through real HTTP and transactions."""

import uuid
from datetime import UTC, datetime, timedelta

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.infrastructure.database.gc_mobile_models import (
    ClientManagerGroupAssignmentModel as Assignment,
)
from app.infrastructure.database.gc_mobile_models import (
    ClientManagerProfileModel as Profile,
)
from app.infrastructure.database.models import AuditLogModel, UserModel
from app.presentation.api.v1.routes.gc_app import router
from tests.integration.test_auth_response_durability import auth_database as auth_database
from tests.integration.test_gc_manager_response_durability import BASE, prepare_manager_command
from tests.integration.test_gc_manager_retained_assignments import enable_fk, group_access


async def test_manager_profile_assignment_and_session_lifecycle(auth_database):
    env = auth_database
    await enable_fk(env)
    env.app.include_router(router, prefix=BASE)
    _, headers, _ = await prepare_manager_command(env, "reinvite")
    async with env.sessions() as session, session.begin():
        profile = await session.scalar(select(Profile))
        profile_id, user_id = profile.id, profile.user_id
        first, first_access = await group_access(session, profile)
        second, _ = await group_access(session, profile)
        first_id, second_id = first.id, second.id
        session.add(
            Assignment(
                id=uuid.uuid4(),
                agency_id=profile.agency_id,
                organization_id=profile.organization_id,
                profile_id=profile.id,
                group_id=first.id,
                gc_group_access_id=first_access.id,
                is_active=False,
                revoked_at=datetime.now(UTC) - timedelta(days=1),
                can_view_passenger_names=True,
                personal_document_access_enabled=True,
            )
        )
    env.gate.release.set()
    path = f"{BASE}/client-managers/{profile_id}"
    async with AsyncClient(
        transport=ASGITransport(app=env.app), base_url="http://testserver", headers=headers
    ) as client:
        assigned = await client.put(
            path + "/groups",
            json={
                "group_ids": [str(first_id), str(second_id), str(first_id)],
                "expected_revision": 1,
            },
        )
        assert assigned.status_code == 200
        assert {item["id"] for item in assigned.json()["assigned_groups"]} == {
            str(first_id),
            str(second_id),
        }
        async with env.sessions() as session:
            retained = await session.scalar(
                select(Assignment).where(Assignment.group_id == first_id)
            )
            assert retained.can_view_passenger_names and retained.personal_document_access_enabled
        stale = await client.put(path + "/groups", json={"group_ids": [], "expected_revision": 1})
        assert stale.status_code == 409
        invalid = await client.patch(path, json={"phone_number": "invalid", "expected_revision": 2})
        assert invalid.status_code == 422
        updated = await client.patch(
            path,
            json={
                "full_name": "  Changed   Manager ",
                "email": "changed-manager@example.com",
                "phone_number": "+919999000002",
                "expected_revision": 2,
            },
        )
        assert updated.status_code == 200
        assert updated.json()["full_name"] == "Changed Manager"
        assert updated.json()["phone_number"] == "+919999000002"
        removed = await client.put(
            path + "/groups", json={"group_ids": [str(second_id)], "expected_revision": 3}
        )
        assert removed.status_code == 200
        assert [item["id"] for item in removed.json()["assigned_groups"]] == [str(second_id)]
        for revision, status in ((4, "suspended"), (5, "active")):
            changed = await client.patch(
                path + "/status", json={"status": status, "expected_revision": revision}
            )
            assert changed.status_code == 200
            assert changed.json()["status"] == status
        compatibility = await client.patch(
            path + "/force-password-change",
            json={"force_password_change": True, "expected_revision": 6},
        )
        assert compatibility.status_code == 200
        assert compatibility.json()["force_password_change"] is False
        revoked = await client.post(path + "/revoke-sessions")
        assert revoked.status_code == 204
        deleted = await client.delete(path)
        assert deleted.status_code == 204
    async with env.sessions() as session:
        saved = await session.get(Profile, profile_id)
        user = await session.get(UserModel, user_id)
        assert saved.status == "deleted" and saved.deleted_at is not None
        assert saved.revision == 9 and saved.access_generation == 8
        assert not user.is_active and user.email == f"deleted-{user_id}@deleted.invalid"
        grants = list(await session.scalars(select(Assignment)))
        assert len(grants) == 2 and all(
            not item.is_active and item.revoked_at is not None for item in grants
        )
        actions = list(await session.scalars(select(AuditLogModel.action)))
        assert "gc_app.client_manager_deleted" in actions
        assert actions.count("gc_app.client_manager_groups_replaced") == 2
