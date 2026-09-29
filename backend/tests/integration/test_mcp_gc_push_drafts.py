"""Append-only authored draft creation and complete SDK text-to-queue flow."""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken
from pydantic import ValidationError
from sqlalchemy import func, select

from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.gc_push_drafts import gc_push_draft_operation
from app.application.mcp.operations import MCPOperationError, MCPOperationService
from app.infrastructure.database.gc_mobile_models import MobileNotificationModel
from app.infrastructure.database.gc_notification_models import GCNotificationDraftModel
from app.presentation.mcp.gc_push_tools import register_gc_push_tools
from tests.integration.test_mcp_gc_push import push_fixture as push_fixture
from tests.integration.test_mcp_operations import operations_fixture as operations_fixture

pytestmark = pytest.mark.asyncio


def payload(f):
    return {
        "agency_id": str(f[1].agency_id),
        "title": "Meet at the bus",
        "body": "Please arrive at 08:30.",
        "group_ids": [str(a.group_id) for a in f[2]],
    }


async def create(f, value=None, *, connection=0, key="create-gc-push-draft-001"):
    for grant in f[0][3]:
        grant.capabilities = ["mcp:read", "mcp:communicate", "mcp:change"]
    await f[0][0].flush()
    return await MCPOperationService(f[0][0], f[0][1], (gc_push_draft_operation(),)).execute(
        access_token=f[0][4][connection],
        operation_name="create_gc_push_draft",
        idempotency_key=key,
        payload=payload(f) if value is None else value,
    )


async def test_draft_creation_replays_across_connections_without_replacing_or_sending(push_fixture):
    f = push_fixture
    created = await create(f)
    replay = await create(f, connection=1)
    assert created == replay
    assert created["data"]["revision"] == 1 and created["data"]["messages_queued"] == 0
    assert f[4].title == "Meet at reception"
    assert await f[0][0].scalar(select(func.count()).select_from(GCNotificationDraftModel)) == 2
    assert await f[0][0].scalar(select(func.count()).select_from(MobileNotificationModel)) == 0
    with pytest.raises(MCPOperationError, match="idempotency_conflict"):
        await create(f, {**payload(f), "body": "Different content"})


@pytest.mark.parametrize(
    "changed", ["duplicate_groups", "all_active", "update_id", "eleven_groups", "blank_body"]
)
async def test_draft_validation_preserves_existing_records(push_fixture, changed):
    f = push_fixture
    value = payload(f)
    if changed == "duplicate_groups":
        value["group_ids"] *= 2
    elif changed == "all_active":
        value["audience"] = "all_active_trips"
    elif changed == "update_id":
        value["draft_id"] = str(f[4].id)
    elif changed == "eleven_groups":
        value["group_ids"] = [str(uuid.uuid4()) for _ in range(11)]
    else:
        value["body"] = "  "
    with pytest.raises(ValidationError):
        await create(f, value)
    assert await f[0][0].scalar(select(func.count()).select_from(GCNotificationDraftModel)) == 1


async def test_missing_or_other_agency_group_is_rejected_by_shared_business_validation(
    push_fixture,
):
    f = push_fixture
    with pytest.raises(MCPOperationError, match="gc_push_audience_unavailable"):
        await create(f, {**payload(f), "group_ids": [str(uuid.uuid4())]})
    assert await f[0][0].scalar(select(func.count()).select_from(GCNotificationDraftModel)) == 1


async def test_manual_draft_deletion_denies_saved_receipt_disclosure(push_fixture):
    f = push_fixture
    created = await create(f)
    draft = await f[0][0].get(GCNotificationDraftModel, uuid.UUID(created["data"]["draft_id"]))
    draft.deleted_at = datetime.now(UTC)
    await f[0][0].flush()
    with pytest.raises(MCPAuthError):
        await create(f, connection=1)


async def test_sdk_text_to_saved_preview_to_confirmed_queue(push_fixture, monkeypatch):
    f = push_fixture
    session, settings, user, grants, tokens = f[0]
    for grant in grants:
        grant.capabilities = ["mcp:read", "mcp:communicate", "mcp:change"]
    await session.commit()
    app, server = FastAPI(), MCPServer("GC push full fixture")

    @asynccontextmanager
    async def sessions():
        yield session

    app.state.mcp_session_factory, app.state.mcp_operations = sessions, {}
    register_gc_push_tools(app, server, settings)
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
    created = (
        await server.call_tool(
            "create_gc_push_draft",
            {"draft": payload(f), "idempotency_key": "sdk-create-gc-draft-001"},
        )
    ).structured_content
    assert "receipt" in created, created
    draft = created["receipt"]["data"]
    assert draft["messages_queued"] == 0
    prepared = (
        await server.call_tool(
            "prepare_gc_push",
            {
                "draft": {
                    "agency_id": draft["agency_id"],
                    "draft_id": draft["draft_id"],
                    "expected_revision": draft["revision"],
                },
                "idempotency_key": "sdk-prepare-created-001",
            },
        )
    ).structured_content
    plan = prepared["receipt"]["data"]
    assert plan["preview"]["title"] == payload(f)["title"]
    confirmed = (
        await server.call_tool(
            "confirm_gc_push",
            {
                "plan_id": plan["plan_id"],
                "plan_hash": plan["plan_hash"],
                "idempotency_key": "sdk-confirm-created-001",
            },
        )
    ).structured_content
    assert confirmed["receipt"]["status"] == "queued"
    assert await session.scalar(select(func.count()).select_from(MobileNotificationModel)) == 2
