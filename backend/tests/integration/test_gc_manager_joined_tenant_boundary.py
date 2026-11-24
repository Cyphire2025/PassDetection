"""GC directory projections cannot leak a user bound to another agency."""

import uuid

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.infrastructure.database.models import AgencyModel, UserModel
from app.presentation.api.v1.routes.gc_app import router
from tests.integration.test_auth_response_durability import auth_database as auth_database
from tests.integration.test_gc_manager_response_durability import BASE, prepare_manager_command


async def test_client_manager_list_rejects_cross_agency_user_profile_binding(auth_database):
    env = auth_database
    env.app.include_router(router, prefix=BASE)
    _, headers, _ = await prepare_manager_command(env, "reinvite")
    # This historical inconsistency is allowed by the current user-id FK.
    # Mutation lookup already rejects it with a user+profile tenant predicate;
    # the directory must enforce that same boundary when projecting user PII.
    other_id = uuid.uuid4()
    async with env.sessions() as session, session.begin():
        session.add(AgencyModel(id=other_id, name="Other Agency", email="other-agency@example.com"))
        await session.flush()
        manager = await session.scalar(select(UserModel).where(UserModel.role == "client_manager"))
        manager.agency_id = other_id
        manager.full_name = "Other Agency Person"
        manager.email = "other-agency-person@example.com"
    env.gate.release.set()
    async with AsyncClient(
        transport=ASGITransport(app=env.app), base_url="http://testserver"
    ) as client:
        response = await client.get(f"{BASE}/client-managers", headers=headers)
    assert response.status_code == 200
    assert response.json()["total"] == 0
    assert response.json()["items"] == []
    assert "Other Agency Person" not in response.text
    assert "other-agency-person@example.com" not in response.text
