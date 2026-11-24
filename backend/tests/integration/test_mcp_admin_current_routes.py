"""Actual dashboard control and bounded management projection contracts."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel, MCPTokenModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import AuditLogModel
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from tests.integration.test_mcp_authorization import call_mcp, connect
from tests.integration.test_mcp_authorization import mcp_fixture as mcp_fixture


async def test_dashboard_pause_and_resume_retains_existing_credentials_and_chained_audits(
    mcp_fixture,
):
    client, session, _, _, _, dashboard = mcp_fixture
    _, tokens = await connect(mcp_fixture)
    grant = await session.scalar(select(MCPGrantModel))
    original = (grant.id, list(grant.capabilities), grant.revoked_at)
    headers = {"Authorization": f"Bearer {dashboard}"}
    paused = await client.put("/api/v1/admin/mcp/control", json={"enabled": False}, headers=headers)
    assert paused.status_code == 200 and paused.json() == {"enabled": False}
    assert (await call_mcp(client, tokens["access_token"])).status_code == 401
    resumed = await client.put("/api/v1/admin/mcp/control", json={"enabled": True}, headers=headers)
    assert resumed.status_code == 200 and resumed.json() == {"enabled": True}
    assert (await call_mcp(client, tokens["access_token"])).status_code == 200
    await session.refresh(grant)
    assert (grant.id, grant.capabilities, grant.revoked_at) == original
    assert await session.scalar(select(func.count()).select_from(MCPTokenModel)) == 2
    audits = list(
        await session.scalars(
            select(AuditLogModel).where(
                AuditLogModel.action == "mcp.control_changed",
            )
        )
    )
    assert len(audits) == 2 and sorted(row.metadata_json["enabled"] for row in audits) == [
        False,
        True,
    ]
    assert (await AuditLogRepository(session).verify_chain(None)).valid


@pytest.mark.parametrize("boundary", ["deployment_disabled", "missing_control"])
async def test_control_rejection_does_not_create_or_enable_authority(mcp_fixture, boundary):
    client, session, settings, _, _, dashboard = mcp_fixture
    if boundary == "deployment_disabled":
        settings.mcp.enabled = False
        expected = 409
    else:
        await session.delete(await session.get(MCPControlModel, 1))
        await session.commit()
        expected = 503
    response = await client.put(
        "/api/v1/admin/mcp/control",
        json={"enabled": True},
        headers={"Authorization": f"Bearer {dashboard}"},
    )
    assert response.status_code == expected
    assert await session.scalar(select(func.count()).select_from(MCPGrantModel)) == 0
    assert (
        await session.scalar(
            select(func.count())
            .select_from(AuditLogModel)
            .where(
                AuditLogModel.action == "mcp.control_changed",
            )
        )
        == 0
    )


async def test_activity_search_is_literal_paginated_and_never_returns_private_metadata(mcp_fixture):
    client, session, _, user, _, dashboard = mcp_fixture
    for action in ["mcp.literal%activity", "mcp.literal%activity", "mcp.literalXactivity"]:
        await AuditLogRepository(session).record(
            action=action,
            entity_type="synthetic",
            user_id=user.id,
            metadata={"private_note": "synthetic-private-contact"},
        )
    await session.commit()
    headers = {"Authorization": f"Bearer {dashboard}"}
    first = await client.get(
        "/api/v1/admin/mcp/activity?search=literal%25&limit=1", headers=headers
    )
    second = await client.get(
        "/api/v1/admin/mcp/activity?search=literal%25&limit=1&offset=1", headers=headers
    )
    assert first.status_code == second.status_code == 200
    one, two = first.json(), second.json()
    assert one["next_offset"] == 1 and two["next_offset"] is None
    assert len(one["items"]) == len(two["items"]) == 1
    assert one["items"][0]["id"] != two["items"][0]["id"]
    for response in [first, second]:
        row = response.json()["items"][0]
        assert row["action"] == "mcp.literal%activity"
        assert set(row) == {"id", "action", "result", "entity_id", "created_at"}
        assert (
            "private_note" not in response.text and "synthetic-private-contact" not in response.text
        )


async def test_operations_projection_is_paginated_without_returning_stored_private_result(
    mcp_fixture,
):
    client, session, _, user, _, dashboard = mcp_fixture
    await connect(mcp_fixture)
    grant = await session.scalar(select(MCPGrantModel))
    now = datetime.now(UTC)
    identifiers = []
    for index in range(2):
        identifier = uuid.uuid4()
        identifiers.append(identifier)
        session.add(
            MCPOperationModel(
                id=identifier,
                user_id=user.id,
                initial_grant_id=grant.id,
                operation_name="retained-projection-proof",
                capability="mcp:read",
                idempotency_hash=str(index) * 64,
                payload_hash="d" * 64,
                initial_result={"private_note": "synthetic-private-payload"},
                workflow_id=uuid.uuid4(),
                status="succeeded",
                progress=1,
                stage="completed",
                revision=1,
                created_entities=[],
                created_at=now - timedelta(minutes=index),
                updated_at=now,
                completed_at=now,
            )
        )
    await session.commit()
    headers = {"Authorization": f"Bearer {dashboard}"}
    first = await client.get("/api/v1/admin/mcp/operations?limit=1", headers=headers)
    second = await client.get("/api/v1/admin/mcp/operations?limit=1&offset=1", headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json()["next_offset"] == 1 and second.json()["next_offset"] is None
    assert [response.json()["items"][0]["id"] for response in [first, second]] == list(
        map(str, identifiers)
    )
    for response in [first, second]:
        row = response.json()["items"][0]
        assert row["connection_id"] == str(grant.id) and row["created_entities"] == []
        assert "initial_result" not in row and "synthetic-private-payload" not in response.text


@pytest.mark.parametrize("operation", ["revoke", "update"])
async def test_unknown_connection_mutations_return_not_found_without_success_audit(
    mcp_fixture,
    operation,
):
    client, session, _, _, _, dashboard = mcp_fixture
    identifier = uuid.uuid4()
    path = f"/api/v1/admin/mcp/connections/{identifier}"
    arguments = {"headers": {"Authorization": f"Bearer {dashboard}"}}
    response = (
        await client.post(path + "/revoke", **arguments)
        if operation == "revoke"
        else await client.patch(
            path,
            json={"name": "Synthetic nonexistent", "capabilities": ["mcp:read"]},
            **arguments,
        )
    )
    assert response.status_code == 404 and response.json()["detail"] == "Connection not found"
    assert await session.scalar(select(func.count()).select_from(MCPGrantModel)) == 0
    assert (
        await session.scalar(
            select(func.count())
            .select_from(AuditLogModel)
            .where(
                AuditLogModel.action.in_(["mcp.revoked", "mcp.connection_changed"]),
            )
        )
        == 0
    )
