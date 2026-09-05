from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.gc_mobile_models import ClientOrganizationModel, GCGroupAccessModel
from app.infrastructure.database.models import AgencyModel, ClientGroupModel, UserModel
from app.presentation.api.v1.routes.gc_app_group_access_support import group_access_response


@pytest.mark.asyncio
async def test_group_control_context_executes_with_an_explicit_join_origin(
    db_session: AsyncSession,
) -> None:
    agency = AgencyModel(id=uuid.uuid4(), name="Synthetic control agency", email="agency@example.test")
    owner = UserModel(
        id=uuid.uuid4(), email="control@example.test", full_name="QA Owner",
        hashed_password="unused-fixture-hash", role="super_admin", agency_id=agency.id,
    )
    db_session.add_all([agency, owner])
    await db_session.flush()
    group = ClientGroupModel(
        id=uuid.uuid4(), agency_id=agency.id, created_by_user_id=owner.id,
        name="QA control group", token="synthetic-group-control-query", status="active",
    )
    organization = ClientOrganizationModel(
        id=uuid.uuid4(), agency_id=agency.id, name="QA organization",
        normalized_name="qa organization", status="active",
    )
    db_session.add_all([group, organization])
    await db_session.flush()
    access = GCGroupAccessModel(
        id=uuid.uuid4(), agency_id=agency.id, group_id=group.id,
        client_organization_id=organization.id, is_enabled=False,
    )
    db_session.add(access)
    await db_session.flush()

    result = await group_access_response(db_session, access)

    assert result.group_id == group.id
    assert result.client_organization_id == organization.id
    assert result.name == "QA control group"
    assert result.my_photos_enabled is False
    assert result.active_mobile_users == 0
    assert result.synced_device_count == 0
