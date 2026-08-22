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
    delete_client_manager,
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


class _ConstraintError(Exception):
    def __init__(self, constraint_name: str) -> None:
        super().__init__(f'constraint "{constraint_name}"')
        self.constraint_name = constraint_name


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
    )


def test_client_manager_schema_rejects_administrator_chosen_passwords() -> None:
    with pytest.raises(ValueError, match="temporary_password|Input should be None"):
        ClientManagerCreateRequest(
            full_name="Client Manager",
            email="manager@example.com",
            phone_number="+919999999999",
            organization_id=uuid.uuid4(),
            temporary_password="AdministratorKnowsThis9",
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
async def test_client_manager_create_returns_single_use_activation_without_refetch() -> None:
    agency_id = uuid.uuid4()
    organization = _organization(agency_id)
    added: list[object] = []
    flush_snapshots: list[tuple[str, ...]] = []

    def record_flush() -> None:
        flush_snapshots.append(tuple(type(item).__name__ for item in added))

    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _Result(organization),
                _Result((False, False)),
                _Result([]),
            ]
        ),
        add=added.append,
        flush=AsyncMock(side_effect=record_flush),
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
    assert created.temporary_password is None
    assert created.activation_token is not None
    assert len(created.activation_token) >= 32
    assert created.status == "invited"
    assert created.force_password_change is False
    assert http_response.headers["Cache-Control"] == "private, no-store, max-age=0"
    assert session.execute.await_count == 3
    assert session.flush.await_count == 2
    assert flush_snapshots == [
        ("UserModel",),
        ("UserModel", "ClientManagerProfileModel"),
    ]
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_client_manager_invitation_stays_pending_without_forced_password() -> None:
    agency_id = uuid.uuid4()
    organization = _organization(agency_id)
    body = _create_body(organization.id)
    added: list[object] = []
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _Result(organization),
                _Result((False, False)),
                _Result([]),
            ]
        ),
        add=added.append,
        flush=AsyncMock(),
        rollback=AsyncMock(),
    )

    with patch("app.presentation.api.v1.routes.gc_app._audit", new=AsyncMock()):
        created = await create_client_manager(
            body=body,
            request=_request(),
            http_response=Response(),
            current_user=_current_user(agency_id),
            session=session,  # type: ignore[arg-type]
        )

    assert created.status == "invited"
    assert created.force_password_change is False
    assert created.activation_token is not None
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_client_manager_create_flushes_foreign_key_dependencies_in_order() -> None:
    agency_id = uuid.uuid4()
    organization = _organization(agency_id)
    group_id = uuid.uuid4()
    access_id = uuid.uuid4()
    body = _create_body(organization.id).model_copy(update={"group_ids": [group_id]})
    added: list[object] = []
    flush_snapshots: list[tuple[str, ...]] = []

    def record_flush() -> None:
        flush_snapshots.append(tuple(type(item).__name__ for item in added))

    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _Result(organization),
                _Result((False, False)),
                _Result([]),
            ]
        ),
        add=added.append,
        flush=AsyncMock(side_effect=record_flush),
        rollback=AsyncMock(),
    )

    with (
        patch(
            "app.presentation.api.v1.routes.gc_app._validate_manager_groups",
            new=AsyncMock(return_value={group_id: SimpleNamespace(id=access_id)}),
        ),
        patch("app.presentation.api.v1.routes.gc_app._audit", new=AsyncMock()),
    ):
        await create_client_manager(
            body=body,
            request=_request(),
            http_response=Response(),
            current_user=_current_user(agency_id),
            session=session,  # type: ignore[arg-type]
        )

    assert flush_snapshots == [
        ("UserModel",),
        ("UserModel", "ClientManagerProfileModel"),
        (
            "UserModel",
            "ClientManagerProfileModel",
            "ClientManagerGroupAssignmentModel",
        ),
    ]
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("constraint_name", "expected_detail"),
    [
        ("users_email_key", "Email is already in use"),
        (
            "uq_client_manager_phone_live",
            "Mobile number is already assigned to another Client Manager",
        ),
    ],
)
async def test_client_manager_unique_race_rolls_back_and_returns_precise_conflict(
    constraint_name: str,
    expected_detail: str,
) -> None:
    agency_id = uuid.uuid4()
    organization = _organization(agency_id)
    session = SimpleNamespace(
        execute=AsyncMock(side_effect=[_Result(organization), _Result((False, False))]),
        add=lambda _item: None,
        flush=AsyncMock(
            side_effect=(
                [
                    IntegrityError(
                        "insert",
                        {},
                        _ConstraintError(constraint_name),
                    )
                ]
                if constraint_name == "users_email_key"
                else [
                    None,
                    IntegrityError(
                        "insert",
                        {},
                        _ConstraintError(constraint_name),
                    ),
                ]
            )
        ),
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
    assert exc_info.value.detail == expected_detail
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_client_manager_unrelated_integrity_failure_is_not_reported_as_duplicate() -> None:
    agency_id = uuid.uuid4()
    organization = _organization(agency_id)
    original_error = IntegrityError(
        "insert",
        {},
        _ConstraintError("ck_client_manager_profile_state_shape"),
    )
    session = SimpleNamespace(
        execute=AsyncMock(side_effect=[_Result(organization), _Result((False, False))]),
        add=lambda _item: None,
        flush=AsyncMock(side_effect=[None, original_error]),
        rollback=AsyncMock(),
    )

    with pytest.raises(IntegrityError) as exc_info:
        await create_client_manager(
            body=_create_body(organization.id),
            request=_request(),
            http_response=Response(),
            current_user=_current_user(agency_id),
            session=session,  # type: ignore[arg-type]
        )

    assert exc_info.value is original_error
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_client_manager_delete_revokes_access_and_releases_the_email() -> None:
    agency_id = uuid.uuid4()
    profile_id = uuid.uuid4()
    user_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    profile = SimpleNamespace(
        id=profile_id,
        status="active",
        deleted_at=None,
        access_generation=3,
        revision=6,
        invitation_token_hash="old-token",
        invitation_expires_at=now,
        updated_by_user_id=None,
        updated_at=now,
    )
    user = SimpleNamespace(
        id=user_id,
        email="manager@example.com",
        is_active=True,
        hashed_password="old-hash",
        deleted_at=None,
        updated_at=now,
    )
    session = SimpleNamespace(execute=AsyncMock())
    revoke_sessions = AsyncMock()

    with (
        patch(
            "app.presentation.api.v1.routes.gc_app._get_client_manager",
            new=AsyncMock(return_value=(profile, user, SimpleNamespace())),
        ),
        patch(
            "app.presentation.api.v1.routes.gc_app._revoke_mobile_sessions",
            new=revoke_sessions,
        ),
        patch("app.presentation.api.v1.routes.gc_app.hash_password", return_value="revoked-hash"),
        patch("app.presentation.api.v1.routes.gc_app._audit", new=AsyncMock()),
    ):
        response = await delete_client_manager(
            profile_id=profile_id,
            request=_request(),
            agency_id=None,
            current_user=_current_user(agency_id),
            session=session,  # type: ignore[arg-type]
        )

    assert response.status_code == 204
    assert profile.status == "deleted"
    assert profile.access_generation == 4
    assert profile.revision == 7
    assert profile.invitation_token_hash is None
    assert user.is_active is False
    assert user.email == f"deleted-{user_id}@deleted.invalid"
    assert user.hashed_password == "revoked-hash"
    revoke_sessions.assert_awaited_once_with(
        session,
        agency_id,
        user_id,
        "account_deleted",
    )
