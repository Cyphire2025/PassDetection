from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, Response
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request

from app.domain.entities.entities import UserRole
from app.presentation.api.v1.routes.gc_app import (
    create_client_manager,
    list_client_managers,
)
from app.presentation.api.v1.schemas.gc_app_schemas import ClientManagerCreateRequest


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


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": []})


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
        name="Enterprise Client",
        status="active",
        created_at=now,
        updated_at=now,
    )


def _create_body(organization_id: uuid.UUID) -> ClientManagerCreateRequest:
    return ClientManagerCreateRequest(
        full_name="Client Manager",
        email="manager@example.com",
        phone_number="+919999999999",
        organization_id=organization_id,
        group_ids=[],
        temporary_password="SecurePass1!",
        return_temporary_password_once=True,
        invitation_flow=False,
        force_password_change=True,
    )


@pytest.mark.asyncio
async def test_client_manager_list_applies_status_company_and_phone_search() -> None:
    agency_id = uuid.uuid4()
    company_id = uuid.uuid4()
    session = SimpleNamespace(
        execute=AsyncMock(side_effect=[_Result(0), _Result([])]),
    )

    response = await list_client_managers(
        q="+91 999",
        account_status="active",
        company_id=company_id,
        agency_id=None,
        offset=0,
        limit=20,
        current_user=_current_user(agency_id),
        session=session,  # type: ignore[arg-type]
    )

    assert response.total == 0
    assert session.execute.await_count == 2
    sql = str(
        session.execute.await_args_list[0].args[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert str(agency_id) in sql
    assert str(company_id) in sql
    assert "client_manager_profiles.status = 'active'" in sql
    assert "client_manager_profiles.normalized_phone_number ILIKE" in sql
    assert "91999" in sql
    assert "client_manager_profiles.deleted_at IS NULL" in sql


@pytest.mark.asyncio
async def test_client_manager_list_can_return_deleted_audit_records() -> None:
    agency_id = uuid.uuid4()
    session = SimpleNamespace(execute=AsyncMock(side_effect=[_Result(0), _Result([])]))

    await list_client_managers(
        q=None,
        account_status="deleted",
        company_id=None,
        agency_id=None,
        offset=0,
        limit=20,
        current_user=_current_user(agency_id),
        session=session,  # type: ignore[arg-type]
    )

    sql = str(
        session.execute.await_args_list[0].args[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "client_manager_profiles.deleted_at IS NOT NULL" in sql
    assert "client_manager_profiles.status = 'deleted'" in sql


@pytest.mark.asyncio
async def test_client_manager_duplicate_phone_is_a_safe_conflict_before_writes() -> None:
    agency_id = uuid.uuid4()
    organization = _organization(agency_id)
    session = SimpleNamespace(
        execute=AsyncMock(side_effect=[_Result(organization), _Result((False, True))]),
        add_all=lambda _items: None,
        flush=AsyncMock(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await create_client_manager(
            body=_create_body(organization.id),
            request=_request(),
            http_response=Response(),
            current_user=_current_user(agency_id),
            session=session,  # type: ignore[arg-type]
        )

    assert exc_info.value.status_code == 409
    assert "Mobile number" in str(exc_info.value.detail)
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_client_manager_create_returns_once_without_waiting_for_a_refetch() -> None:
    agency_id = uuid.uuid4()
    organization = _organization(agency_id)
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _Result(organization),
                _Result((False, False)),
                _Result([]),
            ]
        ),
        add_all=lambda _items: None,
        add=lambda _item: None,
        flush=AsyncMock(),
        rollback=AsyncMock(),
    )
    http_response = Response()

    with patch("app.presentation.api.v1.routes.gc_app._audit", new=AsyncMock()):
        created = await create_client_manager(
            body=_create_body(organization.id),
            request=_request(),
            http_response=http_response,
            current_user=_current_user(agency_id),
            session=session,  # type: ignore[arg-type]
        )

    assert created.email == "manager@example.com"
    assert created.phone_number == "+919999999999"
    assert created.temporary_password == "SecurePass1!"
    assert http_response.headers["Cache-Control"] == "private, no-store, max-age=0"
    assert session.execute.await_count == 3
    assert session.flush.await_count == 2
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_client_manager_unique_race_rolls_back_and_returns_conflict() -> None:
    agency_id = uuid.uuid4()
    organization = _organization(agency_id)
    session = SimpleNamespace(
        execute=AsyncMock(side_effect=[_Result(organization), _Result((False, False))]),
        add_all=lambda _items: None,
        flush=AsyncMock(side_effect=IntegrityError("insert", {}, Exception("unique"))),
        rollback=AsyncMock(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await create_client_manager(
            body=_create_body(organization.id),
            request=_request(),
            http_response=Response(),
            current_user=_current_user(agency_id),
            session=session,  # type: ignore[arg-type]
        )

    assert exc_info.value.status_code == 409
    assert "email or mobile number" in str(exc_info.value.detail)
    session.rollback.assert_awaited_once()
