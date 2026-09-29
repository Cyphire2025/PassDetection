"""Independent committed denial audits; no existing authorization fixtures changed."""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.domain.exceptions.exceptions import (
    AuthenticationError,
    AuthorizationError,
    StepUpRequiredError,
)
from app.infrastructure.database.models import AuditLogModel, Base, UserModel
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.mcp import management_audit
from app.presentation.mcp.management_audit import MCPManagementAuditRoute
from tests.dashboard_session_fixtures import issue_dashboard_access
from tests.integration.test_mcp_authorization import connect, consent
from tests.integration.test_mcp_authorization import mcp_fixture as mcp_fixture

SECRET = "opaque-secret-state-code-token-and-private-person@example.test"


@pytest.fixture
async def audit_database(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'audit.sqlite'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(UserModel(id=user_id, email="audit-fixture@example.test", full_name="Fixture",
                              hashed_password="unused", role="super_admin", is_active=True))
        await session.commit()
    yield factory, user_id
    await engine.dispose()


def audit_app(factory):
    app = FastAPI()
    app.state.mcp_management_audit_session_factory = factory
    router = APIRouter(route_class=MCPManagementAuditRoute)
    return app, router


async def audits(factory):
    async with factory() as session:
        rows = list((await session.scalars(select(AuditLogModel))).all())
        assert (await AuditLogRepository(session).verify_chain(None)).valid
        return rows


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422, 429, 500, 503])
async def test_error_responses_keep_body_status_and_headers_without_retaining_input(audit_database, status):
    factory, user_id = audit_database
    app, router = audit_app(factory)
    connection_id = uuid.uuid4()

    @router.patch("/connections/{connection_id}")
    async def update_connection(request: Request):
        request.state.auth_claims = {"sub": str(user_id), "private": SECRET}
        return JSONResponse({"error": SECRET}, status_code=status, headers={"Cache-Control": "no-store"})

    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.patch(f"/connections/{connection_id}?state={SECRET}",
                                      headers={"Authorization": f"Bearer {SECRET}"}, json={"name": SECRET})
    assert response.status_code == status
    assert response.json() == {"error": SECRET}
    assert response.headers["cache-control"] == "no-store"
    rows = await audits(factory)
    assert len(rows) == 1
    row = rows[0]
    assert row.action == "mcp.management_rejected"
    assert row.user_id == user_id and row.entity_id == str(connection_id)
    assert row.metadata_json["operation"] == "update_connection"
    assert row.metadata_json["http_status"] == status
    assert row.result == ("failed" if status >= 500 else "denied" if status in {401, 403} else "blocked")
    assert row.actor_email is None and row.ip_address is None
    assert SECRET not in json.dumps(row.metadata_json)


@pytest.mark.asyncio
@pytest.mark.parametrize("error,status,reason", [
    (StepUpRequiredError(), 403, "recent_mfa_required"),
    (AuthenticationError(SECRET), 401, "authentication_required"),
    (AuthorizationError(SECRET), 403, "access_denied"),
    (HTTPException(403, SECRET), 403, "access_denied"),
    (RequestValidationError([{"input": SECRET}], body={"code": SECRET}), 422, "invalid_request"),
])
async def test_dependency_denials_preserve_exception_and_commit_safe_audit(audit_database, error, status, reason):
    factory, _ = audit_database
    app, router = audit_app(factory)
    observed = []

    async def reject():
        raise error

    @router.post("/authorize", dependencies=[Depends(reject)])
    async def authorize():
        pytest.fail("Denied authorization reached its handler")

    async def handler(_request, caught):
        observed.append(caught)
        return JSONResponse({"unchanged": True}, status_code=status)

    app.add_exception_handler(type(error), handler)
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/authorize", json={"code": SECRET})
    assert response.status_code == status and response.json() == {"unchanged": True}
    assert observed == [error]
    rows = await audits(factory)
    assert len(rows) == 1
    assert rows[0].metadata_json == {"operation": "authorize", "reason": reason, "http_status": status}
    assert rows[0].user_id is None and rows[0].entity_id is None


@pytest.mark.asyncio
async def test_request_rollback_finishes_before_independent_audit_commit(audit_database):
    factory, user_id = audit_database
    order = []

    @asynccontextmanager
    async def separate_audit():
        order.append("audit_open")
        async with factory() as session:
            yield session
        order.append("audit_closed")

    app, router = audit_app(separate_audit)

    async def business_session():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                order.append("request_rolled_back")
                raise

    @router.put("/control")
    async def control(request: Request, session=Depends(business_session)):
        request.state.auth_claims = {"sub": str(user_id)}
        user = await session.get(UserModel, user_id)
        user.full_name = "must-not-commit"
        await AuditLogRepository(session).record(action="must_not_commit", entity_type="fixture")
        raise HTTPException(409, SECRET)

    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.put("/control")).status_code == 409
    assert order == ["request_rolled_back", "audit_open", "audit_closed"]
    async with factory() as session:
        assert (await session.get(UserModel, user_id)).full_name == "Fixture"
    rows = await audits(factory)
    assert len(rows) == 1 and rows[0].action == "mcp.management_rejected"
    assert rows[0].entity_type == "mcp_control"


@pytest.mark.asyncio
async def test_unexpected_failure_records_only_fixed_reason_then_reraises(audit_database):
    factory, _ = audit_database
    app, router = audit_app(factory)
    failure = RuntimeError(SECRET)

    @router.post("/authorize")
    async def authorize():
        raise failure

    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with pytest.raises(RuntimeError) as raised:
            await client.post("/authorize")
    assert raised.value is failure
    rows = await audits(factory)
    assert len(rows) == 1 and rows[0].result == "failed"
    assert rows[0].metadata_json == {"operation": "authorize", "reason": "operation_failed", "http_status": 500}


