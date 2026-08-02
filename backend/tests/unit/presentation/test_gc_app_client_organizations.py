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
    delete_client_organization,
    list_client_organizations,
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
