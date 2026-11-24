"""Company changes retain grant history without breaking current relational scopes."""

import uuid
from datetime import UTC, datetime, timedelta

from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select, text

from app.infrastructure.database.gc_mobile_models import (
    ClientManagerGroupAssignmentModel as Assignment,
)
from app.infrastructure.database.gc_mobile_models import (
    ClientManagerProfileModel as Profile,
)
from app.infrastructure.database.gc_mobile_models import (
    ClientOrganizationModel as Organization,
)
from app.infrastructure.database.gc_mobile_models import (
    GCGroupAccessModel as Access,
)
from app.infrastructure.database.models import ClientGroupModel as Group
from app.presentation.api.v1.routes.gc_app import router
from tests.integration.test_auth_response_durability import auth_database as auth_database
from tests.integration.test_gc_manager_response_durability import BASE, prepare_manager_command


async def enable_fk(env):
    engine = env.sessions.kw["bind"]

    @event.listens_for(engine.sync_engine, "connect")
    def configure(connection, _record):
        cursor = connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    async with engine.connect() as connection:
        await connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        assert await connection.scalar(text("PRAGMA foreign_keys")) == 1


async def group_access(session, profile):
    group = Group(
        id=uuid.uuid4(),
        agency_id=profile.agency_id,
        company_id=profile.organization_id,
        name="Synthetic retained trip",
        token=uuid.uuid4().hex,
        status="closed",
    )
    session.add(group)
    await session.flush()
    access = Access(
        id=uuid.uuid4(),
        agency_id=profile.agency_id,
        group_id=group.id,
        client_organization_id=profile.organization_id,
        is_enabled=True,
        client_manager_access_enabled=True,
    )
    session.add(access)
    await session.flush()
    return group, access


async def test_company_change_detaches_active_and_historical_grant_scope(auth_database):
    env = auth_database
    await enable_fk(env)
    env.app.include_router(router, prefix=BASE)
    _, headers, _ = await prepare_manager_command(env, "reinvite")
    old_revoked_at = datetime.now(UTC) - timedelta(days=1)
    async with env.sessions() as session, session.begin():
        profile = await session.scalar(select(Profile))
        profile_id, prior_revoker_id = profile.id, profile.user_id
        next_company = Organization(
            id=uuid.uuid4(),
            agency_id=profile.agency_id,
            name="Next Company",
            normalized_name="next company",
            status="active",
        )
        session.add(next_company)
        for active in (True, False):
            group, access = await group_access(session, profile)
            session.add(
                Assignment(
                    id=uuid.uuid4(),
                    agency_id=profile.agency_id,
                    organization_id=profile.organization_id,
                    profile_id=profile.id,
                    group_id=group.id,
                    gc_group_access_id=access.id,
                    is_active=active,
                    revoked_at=None if active else old_revoked_at,
                    revoked_by_user_id=None if active else prior_revoker_id,
                )
            )
        next_id = next_company.id
    env.gate.release.set()
    async with AsyncClient(
        transport=ASGITransport(app=env.app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        response = await client.patch(
            f"{BASE}/client-managers/{profile_id}",
            headers=headers,
            json={"organization_id": str(next_id), "expected_revision": 1},
        )
    assert response.status_code == 200
    assert response.json()["organization_id"] == str(next_id)
    async with env.sessions() as session:
        grants = list(await session.scalars(select(Assignment).order_by(Assignment.revoked_at)))
        assert len(grants) == 2
        assert all(not grant.is_active and grant.organization_id is None for grant in grants)
        assert grants[0].revoked_at.replace(tzinfo=UTC) == old_revoked_at
        assert grants[0].revoked_by_user_id == prior_revoker_id
        assert grants[1].revoked_by_user_id not in {None, prior_revoker_id}


async def test_readding_retained_grant_rebinds_scope_without_old_privacy_grants(auth_database):
    env = auth_database
    await enable_fk(env)
    env.app.include_router(router, prefix=BASE)
    _, headers, _ = await prepare_manager_command(env, "reinvite")
    async with env.sessions() as session, session.begin():
        profile = await session.scalar(select(Profile))
        profile_id, company_id = profile.id, profile.organization_id
        group, access = await group_access(session, profile)
        group_id = group.id
        grant = Assignment(
            id=uuid.uuid4(),
            agency_id=profile.agency_id,
            organization_id=None,
            profile_id=profile.id,
            group_id=group.id,
            gc_group_access_id=access.id,
            is_active=False,
            revoked_at=datetime.now(UTC) - timedelta(days=1),
            can_view_passenger_names=True,
            personal_document_access_enabled=True,
        )
        session.add(grant)
        grant_id = grant.id
    env.gate.release.set()
    async with AsyncClient(
        transport=ASGITransport(app=env.app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        response = await client.put(
            f"{BASE}/client-managers/{profile_id}/groups",
            headers=headers,
            json={"group_ids": [str(group_id)], "expected_revision": 1},
        )
    assert response.status_code == 200
    async with env.sessions() as session:
        saved = await session.get(Assignment, grant_id)
        assert saved.is_active and saved.organization_id == company_id
        assert saved.revoked_at is None
        assert not saved.can_view_passenger_names
        assert not saved.personal_document_access_enabled
