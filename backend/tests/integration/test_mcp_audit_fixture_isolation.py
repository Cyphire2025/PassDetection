"""Old HTTP fixtures persist denials without touching the global/business session."""

import uuid

import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.infrastructure.database.models import AuditLogModel, UserModel
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.mcp.management_audit import MCPManagementAuditRoute
from tests.integration.test_mcp_authorization import consent
from tests.integration.test_mcp_authorization import mcp_fixture as mcp_fixture


async def rejection_audits(client, business):
    factory = client._transport.app.state.mcp_management_audit_session_factory
    async with factory() as audit:
        assert audit is not business and audit.bind is not business.bind
        assert (await AuditLogRepository(audit).verify_chain(None)).valid
        return list(await audit.scalars(select(AuditLogModel)))


async def test_shared_client_denial_has_independent_audit_and_preserves_rollback(client, db_session):
    user_id = uuid.uuid4()
    db_session.add(UserModel(id=user_id, email="pending@example.test", full_name="Uncommitted",
                             hashed_password="fixture", role="super_admin", is_active=True))
    await db_session.flush()
    response = await client.get("/api/v1/admin/mcp")
    assert response.status_code == 401
    await db_session.rollback()
    assert await db_session.get(UserModel, user_id) is None
    audits = await rejection_audits(client, db_session)
    assert len(audits) == 1 and audits[0].action == "mcp.management_rejected"
    assert audits[0].metadata_json == {
        "operation": "overview", "reason": "authentication_required", "http_status": 401,
    }


async def test_old_mcp_fixture_denial_does_not_commit_pending_business_data(mcp_fixture):
    client, business, _, user, _, dashboard = mcp_fixture
    await business.commit()
    user_id, original_name = user.id, user.full_name
    user.full_name = "Rejected request must not commit this"
    await AuditLogRepository(business).record(action="must_not_commit", entity_type="fixture")
    await business.flush()
    response = await client.post("/api/v1/admin/mcp/authorize",
                                headers={"Authorization": f"Bearer {dashboard}"},
                                json={**consent(), "client_id": "unapproved-fixture-client"})
    assert response.status_code == 400
    await business.rollback()
    assert (await business.get(UserModel, user_id)).full_name == original_name
    assert await business.scalar(select(func.count()).select_from(AuditLogModel).where(
        AuditLogModel.action == "must_not_commit")) == 0
    audits = await rejection_audits(client, business)
    assert len(audits) == 1 and audits[0].user_id == user_id
    assert audits[0].metadata_json == {
        "operation": "authorize", "reason": "invalid_request", "http_status": 400,
    }


async def test_unbound_app_fails_before_global_audit_session_can_open():
    app = FastAPI()
    router = APIRouter(route_class=MCPManagementAuditRoute)

    @router.get("/overview")
    async def overview():
        raise HTTPException(403, "denied")

    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with pytest.raises(pytest.fail.Exception, match="Bind an isolated"):
            await client.get("/overview")