@pytest.mark.asyncio
async def test_audit_failure_preserves_denial_and_emits_no_exception_contents(monkeypatch):
    @asynccontextmanager
    async def unavailable():
        raise RuntimeError(SECRET)
        yield  # pragma: no cover

    app, router = audit_app(unavailable)
    events = []
    monkeypatch.setattr(management_audit.logger, "error", lambda event, **fields: events.append((event, fields)))

    @router.post("/authorize")
    async def authorize():
        raise HTTPException(403, "unchanged")

    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/authorize")
    assert response.status_code == 403 and response.json() == {"detail": "unchanged"}
    assert events == [("mcp_management_audit_unavailable", {"operation": "authorize"})]


@pytest.mark.asyncio
async def test_success_and_unregistered_routes_do_not_gain_failure_audits(audit_database):
    factory, _ = audit_database
    app, router = audit_app(factory)

    @router.post("/authorize")
    async def authorize():
        return {"success": True}

    @router.post("/unrelated")
    async def unrelated():
        raise HTTPException(409, SECRET)

    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/authorize")).status_code == 200
        assert (await client.post("/unrelated")).status_code == 409
    assert await audits(factory) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("case,status,operation,reason", [
    ("client", 400, "authorize", "invalid_request"),
    ("resource", 400, "authorize", "invalid_request"),
    ("disabled_deployment", 409, "control", "state_conflict"),
    ("missing_revoke", 404, "revoke", "record_unavailable"),
    ("missing_update", 404, "update_connection", "record_unavailable"),
    ("expansion", 409, "update_connection", "state_conflict"),
    ("stale_mfa", 403, "authorize", "recent_mfa_required"),
    ("csrf", 403, "authorize", "access_denied"),
    ("invalid_id", 422, "revoke", "invalid_request"),
    ("invalid_body", 422, "authorize", "invalid_request"),
    ("role", 403, "artifacts", "access_denied"),
])
async def test_actual_management_failures_are_durably_audited_without_credentials(
    mcp_fixture, audit_database, case, status, operation, reason,
):
    client, business, settings, user, _, dashboard = mcp_fixture
    factory, _ = audit_database
    app = client._transport.app
    app.state.mcp_management_audit_session_factory = factory
    async with factory() as session:
        session.add(UserModel(id=user.id, email="second-audit-fixture@example.test", full_name="Fixture",
                             hashed_password="unused", role="super_admin", is_active=True))
        await session.commit()
    headers = {"Authorization": f"Bearer {dashboard}"}
    method, path, body = "POST", "/authorize", {**consent(), "name": SECRET}
    if case in {"client", "resource"}:
        body["client_id" if case == "client" else "resource"] = SECRET
    elif case == "disabled_deployment":
        settings.mcp.enabled = False
        method, path, body = "PUT", "/control", {"enabled": True}
    elif case in {"missing_revoke", "missing_update", "invalid_id"}:
        connection = SECRET if case == "invalid_id" else str(uuid.uuid4())
        path = f"/connections/{connection}"
        if case == "missing_update":
            method, body = "PATCH", {"name": SECRET, "capabilities": ["mcp:read"]}
        else:
            path += "/revoke"
    elif case == "expansion":
        from app.infrastructure.database.mcp_models import MCPGrantModel
        await connect(mcp_fixture, scopes=["mcp:read"])
        grant = await business.scalar(select(MCPGrantModel))
        method, path, body = "PATCH", f"/connections/{grant.id}", {"name": SECRET, "capabilities": ["mcp:export"]}
    elif case == "stale_mfa":
        stale, _ = await issue_dashboard_access(
            business, user.id, "super_admin", session_version=1,
            authentication_methods=("pwd", "totp"),
            mfa_authenticated_at=datetime.now(UTC) - timedelta(minutes=11),
        )
        headers = {"Authorization": f"Bearer {stale}"}
    elif case == "csrf":
        client.cookies.set("access_token", dashboard)
        headers = {"Origin": "https://attacker.example"}
    elif case == "invalid_body":
        body["scopes"] = [SECRET]
    elif case == "role":
        user.role = "agency_staff"
        await business.flush()
        method, path, body = "GET", "/artifacts", None
    response = await client.request(method, "/api/v1/admin/mcp" + path, headers=headers, json=body)
    assert response.status_code == status
    rows = await audits(factory)
    assert len(rows) == 1 and rows[0].action == "mcp.management_rejected"
    assert rows[0].metadata_json == {"operation": operation, "reason": reason, "http_status": status}
    assert SECRET not in json.dumps(rows[0].metadata_json)
    assert dashboard not in json.dumps(rows[0].metadata_json)
    assert rows[0].actor_email is None and rows[0].ip_address is None


@pytest.mark.asyncio
@pytest.mark.parametrize("path,body,method,action", [
    ("/control", {"enabled": True}, "PUT", "mcp.control_changed"),
    ("/authorize", consent(), "POST", "mcp.authorized"),
])
async def test_actual_success_keeps_one_existing_audit_and_no_rejection(
    mcp_fixture, audit_database, path, body, method, action,
):
    client, business, _, _, _, dashboard = mcp_fixture
    factory, _ = audit_database
    client._transport.app.state.mcp_management_audit_session_factory = factory
    response = await client.request(method, "/api/v1/admin/mcp" + path,
                                    headers={"Authorization": f"Bearer {dashboard}"}, json=body)
    assert response.status_code == 200
    existing = list((await business.scalars(select(AuditLogModel).where(AuditLogModel.action == action))).all())
    assert len(existing) == 1 and existing[0].result == "success"
    assert await audits(factory) == []
