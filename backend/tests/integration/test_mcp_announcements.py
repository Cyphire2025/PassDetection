"""Retained announcement revisions reuse website creation without deletion/publication."""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken
from sqlalchemy import func, select, text

from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.operations import MCPOperationError, MCPOperationService
from app.infrastructure.database.gc_mobile_models import (
    GCAnnouncementModel,
    MobileNotificationModel,
)
from app.infrastructure.database.models import AgencyModel
from app.presentation.api.v1.routes.gc_app_content import publish_announcement
from app.presentation.mcp.announcement_tools import (
    announcement_definition,
    register_announcement_tools,
)
from app.presentation.mcp.invocation import MCPInputError
from tests.gc_app_workflow_fixtures import workflow_group
from tests.integration.test_mcp_operations import operations_fixture as operations_fixture
from tests.unit.presentation.test_gc_app_announcement_atomic_publish import request

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def announcement_fixture(operations_fixture):
    session, settings, user, grants, tokens = operations_fixture
    for grant in grants:
        grant.capabilities = ["mcp:change", "mcp:read"]
    actor, group, access = await workflow_group(session)
    await session.commit()
    await session.execute(text("BEGIN"))
    service = MCPOperationService(
        session,
        settings,
        (announcement_definition(revision=False), announcement_definition(revision=True)),
    )
    return operations_fixture, actor, group, access, service


def payload(f):
    return {
        "agency_id": str(f[2].agency_id),
        "group_id": str(f[2].id),
        "title": "Breakfast",
        "message": "Breakfast is served at 07:00.",
        "expected_access_revision": f[3].revision,
        "publish": False,
    }


async def invoke(f, value, *, revision=False, key="create-announcement-001", connection=0):
    return await f[4].execute(
        access_token=f[0][4][connection],
        operation_name="create_gc_announcement_revision"
        if revision
        else "create_gc_announcement_draft",
        payload=value,
        idempotency_key=key,
    )


async def test_new_draft_cross_connection_replay_one_append_no_notifications(announcement_fixture):
    f = announcement_fixture
    value = payload(f)
    created = await invoke(f, value)
    assert created == await invoke(f, value, connection=1)
    assert created["data"]["status"] == "draft" and created["data"]["notifications_queued"] == 0
    assert f[3].revision == value["expected_access_revision"] + 1
    assert await f[0][0].scalar(select(func.count()).select_from(GCAnnouncementModel)) == 1
    assert await f[0][0].scalar(select(func.count()).select_from(MobileNotificationModel)) == 0
    with pytest.raises(MCPOperationError, match="idempotency_conflict"):
        await invoke(f, {**value, "message": "Changed content"})


@pytest.mark.parametrize("lost", ["agency", "group", "access", "capability", "role"])
async def test_replay_and_inspection_recheck_current_scope_without_exposing_saved_result(
    announcement_fixture, lost
):
    f = announcement_fixture
    value = payload(f)
    result = await invoke(f, value)
    session = f[0][0]
    if lost == "agency":
        (await session.get(AgencyModel, f[2].agency_id)).is_active = False
    elif lost == "group":
        f[2].deleted_at = datetime.now(UTC)
    elif lost == "access":
        f[3].removed_at = datetime.now(UTC)
        f[3].revoked_at = f[3].removed_at
        f[3].is_enabled = f[3].passenger_access_enabled = False
    elif lost == "capability":
        f[0][3][1].capabilities = ["mcp:read"]
    else:
        f[0][2].role = "agency_admin"
    await session.flush()
    for inspect in (False, True):
        with pytest.raises((MCPAuthError, MCPOperationError, MCPInputError)):
            if inspect:
                await f[4].inspect(
                    access_token=f[0][4][1], operation_id=uuid.UUID(result["operation_id"])
                )
            else:
                await invoke(f, value, connection=1)
    assert await session.scalar(select(func.count()).select_from(GCAnnouncementModel)) == 1


async def test_outer_rollback_restores_access_revision_and_allows_same_key_retry(announcement_fixture):
    f = announcement_fixture
    value = payload(f)
    session = f[0][0]
    await invoke(f, value)
    await session.rollback()
    await session.execute(text("BEGIN"))
    await session.refresh(f[3])
    assert f[3].revision == value["expected_access_revision"]
    assert await session.scalar(select(func.count()).select_from(GCAnnouncementModel)) == 0
    retried = await invoke(f, value)
    assert retried["data"]["version"] == 1
    assert await session.scalar(select(func.count()).select_from(GCAnnouncementModel)) == 1


