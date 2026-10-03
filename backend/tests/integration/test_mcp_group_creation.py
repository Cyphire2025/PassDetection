"""Group creation preserves existing data and shares website business validation."""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken
from sqlalchemy import func, select

from app.application.mcp.group_changes import CREATE_GROUP_POLICY, group_creation_operation
from app.application.mcp.operations import MCPOperationError, MCPOperationService
from app.application.use_cases.client_groups.create_client_group_use_case import (
    CreateClientGroupUseCase,
)
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    PlatformSettingModel,
    UserModel,
    WhatsAppBroadcastGroupModel,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.schemas.client_group_schemas import CreateClientGroupRequest
from app.presentation.mcp.group_change_tools import (
    MCPCreateGroupRequest,
    register_group_change_tools,
    validate_group_creation,
)
from app.presentation.mcp.invocation import MCPInputError
from tests.integration.test_mcp_operations import operations_fixture as operations_fixture


@pytest.fixture
async def group_creation_fixture(operations_fixture):
    session, settings, actor, grants, tokens = operations_fixture
    agency = AgencyModel(
        id=uuid.uuid4(), name="Creation tenant", email="creation-agency@example.test"
    )
    session.add(agency)
    await session.flush()
    owner = UserModel(
        id=uuid.uuid4(),
        email="group-owner@example.test",
        full_name="Group owner",
        hashed_password="fixture",
        role="agency_staff",
        is_active=True,
        agency_id=agency.id,
    )
    session.add(owner)
    await session.flush()
    payload = {
        "agency_id": str(agency.id),
        "owner_user_id": str(owner.id),
        "name": "  September   trip ",
        "destination": "Japan",
        "travel_date": "2026-10-10",
        "return_date": "2026-10-18",
        "timezone": "Asia/Tokyo",
        "import_only": False,
        "collection_settings_confirmed": True,
    }
    definition = group_creation_operation(validate_group_creation)
    service = MCPOperationService(session, settings, [definition])
    return operations_fixture, agency, owner, payload, service


async def create(fixture, *, key="group-create-request-001", payload=None, connection=0):
    base, _, _, default, service = fixture
    return await service.execute(
        access_token=base[4][connection],
        operation_name=CREATE_GROUP_POLICY.name,
        idempotency_key=key,
        payload=default if payload is None else payload,
    )


