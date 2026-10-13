from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from starlette.requests import Request

from app.domain.entities.entities import UserRole
from app.domain.exceptions.exceptions import ConflictError
from app.infrastructure.database.gc_mobile_models import (
    ClientManagerProfileModel,
    ClientOrganizationModel,
)
from app.infrastructure.database.models import AuditLogModel, ClientGroupModel, UserModel
from app.presentation.api.v1.routes.gc_app import (
    _group_access_response,
    create_client_organization,
    delete_client_organization,
    list_client_organizations,
    search_client_organizations,
    search_gc_groups,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    ClientOrganizationCreateRequest,
    GCGroupAccessUpdateRequest,
)
from tests.integration.test_company_directory import company, seed_user


class _Result:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object | None:
        return self._value

    def scalar_one(self) -> object:
        return self._value

    def scalars(self) -> _Result:
        return self

    def all(self):  # type: ignore[no-untyped-def]
        return self._value

    def one(self):  # type: ignore[no-untyped-def]
        return self._value

    def first(self):  # type: ignore[no-untyped-def]
        return self._value

    def __iter__(self):  # type: ignore[no-untyped-def]
        if isinstance(self._value, list):
            return iter(self._value)
        return iter([self._value])


def _request() -> Request:
    return Request({"type": "http", "method": "DELETE", "path": "/", "headers": []})


def _current_user(agency_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        email="gc-admin@example.test",
        role=UserRole.AGENCY_ADMIN,
        agency_id=agency_id,
    )


def test_new_gc_group_access_enables_all_mobile_roles_by_default() -> None:
    request = GCGroupAccessUpdateRequest(
        client_organization_id=uuid.uuid4(),
        enabled=True,
    )

    assert request.passenger_access_enabled is True
    assert request.client_manager_access_enabled is True
    assert request.coordinator_access_enabled is True


def test_gc_group_access_can_still_explicitly_disable_roles() -> None:
    request = GCGroupAccessUpdateRequest(
        client_organization_id=uuid.uuid4(),
        enabled=True,
        passenger_access_enabled=False,
        client_manager_access_enabled=False,
        coordinator_access_enabled=False,
    )

    assert request.passenger_access_enabled is False
    assert request.client_manager_access_enabled is False
    assert request.coordinator_access_enabled is False


@pytest.mark.asyncio
async def test_client_organization_directory_excludes_removed_records() -> None:
    agency_id = uuid.uuid4()
    session = SimpleNamespace(execute=AsyncMock(return_value=_Result([])))

    response = await list_client_organizations(
        current_user=_current_user(agency_id),
        session=session,  # type: ignore[arg-type]
    )

    assert response == []
    statement = session.execute.await_args.args[0]
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert str(agency_id) in sql
    assert "client_organizations.status = 'active'" in sql


