from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql
from starlette.requests import Request

from app.domain.entities.entities import UserRole
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


def _organization(agency_id: uuid.UUID) -> SimpleNamespace:
    now = datetime.now(tz=UTC)
    return SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=agency_id,
        status="active",
        deleted_at=None,
        updated_by_user_id=None,
        updated_at=now,
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
    assert "client_groups.status = 'active'" in statements[0]
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
    )
    organization = SimpleNamespace(id=uuid.uuid4(), name="Bluechip")
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
async def test_removed_organization_name_can_be_created_again() -> None:
    agency_id = uuid.uuid4()
    session = SimpleNamespace(
        execute=AsyncMock(return_value=_Result(None)),
        add=lambda _item: None,
        flush=AsyncMock(),
    )

    with patch(
        "app.presentation.api.v1.routes.gc_app._audit",
        new=AsyncMock(),
    ):
        response = await create_client_organization(
            body=ClientOrganizationCreateRequest(name="BLUECHIP"),
            request=_request(),
            current_user=_current_user(agency_id),
            session=session,  # type: ignore[arg-type]
        )

    assert response.name == "BLUECHIP"
    duplicate_lookup = session.execute.await_args.args[0]
    sql = str(
        duplicate_lookup.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "client_organizations.normalized_name = 'bluechip'" in sql
    assert "client_organizations.status != 'deleted'" in sql


@pytest.mark.asyncio
async def test_unused_client_organization_is_soft_deleted_and_audited() -> None:
    agency_id = uuid.uuid4()
    organization = _organization(agency_id)
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[_Result(organization), _Result(0), _Result(0)]
        ),
        flush=AsyncMock(),
    )

    with patch(
        "app.presentation.api.v1.routes.gc_app._audit",
        new=AsyncMock(),
    ) as audit:
        response = await delete_client_organization(
            organization_id=organization.id,
            request=_request(),
            current_user=_current_user(agency_id),
            session=session,  # type: ignore[arg-type]
        )

    assert response.status_code == 204
    assert organization.status == "deleted"
    assert organization.deleted_at is not None
    session.flush.assert_awaited_once()
    audit.assert_awaited_once()

    organization_lookup = session.execute.await_args_list[0].args[0]
    sql = str(
        organization_lookup.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert str(agency_id) in sql
    assert str(organization.id) in sql
    assert "client_organizations.status = 'active'" in sql


@pytest.mark.asyncio
async def test_client_organization_removal_is_blocked_while_in_use() -> None:
    agency_id = uuid.uuid4()
    organization = _organization(agency_id)
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[_Result(organization), _Result(2), _Result(1)]
        ),
        flush=AsyncMock(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await delete_client_organization(
            organization_id=organization.id,
            request=_request(),
            current_user=_current_user(agency_id),
            session=session,  # type: ignore[arg-type]
        )

    assert exc_info.value.status_code == 409
    assert "2 enabled GC App groups" in str(exc_info.value.detail)
    assert "1 Client Manager account" in str(exc_info.value.detail)
    assert organization.status == "active"
    assert organization.deleted_at is None
    session.flush.assert_not_awaited()
