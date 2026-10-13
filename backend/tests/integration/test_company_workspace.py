"""Company context is inferred only when tenant identity is unambiguous."""
from __future__ import annotations

import uuid
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.access import (
    COMPANY_LOOKUP_ROLES,
    company_agency_scope,
    require_company,
    resolve_company_workspace,
)
from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import AuthorizationError, ConflictError, ValidationError
from app.infrastructure.database.models import AgencyModel
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes.companies import router
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.middleware.error_handler import register_exception_handlers


def actor(role: UserRole, agency_id: uuid.UUID | None = None) -> User:
    return User.create(email=f"{uuid.uuid4()}@example.test", hashed_password="synthetic", full_name="Synthetic",
                       role=role, agency_id=agency_id)


async def agency(session: AsyncSession, *, active: bool = True) -> uuid.UUID:
    key = uuid.uuid4()
    session.add(AgencyModel(id=key, name="Synthetic agency", email=f"{key}@example.test", is_active=active))
    await session.flush()
    return key


@pytest.mark.asyncio
@pytest.mark.parametrize("role", COMPANY_LOOKUP_ROLES)
async def test_assigned_active_agency_wins_even_with_multiple_other_tenants(db_session: AsyncSession, role: UserRole) -> None:
    chosen = await agency(db_session)
    await agency(db_session)
    assert await resolve_company_workspace(db_session, user=actor(role, chosen)) == chosen


@pytest.mark.asyncio
@pytest.mark.parametrize("present", [False, True])
async def test_unavailable_assigned_agency_never_falls_back(db_session: AsyncSession, present: bool) -> None:
    chosen = await agency(db_session, active=False) if present else uuid.uuid4()
    await agency(db_session)
    with pytest.raises(ConflictError) as error:
        await resolve_company_workspace(db_session, user=actor(UserRole.SUPER_ADMIN, chosen))
    assert error.value.code == "COMPANY_WORKSPACE_INACTIVE"


@pytest.mark.asyncio
async def test_unbound_superadmin_uses_only_active_agency_and_crud_still_requires_explicit_scope(db_session: AsyncSession) -> None:
    await agency(db_session, active=False)
    chosen = await agency(db_session)
    user = actor(UserRole.SUPER_ADMIN)
    assert await resolve_company_workspace(db_session, user=user) == chosen
    with pytest.raises(ValidationError):
        company_agency_scope(user)
    assert company_agency_scope(user, chosen) == chosen


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 2, 3])
async def test_no_or_multiple_active_agencies_produce_bounded_context_error(db_session: AsyncSession, count: int) -> None:
    for _ in range(count):
        await agency(db_session)
    with pytest.raises(ConflictError) as error:
        await resolve_company_workspace(db_session, user=actor(UserRole.SUPER_ADMIN))
    assert error.value.code == "COMPANY_WORKSPACE_REQUIRED"
    assert "Synthetic agency" not in error.value.message


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER, UserRole.AGENCY_STAFF])
async def test_unbound_agency_accounts_cannot_infer_another_tenant(db_session: AsyncSession, role: UserRole) -> None:
    await agency(db_session)
    with pytest.raises(AuthorizationError):
        await resolve_company_workspace(db_session, user=actor(role))


@pytest.mark.asyncio
async def test_disallowed_role_denied_before_database_access_and_staff_gets_no_company_authority() -> None:
    session = AsyncMock(spec=AsyncSession)
    user = actor(UserRole.AGENCY_COORDINATOR, uuid.uuid4())
    with pytest.raises(AuthorizationError):
        await resolve_company_workspace(session, user=user)
    session.scalar.assert_not_called()
    session.scalars.assert_not_called()
    with pytest.raises(AuthorizationError):
        await require_company(session, user=replace(user, role=UserRole.AGENCY_STAFF), company_id=uuid.uuid4())
    session.scalar.assert_not_called()


@pytest.mark.asyncio
async def test_unbound_resolution_selects_only_ids_with_one_bounded_query(db_session: AsyncSession) -> None:
    await agency(db_session)
    statements: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        await resolve_company_workspace(db_session, user=actor(UserRole.SUPER_ADMIN))
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) == 1
    assert "SELECT agencies.id" in statements[0] and "LIMIT" in statements[0]
    assert "agencies.name" not in statements[0] and "agencies.email" not in statements[0]


@pytest.mark.asyncio
async def test_workspace_http_route_is_not_dynamic_company_id_and_has_private_minimal_response(db_session: AsyncSession) -> None:
    chosen = await agency(db_session)
    user = actor(UserRole.SUPER_ADMIN)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/companies")
    register_exception_handlers(app)
    app.dependency_overrides[get_current_active_user] = lambda: user
    app.dependency_overrides[get_db_session] = lambda: db_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/companies/workspace")
        assert response.status_code == 200
        assert response.json() == {"agency_id": str(chosen)}
        assert response.headers["cache-control"] == "private, no-store"
        await agency(db_session)
        response = await client.get("/api/v1/companies/workspace")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "COMPANY_WORKSPACE_REQUIRED"
        user.role = UserRole.AGENCY_COORDINATOR
        assert (await client.get("/api/v1/companies/workspace")).status_code == 403