@pytest.mark.asyncio
async def test_client_organization_search_is_server_bounded_and_tenant_scoped() -> None:
    agency_id = uuid.uuid4()
    session = SimpleNamespace(
        execute=AsyncMock(side_effect=[_Result(250), _Result([])])
    )

    response = await search_client_organizations(
        q="  Blue Chip  ",
        agency_id=None,
        offset=100,
        limit=50,
        current_user=_current_user(agency_id),
        session=session,  # type: ignore[arg-type]
    )

    assert response.total == 250
    assert response.offset == 100
    assert response.limit == 50
    statements = [
        str(
            call.args[0].compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        for call in session.execute.await_args_list
    ]
    assert all(str(agency_id) in statement for statement in statements)
    assert all("client_organizations.status = 'active'" in statement for statement in statements)
    assert "client_organizations.name ILIKE" in statements[0]
    assert "Blue Chip" in statements[0]
    assert "LIMIT 50 OFFSET 100" in statements[1]


@pytest.mark.asyncio
async def test_eligible_group_search_filters_before_pagination_and_searches_destination() -> None:
    agency_id = uuid.uuid4()
    session = SimpleNamespace(
        execute=AsyncMock(side_effect=[_Result(125), _Result([])])
    )

    response = await search_gc_groups(
        q="  Viet Nam  ",
        agency_id=None,
        group_id=None,
        gc_enabled=None,
        eligible_only=True,
        lifecycle_status=None,
        offset=40,
        limit=20,
        current_user=_current_user(agency_id),
        session=session,  # type: ignore[arg-type]
    )

    assert response.total == 125
    assert response.offset == 40
    assert response.limit == 20
    statements = [
        str(
            call.args[0].compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        for call in session.execute.await_args_list
    ]
    assert all(str(agency_id) in statement for statement in statements)
    assert "client_groups.name ILIKE" in statements[0]
    assert "client_groups.destination ILIKE" in statements[0]
    assert "client_groups.status IN ('active', 'closed')" in statements[0]
    assert "client_groups.deleted_at IS NULL" in statements[0]
    assert "gc_group_access.id IS NULL" in statements[0]
    assert "LIMIT 20 OFFSET 40" in statements[1]


@pytest.mark.asyncio
async def test_enabled_group_page_embeds_aggregated_usage_metrics() -> None:
    agency_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    group = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=agency_id,
        name="Enterprise Group",
        destination="Vietnam",
        travel_date=None,
        return_date=None,
        status="active",
        deleted_at=None,
    )
    organization = SimpleNamespace(id=uuid.uuid4(), name="Bluechip")
    group.company_id = organization.id
    access = SimpleNamespace(
        id=uuid.uuid4(),
        client_organization_id=organization.id,
        is_enabled=True,
        passenger_access_enabled=True,
        client_manager_access_enabled=True,
        coordinator_access_enabled=True,
        access_starts_at=None,
        access_expires_at=None,
        revoked_at=None,
        removed_at=None,
        access_generation=1,
        itinerary_version=2,
        common_document_version=3,
        announcement_version=4,
        revision=5,
        last_successful_sync_at=now,
        updated_at=now,
    )
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[_Result(1), _Result([(group, access, organization, 2, 3)])]
        )
    )

    response = await search_gc_groups(
        q=None,
        agency_id=None,
        group_id=None,
        gc_enabled=True,
        eligible_only=False,
        lifecycle_status=None,
        offset=0,
        limit=20,
        current_user=_current_user(agency_id),
        session=session,  # type: ignore[arg-type]
    )

    assert len(response.items) == 1
    assert response.items[0].access is not None
    assert response.items[0].access.active_mobile_users == 2
    assert response.items[0].access.synced_device_count == 3
    page_statement = session.execute.await_args_list[1].args[0]
    page_sql = str(
        page_statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "count(distinct(mobile_device_sessions.account_id))" in page_sql
    assert "last_sync_acknowledged_at IS NOT NULL" in page_sql


@pytest.mark.asyncio
async def test_group_metrics_distinguish_accounts_from_acknowledged_devices() -> None:
    agency_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    access = SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=agency_id,
        group_id=uuid.uuid4(),
        client_organization_id=uuid.uuid4(),
        is_enabled=True,
        passenger_access_enabled=True,
        client_manager_access_enabled=True,
        coordinator_access_enabled=True,
        access_starts_at=None,
        access_expires_at=None,
        revoked_at=None,
        removed_at=None,
        access_generation=1,
        itinerary_version=1,
        common_document_version=2,
        announcement_version=3,
        revision=4,
        last_successful_sync_at=now,
        updated_at=now,
    )
    group = SimpleNamespace(
        id=access.group_id,
        agency_id=agency_id,
        name="Enterprise Group",
        destination="Vietnam",
        travel_date=None,
        return_date=None,
        status="active",
        deleted_at=None,
    )
    organization = SimpleNamespace(id=access.client_organization_id, name="Bluechip")
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[_Result((2, 3)), _Result((group, organization, False))]
        )
    )

    response = await _group_access_response(session, access)  # type: ignore[arg-type]

    assert response.active_mobile_users == 2
    assert response.synced_device_count == 3
    assert response.my_photos_enabled is False
    metrics_statement = session.execute.await_args_list[0].args[0]
    metrics_sql = str(
        metrics_statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "count(distinct(mobile_device_sessions.account_id))" in metrics_sql
    assert "last_sync_acknowledged_at IS NOT NULL" in metrics_sql
    assert "mobile_device_sessions.expires_at >" in metrics_sql


@pytest.mark.asyncio
async def test_removed_organization_name_can_be_created_again(db_session) -> None:
    user = await seed_user(db_session)
    original = await company(db_session, user, "Bluechip")
    await delete_client_organization(
        organization_id=original.id, request=_request(), current_user=user, session=db_session,
    )
    response = await create_client_organization(
        body=ClientOrganizationCreateRequest(name="BLUECHIP"), request=_request(),
        current_user=user, session=db_session,
    )
    await db_session.commit()
    assert response.name == "BLUECHIP" and response.id != original.id
    current = await db_session.get(ClientOrganizationModel, response.id)
    assert current.normalized_name == "bluechip" and current.status == "active"
    assert original.status == "deleted" and original.deleted_at is not None


@pytest.mark.asyncio
async def test_unused_client_organization_is_soft_deleted_and_audited(db_session) -> None:
    user = await seed_user(db_session)
    organization = await company(db_session, user)
    response = await delete_client_organization(
        organization_id=organization.id, request=_request(), current_user=user, session=db_session,
    )
    await db_session.commit()
    assert response.status_code == 204
    assert organization.status == "deleted" and organization.deleted_at is not None
    assert organization.revision == 2 and organization.updated_by_user_id == user.id
    audit = (await db_session.scalars(select(AuditLogModel).where(
        AuditLogModel.entity_id == str(organization.id), AuditLogModel.action == "company.deleted",
    ))).one()
    assert audit.agency_id == user.agency_id and audit.user_id == user.id
    assert audit.metadata_json == {"status": "deleted", "revision": 2}


@pytest.mark.asyncio
@pytest.mark.parametrize("dependency", ["active", "closed", "archived", "manager"])
async def test_client_organization_removal_is_blocked_while_in_use(db_session, dependency) -> None:
    user = await seed_user(db_session)
    organization = await company(db_session, user)
    if dependency == "manager":
        manager = UserModel(
            id=uuid.uuid4(), agency_id=user.agency_id, email="manager@example.test",
            full_name="Synthetic manager", hashed_password="test-only", role=UserRole.CLIENT_MANAGER.value,
        )
        db_session.add(manager)
        await db_session.flush()
        db_session.add(ClientManagerProfileModel(
            id=uuid.uuid4(), user_id=manager.id, agency_id=user.agency_id,
            organization_id=organization.id, normalized_phone_number="+919999999981", status="invited",
        ))
    else:
        db_session.add(ClientGroupModel(
            id=uuid.uuid4(), agency_id=user.agency_id, company_id=organization.id,
            name="Synthetic group", token=uuid.uuid4().hex, status=dependency,
        ))
    await db_session.commit()
    with pytest.raises(ConflictError, match="history and cannot be deleted"):
        await delete_client_organization(
            organization_id=organization.id, request=_request(), current_user=user, session=db_session,
        )
    assert organization.status == "active" and organization.deleted_at is None
    assert organization.revision == 1
    assert await db_session.scalar(select(AuditLogModel.id).where(
        AuditLogModel.entity_id == str(organization.id), AuditLogModel.action == "company.deleted",
    )) is None
