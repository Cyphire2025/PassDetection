"""Opt-in PostgreSQL uniqueness/locking evidence; uses only isolated test resources."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import event, func, select, text

from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.group_changes import CREATE_GROUP_POLICY, group_creation_operation
from app.application.mcp.operations import MCPOperationError, MCPOperationService
from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    ClientGroupModel,
    UserModel,
    UserSecurityStateModel,
)
from app.presentation.mcp.group_change_tools import validate_group_creation
from tests.integration.test_mcp_operations import KEY, POLICY, create_agency, seed_identity, service
from tests.service_integration.test_mcp_concurrency_postgresql import mcp_sessions as mcp_sessions

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required"
    ),
]


@pytest.fixture
async def operation_sessions(mcp_sessions):
    # The shared fixture enforces local/CI host and database-name guards. This
    # lane does not create/drop schemas, truncate tables, or touch business data.
    sessions, settings = mcp_sessions
    async with sessions() as session:
        assert await session.scalar(text("SELECT to_regclass('mcp_operations')")) is not None, (
            "Apply the MCP operation migration before this lane"
        )
        control = await session.get(MCPControlModel, 1)
        assert control is not None
        control.enabled = True
        user, grants, tokens = await seed_identity(
            session, settings, email=f"operations-{uuid.uuid4()}@example.test"
        )
        user_id, grant_ids = user.id, [grant.id for grant in grants]
        await session.commit()
    return sessions, settings, user_id, grant_ids, tokens


async def invoke(fixture, token_index, callback, *, payload=None):
    sessions, settings, _, _, tokens = fixture
    async with sessions() as session:
        try:
            result = await service((session, settings, None, None, tokens), callback).execute(
                access_token=tokens[token_index],
                operation_name=POLICY.name,
                idempotency_key=KEY,
                payload={"name": "PG fixture"} if payload is None else payload,
            )
        except BaseException:
            await session.rollback()
            raise
        await session.commit()
        return result


@pytest.mark.parametrize("same_connection", [False, True])
async def test_concurrent_claims_replay_one_committed_business_write(
    operation_sessions, same_connection
):
    fixture = operation_sessions
    entered, finish = asyncio.Event(), asyncio.Event()
    executed = 0

    async def callback(context, payload):
        nonlocal executed
        executed += 1
        result = await create_agency(context, payload)
        entered.set()
        await asyncio.wait_for(finish.wait(), 10)
        return result

    winner = asyncio.create_task(invoke(fixture, 0, callback))
    await asyncio.wait_for(entered.wait(), 5)
    attempted = asyncio.Event()
    engine = fixture[0].kw["bind"].sync_engine

    def observe_wait(_connection, _cursor, statement, _parameters, _context, _many):
        if (
            same_connection
            and "FROM mcp_grants" in statement
            and "FOR UPDATE" in statement
            or not same_connection
            and statement.startswith("INSERT INTO mcp_operations")
        ):
            attempted.set()

    event.listen(engine, "before_cursor_execute", observe_wait)
    waiting = [
        asyncio.create_task(invoke(fixture, 0 if same_connection else 1, callback))
        for _ in range(4)
    ]
    try:
        await asyncio.wait_for(attempted.wait(), 5)
        assert not any(task.done() for task in waiting)
        finish.set()
        results = await asyncio.wait_for(asyncio.gather(winner, *waiting), 15)
    finally:
        finish.set()
        event.remove(engine, "before_cursor_execute", observe_wait)
        for task in [winner, *waiting]:
            if not task.done():
                task.cancel()
        await asyncio.gather(winner, *waiting, return_exceptions=True)
    assert executed == 1 and all(item == results[0] for item in results)
    async with fixture[0]() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(MCPOperationModel)
                .where(MCPOperationModel.user_id == fixture[2])
            )
            == 1
        )
        assert (
            await session.get(AgencyModel, uuid.UUID(results[0]["data"]["agency_id"])) is not None
        )


async def test_waiting_claim_wins_after_original_transaction_rolls_back(operation_sessions):
    fixture = operation_sessions
    entered, abort, contender_insert = asyncio.Event(), asyncio.Event(), asyncio.Event()
    rolled_back_id = None

    async def failing(context, payload):
        nonlocal rolled_back_id
        result = await create_agency(context, payload)
        rolled_back_id = uuid.UUID(result.data["agency_id"])
        entered.set()
        await asyncio.wait_for(abort.wait(), 10)
        raise RuntimeError("synthetic transaction failure")

    first = asyncio.create_task(invoke(fixture, 0, failing))
    await asyncio.wait_for(entered.wait(), 5)
    engine = fixture[0].kw["bind"].sync_engine

    def observe_insert(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("INSERT INTO mcp_operations"):
            contender_insert.set()

    event.listen(engine, "before_cursor_execute", observe_insert)
    second = asyncio.create_task(invoke(fixture, 1, create_agency))
    try:
        await asyncio.wait_for(contender_insert.wait(), 5)
        assert not second.done()
        abort.set()
        with pytest.raises(RuntimeError, match="synthetic transaction failure"):
            await first
        result = await asyncio.wait_for(second, 10)
    finally:
        abort.set()
        event.remove(engine, "before_cursor_execute", observe_insert)
        await asyncio.gather(first, second, return_exceptions=True)
    async with fixture[0]() as session:
        assert await session.get(AgencyModel, rolled_back_id) is None
        assert await session.get(AgencyModel, uuid.UUID(result["data"]["agency_id"])) is not None
        assert (
            await session.scalar(
                select(func.count())
                .select_from(MCPOperationModel)
                .where(MCPOperationModel.user_id == fixture[2])
            )
            == 1
        )


async def test_concurrent_changed_payload_cannot_reuse_the_winner_receipt(operation_sessions):
    fixture = operation_sessions
    results = await asyncio.gather(
        invoke(fixture, 0, create_agency, payload={"name": "Payload A"}),
        invoke(fixture, 1, create_agency, payload={"name": "Payload B"}),
        return_exceptions=True,
    )
    assert sum(isinstance(item, dict) for item in results) == 1
    errors = [item for item in results if isinstance(item, MCPOperationError)]
    assert len(errors) == 1 and errors[0].code == "idempotency_conflict"


async def test_actual_group_creation_replays_one_group_and_business_audit(operation_sessions):
    sessions, settings, _, _, tokens = operation_sessions
    agency_id, owner_id = uuid.uuid4(), uuid.uuid4()
    async with sessions() as session:
        session.add(
            AgencyModel(
                id=agency_id, name="MCP PG group fixture", email=f"agency-{agency_id}@example.test"
            )
        )
        await session.flush()
        session.add(
            UserModel(
                id=owner_id,
                email=f"owner-{owner_id}@example.test",
                full_name="Group fixture owner",
                hashed_password="fixture",
                role="agency_staff",
                is_active=True,
                agency_id=agency_id,
            )
        )
        await session.commit()
    payload = {
        "agency_id": str(agency_id),
        "owner_user_id": str(owner_id),
        "name": "Isolated PG group",
        "destination": "Japan",
        "travel_date": "2026-10-10",
        "return_date": "2026-10-18",
        "timezone": "Asia/Tokyo",
    }

    async def run(index):
        async with sessions() as session:
            receipt = await MCPOperationService(
                session, settings, [group_creation_operation(validate_group_creation)]
            ).execute(
                access_token=tokens[index],
                operation_name=CREATE_GROUP_POLICY.name,
                idempotency_key="real-group-creation-race",
                payload=payload,
            )
            await session.commit()
            return receipt

    results = await asyncio.wait_for(asyncio.gather(*(run(index % 2) for index in range(6))), 15)
    assert all(item == results[0] for item in results)
    async with sessions() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ClientGroupModel)
                .where(ClientGroupModel.agency_id == agency_id)
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditLogModel)
                .where(
                    AuditLogModel.agency_id == agency_id,
                    AuditLogModel.action == "client_group_created",
                )
            )
            == 1
        )


@pytest.mark.parametrize("barrier", ["control", "grant", "role", "security"])
async def test_authority_change_winning_lock_fences_waiting_operation(operation_sessions, barrier):
    fixture = operation_sessions
    sessions, settings, user_id, grant_ids, tokens = fixture
    attempted = asyncio.Event()
    called = False

    class ObservedAuthorization(MCPAuthorizationService):
        async def require_grant(self, grant_id, *, lock=False):
            if lock:
                attempted.set()
            return await super().require_grant(grant_id, lock=lock)

    async def callback(context, payload):
        nonlocal called
        called = True
        return await create_agency(context, payload)

    async with sessions() as changer, sessions() as contender:
        if barrier == "control":
            row = await changer.scalar(
                select(MCPControlModel).where(MCPControlModel.id == 1).with_for_update()
            )
            row.enabled = False
        elif barrier == "grant":
            row = await changer.scalar(
                select(MCPGrantModel).where(MCPGrantModel.id == grant_ids[0]).with_for_update()
            )
            row.revoked_at = datetime.now(UTC)
        elif barrier == "role":
            row = await changer.scalar(
                select(UserModel).where(UserModel.id == user_id).with_for_update()
            )
            row.role = "agency_admin"
        else:
            row = await changer.scalar(
                select(UserSecurityStateModel)
                .where(UserSecurityStateModel.user_id == user_id)
                .with_for_update()
            )
            row.session_version += 1
        svc = service((contender, settings, None, None, tokens), callback)
        svc.authorization = ObservedAuthorization(contender, settings)
        pending = asyncio.create_task(
            svc.execute(
                access_token=tokens[0],
                operation_name=POLICY.name,
                idempotency_key=KEY,
                payload={"name": "Must never be created"},
            )
        )
        try:
            await asyncio.wait_for(attempted.wait(), 5)
            assert not pending.done()
            await changer.commit()
            with pytest.raises(MCPAuthError):
                await asyncio.wait_for(pending, 5)
        finally:
            await changer.rollback()
            if not pending.done():
                pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            await contender.rollback()
    assert not called
    async with sessions() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(MCPOperationModel)
                .where(MCPOperationModel.user_id == user_id)
            )
            == 0
        )
