"""Current scope, retained assignments and browser-MFA parity for additive access."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken
from sqlalchemy import func, select

from app.application.mcp.access_changes import inspect_group_access
from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.credentials import utc
from app.application.mcp.operations import (
    MCPDatabaseContext,
    MCPOperationError,
    MCPOperationService,
)
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    ManagerGroupAccessModel,
    UserModel,
)
from app.presentation.mcp.access_change_tools import access_definition, register_access_change_tools
from app.presentation.mcp.invocation import MCPInputError
from tests.integration.test_mcp_operations import operations_fixture as operations_fixture


@pytest.fixture
async def access_changes(operations_fixture):
    session, settings, actor, grants, tokens = operations_fixture
    agencies = [
        AgencyModel(id=uuid.uuid4(), name="Synthetic agency", email=f"{uuid.uuid4()}@example.test")
        for _ in range(2)
    ]
    session.add_all(agencies)
    await session.flush()
    accounts = [
        UserModel(
            id=uuid.uuid4(),
            agency_id=agencies[0].id,
            role=role,
            full_name="Synthetic account",
            email=f"{uuid.uuid4()}@example.test",
            hashed_password="fixture",
            is_active=True,
        )
        for role in ("agency_staff", "agency_manager")
    ]
    session.add_all(accounts)
    await session.flush()
    groups = [
        ClientGroupModel(
            id=uuid.uuid4(),
            agency_id=agencies[0].id,
            name="Same name",
            token=uuid.uuid4().hex,
            import_only=True,
        )
        for _ in range(4)
    ]
    groups[0].created_by_user_id = accounts[0].id
    session.add_all(groups)
    await session.flush()
    existing = [
        ManagerGroupAccessModel(
            id=uuid.uuid4(),
            manager_id=accounts[0].id,
            group_id=groups[index].id,
            agency_id=agencies[0].id,
        )
        for index in (1, 3)
    ]
    session.add_all(existing)
    for grant in grants:
        grant.capabilities = ["mcp:read", "mcp:change"]
    await session.flush()
    return operations_fixture, agencies, accounts, groups, existing


async def inspected(fixture, *, index=0, group_ids=None):
    session, settings, _, _, tokens = fixture[0]
    principal = await MCPAuthorizationService(session, settings).verify_access(
        tokens[0], "mcp:read"
    )
    return await inspect_group_access(
        MCPDatabaseContext(session, principal, uuid.uuid4()),
        agency_id=fixture[1][0].id,
        account_id=fixture[2][index].id,
        account_type="staff" if index == 0 else "manager",
        group_ids=[row.id for row in fixture[3][:3]] if group_ids is None else group_ids,
    )


async def payload_for(fixture, *, index=0):
    read = await inspected(fixture, index=index)
    return {
        "agency_id": read["agency_id"],
        "account_id": read["account_id"],
        "group_ids": [row["group_id"] for row in read["selected_groups"]],
        "expected_revision": read["access_revision"],
    }


async def execute(fixture, payload, *, index=0, connection=0, key="add-access-stable-request"):
    session, settings, _, _, tokens = fixture[0]
    name = "add_staff_group_access" if index == 0 else "add_manager_group_access"
    return await MCPOperationService(session, settings, [access_definition(name)]).execute(
        access_token=tokens[connection], operation_name=name, idempotency_key=key, payload=payload
    )


@pytest.mark.parametrize("index", [0, 1])
async def test_add_only_missing_access_retains_every_other_row_and_exact_retry(
    access_changes, index
):
    f = access_changes
    before = [(row.id, row.manager_id, row.group_id, utc(row.created_at)) for row in f[4]]
    payload = await payload_for(f, index=index)
    result = await execute(f, payload, index=index)
    assert result["data"]["added_count"] == (1 if index == 0 else 3)
    assert [(row.id, row.manager_id, row.group_id, utc(row.created_at)) for row in f[4]] == before
    assert await execute(f, payload, index=index, connection=1) == result
    assert await f[0][0].scalar(select(func.count()).select_from(MCPOperationModel)) == 1
    assert "hashed_password" not in str(result) and f[3][0].token not in str(result)
    assert all(row["path"].startswith("/passports/groups/") for row in result["created_entities"])


async def test_inspection_separates_owned_assigned_and_unassigned_without_mutation(access_changes):
    result = await inspected(access_changes)
    by_id = {row["group_id"]: row["access"] for row in result["selected_groups"]}
    assert [by_id[str(group.id)] for group in access_changes[3][:3]] == [
        "owned",
        "assigned",
        "not_assigned",
    ]
    assert result["retained_assignment_count"] == 2
    assert (
        await access_changes[0][0].scalar(select(func.count()).select_from(MCPOperationModel)) == 0
    )


@pytest.mark.parametrize(
    "change",
    [
        "inactive",
        "deleted",
        "role",
        "agency",
        "archived",
        "group_deleted",
        "group_agency",
        "agency_inactive",
    ],
)
async def test_current_scope_blocks_addition_without_partial_rows(access_changes, change):
    f = access_changes
    payload = await payload_for(f)
    if change == "inactive":
        f[2][0].is_active = False
    elif change == "deleted":
        f[2][0].deleted_at = datetime.now(UTC)
    elif change == "role":
        f[2][0].role = "agency_manager"
    elif change == "agency":
        f[2][0].agency_id = f[1][1].id
    elif change == "archived":
        f[3][2].status = "archived"
    elif change == "group_deleted":
        f[3][2].deleted_at = datetime.now(UTC)
    elif change == "group_agency":
        f[3][2].agency_id = f[1][1].id
    else:
        f[1][0].is_active = False
    await f[0][0].flush()
    with pytest.raises(MCPInputError):
        await execute(f, payload)
    assert await f[0][0].scalar(select(func.count()).select_from(ManagerGroupAccessModel)) == 2
    assert await f[0][0].scalar(select(func.count()).select_from(MCPOperationModel)) == 0


@pytest.mark.parametrize("replay", [False, True])
@pytest.mark.parametrize("age", [601, -61])
async def test_recent_mfa_matches_web_window_for_mutation_and_replay(access_changes, replay, age):
    f = access_changes
    payload = await payload_for(f)
    if replay:
        await execute(f, payload)
    f[0][3][0].mfa_at = datetime.now(UTC) - timedelta(seconds=age)
    await f[0][0].flush()
    with pytest.raises(MCPInputError, match="MFA"):
        await execute(f, payload)
    # A separately authorized fresh connection recovers the exact user-owned intent.
    assert (await execute(f, payload, connection=1))["data"]["added_count"] == 1


@pytest.mark.parametrize("change", ["unrelated_assignment", "selected_owner", "group_revision"])
async def test_revision_covers_unrelated_access_and_selected_group_state(access_changes, change):
    f = access_changes
    payload = await payload_for(f)
    if change == "unrelated_assignment":
        await f[0][0].delete(f[4][1])
    elif change == "selected_owner":
        f[3][2].created_by_user_id = f[2][0].id
    else:
        f[3][2].roster_revision += 1
    await f[0][0].flush()
    with pytest.raises(MCPInputError, match="changed"):
        await execute(f, payload)
    assert await f[0][0].scalar(select(func.count()).select_from(MCPOperationModel)) == 0


@pytest.mark.parametrize(
    "change", ["removed", "rebound", "owned_changed", "account_inactive", "group_archived"]
)
async def test_receipt_rechecks_exact_current_entity_binding(access_changes, change):
    f = access_changes
    payload = await payload_for(f)
    receipt = await execute(f, payload)
    added = await f[0][0].get(
        ManagerGroupAccessModel, uuid.UUID(receipt["data"]["added_assignment_ids"][0])
    )
    if change == "removed":
        await f[0][0].delete(added)
    elif change == "rebound":
        added.group_id = f[3][0].id
    elif change == "owned_changed":
        f[3][0].created_by_user_id = f[2][1].id
    elif change == "account_inactive":
        f[2][0].is_active = False
    else:
        f[3][2].status = "archived"
    await f[0][0].flush()
    with pytest.raises(MCPInputError):
        await execute(f, payload)


@pytest.mark.parametrize("bad", ["empty", "duplicates", "101", "extra", "revision"])
async def test_strict_bounded_inputs_reject_before_access_change(access_changes, bad):
    f = access_changes
    payload = await payload_for(f)
    if bad == "empty":
        payload["group_ids"] = []
    elif bad == "duplicates":
        payload["group_ids"] *= 2
    elif bad == "101":
        payload["group_ids"] = [str(uuid.uuid4()) for _ in range(101)]
    elif bad == "extra":
        payload["replace"] = True
    else:
        payload["expected_revision"] = "malicious secret"
    with pytest.raises(MCPInputError, match="exact"):
        await execute(f, payload)
    assert await f[0][0].scalar(select(func.count()).select_from(ManagerGroupAccessModel)) == 2


async def test_retained_scope_over_bound_fails_before_mutation(access_changes, monkeypatch):
    f = access_changes
    monkeypatch.setattr("app.application.mcp.access_changes.MAX_RETAINED_ASSIGNMENTS", 1)
    with pytest.raises(MCPOperationError, match="scope_too_large"):
        await inspected(f)


async def test_sdk_schema_read_and_both_operations_commit_audited_receipts(
    access_changes, monkeypatch
):
    f = access_changes
    session, settings, actor, grants, tokens = f[0]
    await session.commit()
    app, server = FastAPI(), MCPServer("Access fixture")

    @asynccontextmanager
    async def factory():
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise

    app.state.mcp_session_factory = factory
    app.state.mcp_operations = {}
    register_access_change_tools(server, app, settings)
    monkeypatch.setattr(
        "app.presentation.mcp.invocation.get_access_token",
        lambda: AccessToken(
            token=tokens[0],
            client_id="global-connects-desktop",
            scopes=["mcp:read", "mcp:change"],
            subject=str(actor.id),
            resource=settings.mcp.resource,
            claims={"grant_id": str(grants[0].id)},
        ),
    )
    assert {tool.name for tool in await server.list_tools()} == {
        "inspect_group_access",
        "add_staff_group_access",
        "add_manager_group_access",
    }
    for index, account_type in enumerate(("staff", "manager")):
        selection = {
            "agency_id": str(f[1][0].id),
            "account_id": str(f[2][index].id),
            "group_ids": [str(group.id) for group in f[3][:3]],
        }
        read = (
            await server.call_tool(
                "inspect_group_access", {"selection": selection, "account_type": account_type}
            )
        ).structured_content
        assert read["completeness"] == "complete" and read["audit_id"]
        args = {
            "assignment": {**selection, "expected_revision": read["access_revision"]},
            "idempotency_key": f"sdk-access-{account_type}-request",
        }
        result = (
            await server.call_tool(f"add_{account_type}_group_access", args)
        ).structured_content
        replay = (
            await server.call_tool(f"add_{account_type}_group_access", args)
        ).structured_content
        assert "receipt" in result, result
        assert result["receipt"] == replay["receipt"] and result["audit_id"] != replay["audit_id"]
        assert not session.in_transaction()


async def test_addition_cannot_cross_recoverable_retained_scope_bound(access_changes, monkeypatch):
    f = access_changes
    payload = await payload_for(f)
    monkeypatch.setattr("app.application.mcp.access_changes.MAX_RETAINED_ASSIGNMENTS", 2)
    with pytest.raises(MCPInputError, match="5000"):
        await execute(f, payload)
    assert await f[0][0].scalar(select(func.count()).select_from(ManagerGroupAccessModel)) == 2
