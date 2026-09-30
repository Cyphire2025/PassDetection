"""Actual OAuth and MCP SDK HTTP boundary for personal notifications."""

import json
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, update

from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import AuditLogModel, NotificationModel
from app.infrastructure.repositories.notification_projection_repository import (
    NotificationProjectionRepository,
)
from tests.integration.test_mcp_authorization import call_mcp, connect
from tests.integration.test_mcp_authorization import mcp_fixture as mcp_fixture
from tests.mcp_notification_fixtures import seed_notifications


@pytest.fixture
async def notifications(mcp_fixture):
    data = await seed_notifications(mcp_fixture[1], mcp_fixture[3].id)
    await mcp_fixture[1].commit()
    return mcp_fixture, data


def body(response):
    assert response.status_code == 200, response.text
    return response.json()["result"]["structuredContent"]


async def test_oauth_read_then_explicit_ack_and_response_loss_replay(notifications):
    f, data = notifications
    _, tokens = await connect(f, scopes=["mcp:read", "mcp:change"])
    feed = body(await call_mcp(f[0], tokens["access_token"], name="list_my_notifications"))
    assert len(feed["items"]) == 3 and feed["unread_count"] == 2
    assert {"observed_at", "audit_id", "environment", "revision"} <= feed.keys()
    assert await f[1].scalar(select(func.count()).select_from(MCPOperationModel)) == 0
    args = {"notification_id": str(data.rows[0].id), "idempotency_key": "http-personal-ack-001"}
    ack = body(await call_mcp(f[0], tokens["access_token"], name="acknowledge_my_notification", arguments=args))
    replay = body(await call_mcp(f[0], tokens["access_token"], name="acknowledge_my_notification", arguments=args))
    assert ack["receipt"] == replay["receipt"] and ack["audit_id"] != replay["audit_id"]
    assert ack["receipt"]["data"]["changed"] is True
    after = body(await call_mcp(f[0], tokens["access_token"], name="list_my_notifications"))
    assert after["unread_count"] == 1
    assert "PRIVATE-NOTIFICATION-SENTINEL" not in json.dumps([feed, ack, replay, after])


async def test_read_grant_cannot_ack_and_error_does_not_expose_contents(notifications):
    f, data = notifications
    identifier = data.rows[0].id
    _, tokens = await connect(f, scopes=["mcp:read"])
    result = body(await call_mcp(f[0], tokens["access_token"], name="acknowledge_my_notification",
        arguments={"notification_id": str(identifier), "idempotency_key": "denied-personal-ack-001"}))
    assert result["completeness"] == "unavailable" and "receipt" not in result
    assert await f[1].scalar(select(func.count()).select_from(MCPOperationModel)) == 0
    assert not await f[1].scalar(select(NotificationModel.is_read).where(NotificationModel.id == identifier))


async def test_limit_error_is_static_audited_and_has_no_partial_page(notifications):
    f, data = notifications
    _, tokens = await connect(f, scopes=["mcp:read"])
    await f[1].execute(update(NotificationModel).where(NotificationModel.id == data.rows[2].id)
        .values(message="SECRET-OVERSIZE" * 500))
    await f[1].commit()
    result = body(await call_mcp(f[0], tokens["access_token"], name="list_my_notifications"))
    assert result["error"] == "notification_limit" and result["completeness"] == "unavailable"
    assert "items" not in result and "SECRET-OVERSIZE" not in json.dumps(result)
    audit = await f[1].get(AuditLogModel, uuid.UUID(result["audit_id"]))
    assert audit.result == "blocked" and "SECRET" not in json.dumps(audit.metadata_json)


async def test_foreign_ack_is_static_and_leaves_no_operation(notifications):
    f, data = notifications
    _, tokens = await connect(f, scopes=["mcp:change"])
    result = body(await call_mcp(f[0], tokens["access_token"], name="acknowledge_my_notification",
        arguments={"notification_id": str(data.rows[3].id), "idempotency_key": "foreign-personal-ack-001"}))
    assert result["error"] == "notification_unavailable" and result["completeness"] == "unavailable"
    assert "receipt" not in result and "Synthetic notification" not in json.dumps(result)
    assert await f[1].scalar(select(func.count()).select_from(MCPOperationModel)) == 0


@pytest.mark.parametrize("restriction", ["revoked", "capability", "deployment", "role", "inactive", "deleted", "session", "control"])
async def test_current_authority_denies_before_projection(notifications, monkeypatch, restriction):
    f, _ = notifications
    _, tokens = await connect(f, scopes=["mcp:read"])
    grant = await f[1].scalar(select(MCPGrantModel))
    if restriction == "revoked":
        grant.revoked_at = datetime.now(UTC)
    elif restriction == "capability":
        grant.capabilities = ["mcp:export"]
    elif restriction == "deployment":
        f[2].mcp.enabled_capabilities = ["mcp:export"]
    elif restriction == "role":
        f[3].role = "agency_staff"
    elif restriction == "inactive":
        f[3].is_active = False
    elif restriction == "deleted":
        f[3].deleted_at = datetime.now(UTC)
    elif restriction == "session":
        f[4].session_version += 1
    else:
        (await f[1].get(MCPControlModel, 1)).enabled = False
    await f[1].commit()
    async def forbidden(*args, **kwargs):
        raise AssertionError("Unauthorized notification source read")
    monkeypatch.setattr(NotificationProjectionRepository, "page", forbidden)
    response = await call_mcp(f[0], tokens["access_token"], name="list_my_notifications")
    if response.status_code != 401:
        assert body(response)["completeness"] == "unavailable"
    assert await f[1].scalar(select(func.count()).select_from(MCPOperationModel)) == 0
