"""Announcement append/revision fences and website/push locks on real PostgreSQL."""

import asyncio
import os
import uuid

import pytest
from sqlalchemy import func, select

from app.application.mcp.operations import MCPOperationService
from app.infrastructure.database.gc_mobile_models import GCAnnouncementModel, GCGroupAccessModel
from app.infrastructure.database.gc_notification_models import GCNotificationDraftModel
from app.infrastructure.database.models import ClientGroupModel
from app.presentation.api.v1.routes.gc_app import refresh_mobile_passenger_identities
from app.presentation.api.v1.routes.gc_app_content import _admin_access_context, create_announcement
from app.presentation.api.v1.schemas.gc_app_schemas import AnnouncementCreateRequest
from app.presentation.mcp.announcement_tools import announcement_definition
from app.presentation.mcp.invocation import MCPInputError
from tests.service_integration.test_mcp_concurrency_postgresql import mcp_sessions as mcp_sessions
from tests.service_integration.test_mcp_gc_push_postgresql import (
    FcmProvider,
    confirmation,
    invoke,
    prepare,
    worker,
)
from tests.service_integration.test_mcp_gc_push_postgresql import (
    push_sessions as push_sessions,
)
from tests.unit.presentation.test_gc_app_announcement_atomic_publish import request

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required"
    ),
]


async def payload(f):
    async with f[0]() as session:
        draft = await session.get(GCNotificationDraftModel, f[6])
        group_id = uuid.UUID(draft.group_ids[0])
        access = await session.scalar(
            select(GCGroupAccessModel).where(GCGroupAccessModel.group_id == group_id)
        )
        return {
            "agency_id": str(f[5].agency_id),
            "group_id": str(group_id),
            "title": "Breakfast",
            "message": "Breakfast starts at 07:00.",
            "expected_access_revision": access.revision,
        }


async def create(f, value, *, key="pg-announcement-create-001", connection=0, revision=False):
    async with f[0]() as session:
        result = await MCPOperationService(
            session, f[1], (announcement_definition(revision=revision),)
        ).execute(
            access_token=f[4][connection],
            operation_name="create_gc_announcement_revision"
            if revision
            else "create_gc_announcement_draft",
            idempotency_key=key,
            payload=value,
        )
        await session.commit()
        return result


async def test_same_key_across_connections_appends_one_immutable_draft(push_sessions):
    f = push_sessions
    value = await payload(f)
    receipts = await asyncio.wait_for(
        asyncio.gather(*[create(f, value, connection=i % 2) for i in range(6)]), 15
    )
    assert all(receipt == receipts[0] for receipt in receipts)
    async with f[0]() as session:
        assert await session.scalar(select(func.count()).select_from(GCAnnouncementModel)) == 1
        access = await session.get(GCGroupAccessModel, uuid.UUID(receipts[0]["data"]["access_id"]))
        assert access.revision == value["expected_access_revision"] + 1


async def test_different_keys_at_same_revision_have_one_winner_without_lost_update(push_sessions):
    f = push_sessions
    value = await payload(f)
    results = await asyncio.wait_for(
        asyncio.gather(
            create(f, value, key="pg-announcement-contender-a", connection=0),
            create(f, value, key="pg-announcement-contender-b", connection=1),
            return_exceptions=True,
        ),
        15,
    )
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, MCPInputError) for result in results) == 1
    async with f[0]() as session:
        assert await session.scalar(select(func.count()).select_from(GCAnnouncementModel)) == 1


async def test_new_revisions_keep_prior_drafts_and_serialize_version_numbers(push_sessions):
    f = push_sessions
    value = await payload(f)
    first = await create(f, value)
    revised = {
        **value,
        "previous_announcement_id": first["data"]["announcement_id"],
        "expected_access_revision": first["data"]["access_revision"],
        "message": "Breakfast starts at 08:00.",
    }
    receipts = await asyncio.wait_for(
        asyncio.gather(*[create(f, revised, revision=True, connection=i % 2) for i in range(4)]),
        15,
    )
    assert all(receipt == receipts[0] for receipt in receipts)
    async with f[0]() as session:
        rows = list(await session.scalars(select(GCAnnouncementModel).order_by(GCAnnouncementModel.version)))
        assert [row.version for row in rows] == [1, 2]
        assert [row.body for row in rows] == [value["message"], revised["message"]]
        assert [row.status for row in rows] == ["draft", "draft"]


@pytest.mark.parametrize("winner", ["push", "website"])
async def test_website_content_edit_and_native_push_share_group_then_access_order(push_sessions, winner):
    f = push_sessions
    value = await payload(f)
    prepared = await prepare(f)
    await invoke(f, "confirm_gc_push", confirmation(prepared))
    entered, release, edit_started, edited = (asyncio.Event() for _ in range(4))

    class HeldProvider(FcmProvider):
        async def send(self, messages):
            entered.set()
            if winner == "push":
                await release.wait()
            return await super().send(messages)

    async def website_edit():
        async with f[0]() as session:
            edit_started.set()
            if winner == "website":
                await _admin_access_context(
                    session, f[5], uuid.UUID(value["group_id"]), agency_id=None, lock=True
                )
                edited.set()
                await release.wait()
            await create_announcement(
                uuid.UUID(value["group_id"]),
                AnnouncementCreateRequest(
                    title=value["title"], message=value["message"],
                    expected_access_revision=value["expected_access_revision"], publish=False,
                ),
                request(), None, f[5], session,
            )
            await session.commit()
            edited.set()

    provider = HeldProvider()
    if winner == "push":
        sending = asyncio.create_task(worker(f, provider))
        await asyncio.wait_for(entered.wait(), 5)
        editing = asyncio.create_task(website_edit())
        await edit_started.wait()
        await asyncio.sleep(0.15)
        assert not edited.is_set()
    else:
        editing = asyncio.create_task(website_edit())
        await asyncio.wait_for(edited.wait(), 5)
        sending = asyncio.create_task(worker(f, provider))
        await asyncio.sleep(0.15)
        assert not entered.is_set()
    release.set()
    await asyncio.wait_for(asyncio.gather(sending, editing), 10)
    assert sum(map(len, provider.calls)) == 1
    async with f[0]() as session:
        assert await session.scalar(select(func.count()).select_from(GCAnnouncementModel)) == 1


async def test_passenger_reconciliation_waits_for_group_before_holding_access(push_sessions):
    f = push_sessions
    value = await payload(f)
    group_id = uuid.UUID(value["group_id"])
    started = asyncio.Event()

    async def reconcile():
        async with f[0]() as session:
            started.set()
            await refresh_mobile_passenger_identities(group_id, request(), None, f[5], session)
            await session.commit()

    async with f[0]() as holder:
        await holder.scalar(select(ClientGroupModel).where(ClientGroupModel.id == group_id).with_for_update())
        pending = asyncio.create_task(reconcile())
        await started.wait()
        await asyncio.sleep(0.15)
        assert not pending.done()
        # A group owner must still be able to acquire access. Taking access
        # first in reconciliation can cycle when its identity/journal FK insert
        # later requests group KEY SHARE behind this transaction's group lock.
        await holder.scalar(select(GCGroupAccessModel).where(GCGroupAccessModel.group_id == group_id).with_for_update(nowait=True))
        await holder.commit()
    await asyncio.wait_for(pending, 10)
