"""Website parity, scalar privacy and the actual authenticated MCP HTTP read."""

import asyncio
import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import event, func, select

from app.application.mcp import retention_reads
from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.credentials import MCPAuthError, utc
from app.application.mcp.retention_reads import MCPPassportRetentionReadService, RetentionReadError
from app.application.use_cases.group_passport_retention import PassportRetentionSchedule
from app.domain.entities.entities import UserRole
from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    AuditLogModel,
    ClientGroupModel,
    StorageCleanupJobModel,
)
from app.infrastructure.repositories.passport_retention_repository import (
    PassportRetentionRepository,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.routes import admin
from tests.integration.test_mcp_authorization import call_mcp, connect
from tests.integration.test_mcp_authorization import mcp_fixture as mcp_fixture
from tests.integration.test_mcp_operations import operations_fixture as operations_fixture
from tests.mcp_retention_fixtures import seed_retention_schedules


def principal(f):
    grant = f[3][0]
    return MCPPrincipal(
        grant.id,
        f[2].id,
        grant.client_id,
        tuple(grant.capabilities),
        grant.expires_at,
        grant.resource,
    )


@pytest.fixture
async def schedules(operations_fixture):
    f = operations_fixture
    data = await seed_retention_schedules(f[0], f[2])
    f[3][0].capabilities = ["mcp:read"]
    await f[0].commit()
    return f, data


@pytest.fixture
async def retention_http(mcp_fixture):
    f = mcp_fixture
    data = await seed_retention_schedules(f[1], f[3])
    await f[1].commit()
    return f, data


@pytest.fixture(autouse=True)
def forbid_files_and_cleanup(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Retention read attempted file or cleanup work")

    monkeypatch.setattr(MinioStorageRepository, "__init__", forbidden)
    monkeypatch.setattr(admin, "stage_storage_cleanup_jobs", forbidden)
    monkeypatch.setattr(admin, "process_storage_cleanup_job", forbidden)
    # The actual MCP tests use ASGITransport; intercept only outgoing provider
    # transports, so synthetic HTTP requests continue to exercise the real app.
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)


async def test_all_retained_groups_null_past_future_and_crossagency_match_website(schedules):
    f, data = schedules
    actor = await UserRepository(f[0]).get_by_id(f[2].id)
    assert actor.agency_id is None and data.agencies[0].is_active is False
    for group in data.groups:
        website = await admin.get_group_passport_retention(group.id, actor, f[0])
        result = await MCPPassportRetentionReadService(f[0], f[1]).get_schedule(
            principal(f), group_id=group.id
        )
        assert result["group_id"] == str(website.group_id) == str(group.id)
        assert result["agency_id"] == str(group.agency_id)
        assert result["passport_purge_at"] == (
            utc(website.passport_purge_at).isoformat() if website.passport_purge_at else None
        )
        assert result["passport_retention_days_applied"] == website.passport_retention_days_applied
        assert result["scope"] == "explicit_group" and result["completeness"] == "complete"
        assert "does not prove" in result["notice"]
        assert "SECRET" not in json.dumps(result) and "PRIVATE" not in json.dumps(result)
        assert (
            group.passport_legal_hold is True
            and group.passport_legal_hold_reason == "SECRET_RETIRED_HOLD"
        )
    assert await f[0].scalar(select(func.count()).select_from(StorageCleanupJobModel)) == 0
    assert await f[0].scalar(select(func.count()).select_from(MCPOperationModel)) == 0


async def test_website_agencyadmin_own_null_crossagency_and_missing_are_exact(schedules):
    f, data = schedules
    actor = await UserRepository(f[0]).get_by_id(f[2].id)
    actor.role, actor.agency_id = UserRole.AGENCY_ADMIN, data.agencies[0].id
    for group in data.groups[:4]:
        assert (
            await admin.get_group_passport_retention(group.id, actor, f[0])
        ).group_id == group.id
    for group_id in (data.groups[-1].id, uuid.uuid4()):
        with pytest.raises(HTTPException) as denied:
            await admin.get_group_passport_retention(group_id, actor, f[0])
        assert (
            denied.value.status_code == 404 and denied.value.detail == "Client group was not found"
        )
    actor.agency_id = None
    with pytest.raises(HTTPException) as denied:
        await admin.get_group_passport_retention(data.groups[0].id, actor, f[0])
    assert denied.value.status_code == 404


async def test_four_scalars_without_private_group_hydration_or_business_writes(schedules):
    f, data = schedules
    current, group_id = principal(f), data.groups[0].id
    f[0].expire_all()
    statements = []

    def capture(_connection, _cursor, sql, *_args):
        statements.append(sql.lower())

    def forbidden(*_args):
        raise AssertionError("Private group ORM hydration")

    engine = f[0].bind.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    event.listen(ClientGroupModel, "load", forbidden)
    event.listen(ClientGroupModel, "refresh", forbidden)
    try:
        await MCPPassportRetentionReadService(f[0], f[1]).get_schedule(current, group_id=group_id)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
        event.remove(ClientGroupModel, "load", forbidden)
        event.remove(ClientGroupModel, "refresh", forbidden)
    groups = [sql for sql in statements if "from client_groups" in sql]
    assert len(groups) == 1 and len(statements) == 4
    projection = groups[0].split("\nfrom")[0]
    assert all(
        field in projection
        for field in ("id", "agency_id", "passport_purge_at", "passport_retention_days_applied")
    )
    assert not any(
        field in projection for field in ("notes", "name", "token", "legal_hold", "settings")
    )
    assert not any(sql.startswith(("insert", "update", "delete")) for sql in statements)


@pytest.mark.parametrize("invalid", [None, "not-a-uuid", True, 1])
async def test_invalid_internal_group_is_static(schedules, invalid):
    f, _ = schedules
    with pytest.raises(RetentionReadError, match="retention_invalid_group"):
        await MCPPassportRetentionReadService(f[0], f[1]).get_schedule(
            principal(f), group_id=invalid
        )


@pytest.mark.parametrize("days", [0, 3651, True, "30"])
async def test_invalid_retained_day_projection_fails_whole_read(schedules, monkeypatch, days):
    f, data = schedules
    group = data.groups[0]
    monkeypatch.setattr(
        PassportRetentionRepository,
        "get_schedule",
        AsyncMock(return_value=PassportRetentionSchedule(group.id, group.agency_id, None, days)),
    )
    with pytest.raises(RetentionReadError, match="retention_read_limit"):
        await MCPPassportRetentionReadService(f[0], f[1]).get_schedule(
            principal(f), group_id=group.id
        )


async def test_foreign_actor_missing_group_whole_envelope_and_deadline(schedules, monkeypatch):
    f, data = schedules
    current, group_id = principal(f), data.groups[0].id
    service = MCPPassportRetentionReadService(f[0], f[1])
    with pytest.raises(MCPAuthError):
        await service.get_schedule(replace(current, user_id=uuid.uuid4()), group_id=group_id)
    with pytest.raises(RetentionReadError, match="retention_schedule_unavailable"):
        await service.get_schedule(current, group_id=uuid.uuid4())
    result = await service.get_schedule(current, group_id=group_id)
    monkeypatch.setattr(
        retention_reads, "MAX_RETENTION_RESPONSE_BYTES", len(json.dumps(result).encode()) + 1
    )
    with pytest.raises(RetentionReadError, match="retention_read_limit"):
        await service.get_schedule(current, group_id=group_id)
    monkeypatch.setattr(retention_reads, "MAX_RETENTION_RESPONSE_BYTES", 8192)
    monkeypatch.setattr(retention_reads, "RETENTION_READ_TIMEOUT_SECONDS", 0.01)

    async def slow(*_args, **_kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(PassportRetentionRepository, "get_schedule", slow)
    with pytest.raises(RetentionReadError, match="retention_read_busy"):
        await service.get_schedule(current, group_id=group_id)


def body(response):
    assert response.status_code == 200
    return response.json()["result"]["structuredContent"]


async def test_real_http_parity_read_scope_annotations_and_safe_audit(retention_http):
    f, data = retention_http
    _, tokens = await connect(f, scopes=["mcp:read"])
    group_id = data.groups[-1].id
    web = await f[0].get(
        f"/api/v1/admin/groups/{group_id}/passport-retention",
        headers={"Authorization": f"Bearer {f[5]}"},
    )
    assert web.status_code == 200 and set(web.json()) == {
        "group_id",
        "passport_purge_at",
        "passport_retention_days_applied",
    }
    result = body(
        await call_mcp(
            f[0],
            tokens["access_token"],
            name="get_group_passport_retention",
            arguments={"group_id": str(group_id)},
        )
    )
    assert (
        result["group_id"] == web.json()["group_id"]
        and result["passport_retention_days_applied"]
        == web.json()["passport_retention_days_applied"]
    )
    assert len(json.dumps(result, ensure_ascii=True).encode()) < 8192
    assert result["environment"] == f[2].app_env and result["revision"] == f[2].app_revision
    audit = await f[1].get(AuditLogModel, uuid.UUID(result["audit_id"]))
    assert audit.result == "success" and audit.metadata_json == {
        "capability": "mcp:read",
        "failure_category": None,
    }
    assert str(group_id) not in json.dumps(audit.metadata_json)
    response = await f[0].post(
        "/mcp",
        headers={
            "Authorization": f"Bearer {tokens['access_token']}",
            "Accept": "application/json, text/event-stream",
        },
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    tools = [
        tool
        for tool in response.json()["result"]["tools"]
        if "retention" in tool["name"] or "purge" in tool["name"]
    ]
    assert len(tools) == 1 and tools[0]["name"] == "get_group_passport_retention"
    assert set(tools[0]["inputSchema"]["properties"]) == {"group_id"}
    assert (
        tools[0]["annotations"]["readOnlyHint"] is True
        and tools[0]["annotations"]["destructiveHint"] is False
    )
    assert tools[0]["_meta"]["capability"] == "mcp:read"


@pytest.mark.parametrize("role", ["agency_staff", "agency_manager", "agency_coordinator", "client_manager"])
async def test_real_website_denies_other_roles(retention_http, role):
    f, data = retention_http
    group_id = data.groups[0].id
    f[3].role = role
    await f[1].commit()
    response = await f[0].get(
        f"/api/v1/admin/groups/{group_id}/passport-retention",
        headers={"Authorization": f"Bearer {f[5]}"},
    )
    assert response.status_code in (401, 403)


@pytest.mark.parametrize(
    "restriction",
    ["revoked", "capability", "deployment", "role", "inactive", "deleted", "session", "control"],
)
async def test_actual_mcp_current_authority_denied_before_group_projection(
    retention_http, monkeypatch, restriction
):
    f, data = retention_http
    _, tokens = await connect(f, scopes=["mcp:read"])
    group_id = data.groups[0].id
    grant = await f[1].scalar(select(MCPGrantModel))
    if restriction == "revoked":
        grant.revoked_at = datetime.now(UTC)
    elif restriction == "capability":
        grant.capabilities = ["mcp:export"]
    elif restriction == "deployment":
        f[2].mcp.enabled_capabilities = ["mcp:export"]
    elif restriction == "role":
        f[3].role = "agency_admin"
    elif restriction == "inactive":
        f[3].is_active = False
    elif restriction == "deleted":
        f[3].deleted_at = datetime.now(UTC)
    elif restriction == "session":
        f[4].session_version += 1
    else:
        (await f[1].get(MCPControlModel, 1)).enabled = False
    await f[1].commit()
    read = AsyncMock(side_effect=AssertionError("Unauthorized group projection"))
    monkeypatch.setattr(PassportRetentionRepository, "get_schedule", read)
    response = await call_mcp(
        f[0],
        tokens["access_token"],
        name="get_group_passport_retention",
        arguments={"group_id": str(group_id)},
    )
    if response.status_code != 401:
        assert body(response)["error"] == "access_denied"
    read.assert_not_called()


@pytest.mark.parametrize("failure", ["missing", "timeout", "oversize", "unexpected"])
async def test_actual_mcp_failure_static_no_partial_schedule_and_retry(
    retention_http, monkeypatch, failure
):
    f, data = retention_http
    _, tokens = await connect(f, scopes=["mcp:read"])
    group_id = str(data.groups[-1].id)
    with monkeypatch.context() as patch:
        if failure == "oversize":
            patch.setattr(retention_reads, "MAX_RETENTION_RESPONSE_BYTES", 64)
        elif failure == "missing":
            patch.setattr(PassportRetentionRepository, "get_schedule", AsyncMock(return_value=None))
        else:
            patch.setattr(
                PassportRetentionRepository,
                "get_schedule",
                AsyncMock(
                    side_effect=TimeoutError("SECRET")
                    if failure == "timeout"
                    else RuntimeError("SECRET")
                ),
            )
        result = body(
            await call_mcp(
                f[0],
                tokens["access_token"],
                name="get_group_passport_retention",
                arguments={"group_id": group_id},
            )
        )
    assert (
        result["error"]
        == {
            "missing": "retention_schedule_unavailable",
            "timeout": "retention_read_busy",
            "oversize": "retention_read_limit",
            "unexpected": "operation_failed",
        }[failure]
    )
    assert result["completeness"] == "unavailable" and "passport_purge_at" not in result
    assert "SECRET" not in json.dumps(result)
    assert (
        body(
            await call_mcp(
                f[0],
                tokens["access_token"],
                name="get_group_passport_retention",
                arguments={"group_id": group_id},
            )
        )["group_id"]
        == group_id
    )


@pytest.mark.parametrize("arguments", [{}, {"group_id": "not-a-uuid"}, {"group_id": True}])
async def test_actual_sdk_rejects_missing_or_invalid_group_without_read(
    retention_http, monkeypatch, arguments
):
    f, _ = retention_http
    _, tokens = await connect(f, scopes=["mcp:read"])
    read = AsyncMock(side_effect=AssertionError("Invalid group projection"))
    monkeypatch.setattr(PassportRetentionRepository, "get_schedule", read)
    response = await call_mcp(
        f[0], tokens["access_token"], name="get_group_passport_retention", arguments=arguments
    )
    assert response.status_code == 200 and response.json()["result"]["isError"] is True
    read.assert_not_called()