async def test_revision_preserves_all_prior_drafts_and_published_version(announcement_fixture):
    f = announcement_fixture
    first = await invoke(f, payload(f))
    first_id = uuid.UUID(first["data"]["announcement_id"])
    await publish_announcement(f[2].id, first_id, request(), None, f[1], f[0][0])
    first_row = await f[0][0].get(GCAnnouncementModel, first_id)
    before = (first_row.body, first_row.status, first_row.published_at, first_row.version)
    second = await invoke(
        f,
        {
            **payload(f),
            "previous_announcement_id": str(first_id),
            "message": "Second retained draft",
        },
        revision=True,
        key="announcement-version-002",
    )
    second_id = uuid.UUID(second["data"]["announcement_id"])
    third = await invoke(
        f,
        {
            **payload(f),
            "previous_announcement_id": str(second_id),
            "message": "Third retained draft",
        },
        revision=True,
        key="announcement-version-003",
    )
    await f[0][0].refresh(first_row)
    assert (first_row.body, first_row.status, first_row.published_at, first_row.version) == before
    rows = list(
        await f[0][0].scalars(select(GCAnnouncementModel).order_by(GCAnnouncementModel.version))
    )
    assert [row.version for row in rows] == [1, 2, 3]
    assert [row.status for row in rows] == ["published", "draft", "draft"]
    assert rows[1].body == "Second retained draft"
    assert third["data"]["previous_versions_preserved"] is True


@pytest.mark.parametrize("invalid", ["publish", "delete", "stale", "window", "wrong_source"])
async def test_invalid_change_preserves_all_rows_and_current_revision(
    announcement_fixture, invalid
):
    f = announcement_fixture
    value = payload(f)
    revision = f[3].revision
    is_revision = False
    if invalid == "publish":
        value["publish"] = True
    elif invalid == "delete":
        value["delete_source"] = True
    elif invalid == "stale":
        value["expected_access_revision"] += 1
    elif invalid == "window":
        value["available_from"] = datetime.now(UTC).isoformat()
        value["available_until"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    else:
        value["previous_announcement_id"] = str(uuid.uuid4())
        is_revision = True
    with pytest.raises(MCPInputError):
        await invoke(f, value, revision=is_revision)
    await f[0][0].refresh(f[3])
    assert f[3].revision == revision
    assert await f[0][0].scalar(select(func.count()).select_from(GCAnnouncementModel)) == 0


async def test_sdk_descriptor_then_retained_draft_revision(announcement_fixture, monkeypatch):
    f = announcement_fixture
    session, settings, user, grants, tokens = f[0]
    await session.commit()
    app, server = FastAPI(), MCPServer("Announcement fixture")

    @asynccontextmanager
    async def sessions():
        yield session

    app.state.mcp_session_factory, app.state.mcp_operations = sessions, {}
    register_announcement_tools(app, server, settings)
    monkeypatch.setattr(
        "app.presentation.mcp.invocation.get_access_token",
        lambda: AccessToken(
            token=tokens[0],
            client_id=grants[0].client_id,
            scopes=grants[0].capabilities,
            subject=str(user.id),
            resource=settings.mcp.resource,
            claims={"grant_id": str(grants[0].id)},
        ),
    )
    descriptor = (
        await server.call_tool(
            "get_gc_announcement_change_context",
            {"agency_id": str(f[2].agency_id), "group_id": str(f[2].id)},
        )
    ).structured_content
    assert descriptor["expected_access_revision"] == f[3].revision and descriptor["source"] is None
    created = (
        await server.call_tool(
            "create_gc_announcement_draft",
            {"draft": payload(f), "idempotency_key": "sdk-announcement-create-001"},
        )
    ).structured_content
    assert "receipt" in created, created
    source = created["receipt"]["data"]
    descriptor = (
        await server.call_tool(
            "get_gc_announcement_change_context",
            {
                "agency_id": str(f[2].agency_id),
                "group_id": str(f[2].id),
                "announcement_id": source["announcement_id"],
            },
        )
    ).structured_content
    assert descriptor["source"]["message"] == payload(f)["message"]
    revised = (
        await server.call_tool(
            "create_gc_announcement_revision",
            {
                "draft": {
                    **payload(f),
                    "previous_announcement_id": source["announcement_id"],
                    "message": "Breakfast moved to 08:00.",
                },
                "idempotency_key": "sdk-announcement-revise-001",
            },
        )
    ).structured_content
    assert revised["receipt"]["data"]["version"] == 2
    assert await session.scalar(select(func.count()).select_from(GCAnnouncementModel)) == 2
