"""PostgreSQL one-link exact-retry and canonical private-ledger locking."""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from sqlalchemy import event, func, select

from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.broadcast_link_changes import BroadcastLinkCommand, inspect_link_addition
from app.application.mcp.operations import MCPDatabaseContext, MCPOperationService
from app.infrastructure.database.models import (
    AuditLogModel,
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastSourceContactModel,
)
from app.infrastructure.whatsapp.private_delivery_policy import (
    lock_private_delivery_group_source_snapshot,
)
from app.presentation.mcp.broadcast_link_tools import _matching_fields, broadcast_link_definition
from app.presentation.mcp.invocation import MCPInputError
from tests.service_integration.test_mcp_access_postgresql import access_sessions as access_sessions
from tests.service_integration.test_mcp_concurrency_postgresql import mcp_sessions as mcp_sessions
from tests.service_integration.test_mcp_operations_postgresql import (
    operation_sessions as operation_sessions,
)
from tests.unit.infrastructure.test_whatsapp_source_group_sync import delivery, passenger

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required"
    ),
]


@pytest.fixture
async def link_sessions(access_sessions):
    f = access_sessions
    async with f[0]() as session:
        group = await session.get(ClientGroupModel, f[6][0])
        broadcast = WhatsAppBroadcastGroupModel(
            id=uuid.uuid4(),
            agency_id=group.agency_id,
            name="Synthetic link",
            imported_field_keys=["name", "phone_number"],
        )
        people = [
            passenger(group.agency_id, group.id, phone=phone, name=name)
            for phone, name in [
                ("9876543210", "One"),
                ("9876543210", "Shared"),
                ("9123456789", "Two"),
                ("invalid", "Invalid"),
            ]
        ]
        session.add_all([broadcast, *people])
        await session.flush()
        principal = await MCPAuthorizationService(session, f[1]).verify_access(
            f[3][0], "mcp:change"
        )
        read = await inspect_link_addition(
            MCPDatabaseContext(session, principal, uuid.uuid4()),
            BroadcastLinkCommand(group.agency_id, group.id, broadcast.id, None),
            _matching_fields,
        )
        payload = {
            "agency_id": read["agency_id"],
            "group_id": read["group_id"],
            "broadcast_id": read["broadcast_id"],
            "matching_field_keys": None,
            "expected_revision": read["source_revision"],
        }
        await session.commit()
    return f[0], f[1], f[3], payload, [person.id for person in people]


async def invoke(f, *, connection=0, key="pg-link-stable-intent"):
    async with f[0]() as session:
        try:
            result = await MCPOperationService(
                session, f[1], [broadcast_link_definition()]
            ).execute(
                access_token=f[2][connection],
                operation_name="add_group_broadcast_link",
                idempotency_key=key,
                payload=f[3],
            )
            await session.commit()
            return result
        except BaseException:
            await session.rollback()
            raise


async def test_six_cross_grant_retries_create_one_link_two_destinations_four_contacts(
    link_sessions,
):
    f = link_sessions
    results = await asyncio.wait_for(
        asyncio.gather(*(invoke(f, connection=i % 2) for i in range(6))), 20
    )
    assert all(result == results[0] for result in results)
    async with f[0]() as session:
        broadcast_id = uuid.UUID(f[3]["broadcast_id"])
        for model, count in [
            (ClientGroupWhatsAppBroadcastLinkModel, 1),
            (WhatsAppBroadcastRecipientModel, 2),
            (WhatsAppBroadcastSourceContactModel, 4),
        ]:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.broadcast_group_id == broadcast_id)
                )
                == count
            )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditLogModel)
                .where(
                    AuditLogModel.entity_id == f[3]["group_id"],
                    AuditLogModel.action == "application_broadcast_link_added",
                )
            )
            == 1
        )


async def test_distinct_new_intents_same_source_revision_have_one_winner(link_sessions):
    f = link_sessions
    results = await asyncio.wait_for(
        asyncio.gather(
            invoke(f, key="first-link-addition-intent"),
            invoke(f, connection=1, key="second-link-addition-intent"),
            return_exceptions=True,
        ),
        20,
    )
    assert sum(isinstance(result, dict) for result in results) == 1
    blocked = next(result for result in results if isinstance(result, BaseException))
    assert isinstance(blocked, MCPInputError) and blocked.code == "broadcast_link_revision_changed"


@pytest.mark.parametrize("change", ["source_phone", "queued_private_delivery"])
async def test_canonical_group_lock_fences_phone_and_preserves_queued_delivery(
    link_sessions, change
):
    f = link_sessions
    attempted = asyncio.Event()
    engine = f[0].kw["bind"].sync_engine

    def observe(_connection, _cursor, statement, _parameters, _context, _many):
        if "FROM client_groups" in statement and "FOR UPDATE" in statement:
            attempted.set()

    async with f[0]() as writer:
        group_id = uuid.UUID(f[3]["group_id"])
        agency_id = uuid.UUID(f[3]["agency_id"])
        broadcast_id = uuid.UUID(f[3]["broadcast_id"])
        await lock_private_delivery_group_source_snapshot(
            writer, agency_id=agency_id, group_id=group_id
        )
        if change == "source_phone":
            row = await writer.get(PassportSubmissionModel, f[4][0])
            row.staff_metadata = {"upload_phone": "9000000001"}
        else:
            writer.add(delivery(agency_id, group_id, broadcast_id, "queued"))
        await writer.flush()
        event.listen(engine, "before_cursor_execute", observe)
        waiting = asyncio.create_task(invoke(f))
        try:
            await asyncio.wait_for(attempted.wait(), 5)
            assert not waiting.done()
            await writer.commit()
            with pytest.raises(MCPInputError) as caught:
                await asyncio.wait_for(waiting, 10)
            assert caught.value.code == (
                "broadcast_link_revision_changed"
                if change == "source_phone"
                else "broadcast_link_private_delivery_pending"
            )
        finally:
            event.remove(engine, "before_cursor_execute", observe)
            if not waiting.done():
                waiting.cancel()
                await asyncio.gather(waiting, return_exceptions=True)
    async with f[0]() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ClientGroupWhatsAppBroadcastLinkModel)
                .where(ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id == broadcast_id)
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(WhatsAppBroadcastSourceContactModel)
                .where(WhatsAppBroadcastSourceContactModel.broadcast_group_id == broadcast_id)
            )
            == 0
        )