async def test_creation_uses_existing_use_case_and_replay_preserves_original_data(
    group_creation_fixture, monkeypatch
):
    fixture = group_creation_fixture
    original = CreateClientGroupUseCase.execute
    calls = 0

    async def observed(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(CreateClientGroupUseCase, "execute", observed)
    receipt = await create(fixture)
    session, _, actor, _, _ = fixture[0]
    group = await session.get(ClientGroupModel, uuid.UUID(receipt["data"]["group_id"]))
    assert group.name == "September trip" and group.agency_id == fixture[1].id
    assert group.created_by_user_id == fixture[2].id
    assert group.timezone == "Asia/Tokyo" and group.token
    assert receipt["created_entities"][0]["path"] == f"/passports/groups/{group.id}"
    assert group.token not in json.dumps(receipt) and "token" not in receipt["data"]
    # A later legitimate application edit is retained, while retry returns its
    # original creation receipt and does not restore older field values.
    group.name = "Edited by staff"
    await session.flush()
    assert await create(fixture, connection=1) == receipt
    assert calls == 1 and group.name == "Edited by staff"
    assert await session.scalar(select(func.count()).select_from(ClientGroupModel)) == 1
    audit = await session.get(AuditLogModel, uuid.UUID(receipt["data"]["business_audit_id"]))
    assert audit.user_id == actor.id and audit.entity_id == str(group.id)
    assert audit.metadata_json["owner_user_id"] == str(fixture[2].id)
    assert await session.scalar(select(func.count()).select_from(WhatsAppBroadcastGroupModel)) == 0
    assert (
        await session.scalar(
            select(func.count()).select_from(ClientGroupWhatsAppBroadcastLinkModel)
        )
        == 0
    )


async def test_changed_retry_input_conflicts_without_overwriting_and_same_name_can_be_new(
    group_creation_fixture,
):
    fixture = group_creation_fixture
    first = await create(fixture)
    with pytest.raises(MCPOperationError, match="idempotency_conflict"):
        await create(fixture, payload={**fixture[3], "destination": "Changed"})
    second = await create(fixture, key="explicit-new-group-002")
    assert first["data"]["group_id"] != second["data"]["group_id"]
    groups = list((await fixture[0][0].scalars(select(ClientGroupModel))).all())
    assert len(groups) == 2 and {group.destination for group in groups} == {"Japan"}


@pytest.mark.parametrize(
    "change",
    [
        {"return_date": "2026-09-01"},
        {"timezone": "Not/A_Timezone"},
        {"name": " "},
        {"name": "x" * 101},
        {"destination": ""},
        {"import_only": "true"},
        {"whatsapp_broadcast_group_ids": [str(uuid.uuid4())]},
        {"status": "archived"},
        {"token": "injected"},
    ],
)
async def test_invalid_or_unsupported_creation_never_writes_group(group_creation_fixture, change):
    fixture = group_creation_fixture
    with pytest.raises(MCPInputError, match="documented creation fields"):
        await create(fixture, payload={**fixture[3], **change})
    session = fixture[0][0]
    assert await session.scalar(select(func.count()).select_from(ClientGroupModel)) == 0
    assert await session.scalar(select(func.count()).select_from(MCPOperationModel)) == 0


@pytest.mark.parametrize(
    "change",
    [
        "missing_agency",
        "inactive_agency",
        "missing_owner",
        "inactive_owner",
        "deleted_owner",
        "cross_tenant",
        "coordinator_owner",
        "manager_disabled",
    ],
)
async def test_explicit_tenant_and_owner_must_remain_eligible(group_creation_fixture, change):
    fixture = group_creation_fixture
    base, agency, owner, original_payload, _ = fixture
    session, payload = base[0], dict(original_payload)
    if change == "missing_agency":
        payload["agency_id"] = str(uuid.uuid4())
    elif change == "inactive_agency":
        agency.is_active = False
    elif change == "missing_owner":
        payload["owner_user_id"] = str(uuid.uuid4())
    elif change == "inactive_owner":
        owner.is_active = False
    elif change == "deleted_owner":
        owner.deleted_at = datetime.now(UTC)
    elif change == "cross_tenant":
        owner.agency_id = None
    elif change == "coordinator_owner":
        owner.role = "agency_coordinator"
    else:
        owner.role = "agency_manager"
        session.add(
            PlatformSettingModel(key="global", value={"allow_manager_group_creation": False})
        )
    await session.flush()
    with pytest.raises(MCPOperationError):
        await create(fixture, payload=payload)
    assert await session.scalar(select(func.count()).select_from(ClientGroupModel)) == 0
    assert await session.scalar(select(func.count()).select_from(MCPOperationModel)) == 0


async def test_import_creation_and_platform_default_status_match_web_rules(group_creation_fixture):
    fixture = group_creation_fixture
    session = fixture[0][0]
    session.add(
        PlatformSettingModel(
            key="global",
            value={"default_group_status": "closed", "passport_data_retention_days": 30},
        )
    )
    await session.flush()
    receipt = await create(fixture, payload={**fixture[3], "import_only": True})
    group = await session.get(ClientGroupModel, uuid.UUID(receipt["data"]["group_id"]))
    assert group.import_only and group.status == "closed" and group.closed_at
    assert not group.allow_files_from_device and not group.require_selfie
    assert group.passport_retention_days_applied == 30 and group.passport_purge_at
    assert receipt["data"]["public_collection_enabled"] is False


async def test_business_audit_failure_rolls_back_creation_and_retry_key(
    group_creation_fixture, monkeypatch
):
    fixture = group_creation_fixture
    monkeypatch.setattr(
        AuditLogRepository,
        "record",
        AsyncMock(side_effect=RuntimeError("audit persistence failed")),
    )
    with pytest.raises(RuntimeError, match="audit persistence failed"):
        await create(fixture)
    session = fixture[0][0]
    assert await session.scalar(select(func.count()).select_from(ClientGroupModel)) == 0
    assert await session.scalar(select(func.count()).select_from(MCPOperationModel)) == 0


def test_tool_input_schema_exposes_only_reviewed_creation_fields():
    schema = MCPCreateGroupRequest.model_json_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == set(CreateClientGroupRequest.model_fields) | {
        "agency_id",
        "owner_user_id",
        "collection_settings_confirmed",
    }
    assert {
        "agency_id",
        "owner_user_id",
        "name",
        "destination",
        "travel_date",
        "return_date",
        "collection_settings_confirmed",
    } <= set(schema["required"])


async def sdk_fixture(fixture, monkeypatch):
    base, _, _, payload, _ = fixture
    session, settings, actor, grants, tokens = base
    await session.commit()
    app = FastAPI()

    @asynccontextmanager
    async def sessions():
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise

    app.state.mcp_session_factory = sessions
    app.state.mcp_operations = {}
    server = MCPServer("Group creation fixture")
    register_group_change_tools(server, app, settings)
    current = [0]

    def token():
        index = current[0]
        return AccessToken(
            token=tokens[index],
            client_id=grants[index].client_id,
            scopes=["mcp:change"],
            subject=str(actor.id),
            resource=settings.mcp.resource,
            claims={"grant_id": str(grants[index].id)},
        )

    monkeypatch.setattr("app.presentation.mcp.invocation.get_access_token", token)
    return server, current, {"group": payload, "idempotency_key": "sdk-group-create-001"}


async def test_sdk_tool_commits_creation_and_audits_replays_separately(
    group_creation_fixture, monkeypatch
):
    server, current, arguments = await sdk_fixture(group_creation_fixture, monkeypatch)
    tools = await server.list_tools()
    assert [tool.name for tool in tools] == ["create_group"]
    assert tools[0].annotations.read_only_hint is False
    first = (await server.call_tool("create_group", arguments)).structured_content
    current[0] = 1
    second = (await server.call_tool("create_group", arguments)).structured_content
    assert first["receipt"] == second["receipt"] and first["audit_id"] != second["audit_id"]
    session = group_creation_fixture[0][0]
    assert not session.in_transaction()
    assert await session.scalar(select(func.count()).select_from(ClientGroupModel)) == 1
    audits = list((await session.scalars(select(AuditLogModel))).all())
    assert [audit.action for audit in audits].count("client_group_created") == 1
    assert [audit.action for audit in audits].count("mcp.tool.create_group") == 2


async def test_sdk_tool_reports_safe_validation_failure_and_no_created_group(
    group_creation_fixture, monkeypatch
):
    server, _, arguments = await sdk_fixture(group_creation_fixture, monkeypatch)
    arguments["group"] = {**arguments["group"], "timezone": "secret-invalid-zone"}
    result = (await server.call_tool("create_group", arguments)).structured_content
    assert result["error"] == "invalid_group_creation" and result["requires_input"] is True
    assert "secret-invalid-zone" not in json.dumps(result)
    session = group_creation_fixture[0][0]
    assert await session.scalar(select(func.count()).select_from(ClientGroupModel)) == 0
    audit = await session.get(AuditLogModel, uuid.UUID(result["audit_id"]))
    assert audit.result == "blocked"
