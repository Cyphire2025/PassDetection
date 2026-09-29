"""Real PostgreSQL access addition/replacement/replay serialization evidence."""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from sqlalchemy import event, func, select

from app.application.mcp.access_changes import inspect_group_access
from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.operations import MCPDatabaseContext, MCPOperationService
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    ClientGroupModel,
    ManagerGroupAccessModel,
    UserModel,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes.admin import assign_manager_groups, assign_staff_groups
from app.presentation.api.v1.schemas.operations_schemas import AssignManagerGroupsRequest
from app.presentation.mcp.access_change_tools import access_definition
from app.presentation.mcp.invocation import MCPInputError
from tests.service_integration.test_mcp_concurrency_postgresql import mcp_sessions as mcp_sessions
from tests.service_integration.test_mcp_operations_postgresql import (
    operation_sessions as operation_sessions,
)

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required"
    ),
]


@pytest.fixture
async def access_sessions(operation_sessions):
    sessions, settings, actor_id, _, tokens = operation_sessions
    async with sessions() as session:
        agency = AgencyModel(
            id=uuid.uuid4(), name="Synthetic access", email=f"{uuid.uuid4()}@example.test"
        )
        session.add(agency)
        await session.flush()
        accounts = [
            UserModel(
                id=uuid.uuid4(),
                agency_id=agency.id,
                role=role,
                is_active=True,
                full_name="Synthetic account",
                email=f"{uuid.uuid4()}@example.test",
                hashed_password="fixture",
            )
            for role in ("agency_staff", "agency_manager")
        ]
        groups = [
            ClientGroupModel(
                id=uuid.uuid4(),
                agency_id=agency.id,
                name="Synthetic group",
                token=uuid.uuid4().hex,
                import_only=True,
            )
            for _ in range(2)
        ]
        session.add_all([*accounts, *groups])
        await session.flush()
        principal = await MCPAuthorizationService(session, settings).verify_access(
            tokens[0], "mcp:change"
        )
        payloads = []
        for account, account_type in zip(accounts, ("staff", "manager"), strict=True):
            read = await inspect_group_access(
                MCPDatabaseContext(session, principal, uuid.uuid4()),
                agency_id=agency.id,
                account_id=account.id,
                account_type=account_type,
                group_ids=[groups[0].id],
            )
            payloads.append(
                {
                    "agency_id": str(agency.id),
                    "account_id": str(account.id),
                    "group_ids": [str(groups[0].id)],
                    "expected_revision": read["access_revision"],
                }
            )
        await session.commit()
    return (
        sessions,
        settings,
        actor_id,
        tokens,
        payloads,
        [account.id for account in accounts],
        [group.id for group in groups],
    )


async def invoke(fixture, *, index=0, connection=0, key="pg-add-access-stable-request"):
    sessions, settings, _, tokens, payloads, _, _ = fixture
    name = "add_staff_group_access" if index == 0 else "add_manager_group_access"
    async with sessions() as session:
        try:
            result = await MCPOperationService(
                session, settings, [access_definition(name)]
            ).execute(
                access_token=tokens[connection],
                operation_name=name,
                idempotency_key=key,
                payload=payloads[index],
            )
            await session.commit()
            return result
        except BaseException:
            await session.rollback()
            raise


@pytest.mark.parametrize("index", [0, 1])
async def test_six_cross_connection_retries_add_one_assignment_and_business_audit(
    access_sessions, index
):
    f = access_sessions
    results = await asyncio.wait_for(
        asyncio.gather(*(invoke(f, index=index, connection=n % 2) for n in range(6))), 20
    )
    assert all(row == results[0] for row in results)
    async with f[0]() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ManagerGroupAccessModel)
                .where(ManagerGroupAccessModel.manager_id == f[5][index])
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditLogModel)
                .where(
                    AuditLogModel.entity_id == str(f[5][index]),
                    AuditLogModel.action == "application_group_access_added",
                )
            )
            == 1
        )


@pytest.mark.parametrize("index", [0, 1])
async def test_distinct_keys_same_revision_have_one_winner(access_sessions, index):
    f = access_sessions
    results = await asyncio.wait_for(
        asyncio.gather(
            invoke(f, index=index, key="pg-first-access-intent"),
            invoke(f, index=index, connection=1, key="pg-second-access-intent"),
            return_exceptions=True,
        ),
        20,
    )
    assert sum(isinstance(result, dict) for result in results) == 1
    blocked = next(result for result in results if isinstance(result, BaseException))
    assert isinstance(blocked, MCPInputError) and blocked.code == "group_access_revision_changed"


@pytest.mark.parametrize("index", [0, 1])
async def test_website_replacement_blocks_addition_until_commit_then_revision_conflicts(
    access_sessions, index
):
    f = access_sessions
    attempted = asyncio.Event()
    engine = f[0].kw["bind"].sync_engine

    def observe(_connection, _cursor, statement, _parameters, _context, _many):
        if "FROM users" in statement and "FOR UPDATE" in statement:
            attempted.set()

    async with f[0]() as website:
        actor = await UserRepository(website).get_by_id(f[2])
        body = AssignManagerGroupsRequest(group_ids=[f[6][1]])
        if index == 0:
            await assign_staff_groups(
                staff_id=f[5][index], body=body, current_user=actor, session=website
            )
        else:
            await assign_manager_groups(
                manager_id=f[5][index], body=body, current_user=actor, session=website
            )
        event.listen(engine, "before_cursor_execute", observe)
        waiting = asyncio.create_task(invoke(f, index=index))
        try:
            await asyncio.wait_for(attempted.wait(), 5)
            assert not waiting.done()
            await website.commit()
            with pytest.raises(MCPInputError, match="changed"):
                await asyncio.wait_for(waiting, 10)
        finally:
            event.remove(engine, "before_cursor_execute", observe)
            if not waiting.done():
                waiting.cancel()
                await asyncio.gather(waiting, return_exceptions=True)
    async with f[0]() as session:
        assert list(
            (
                await session.scalars(
                    select(ManagerGroupAccessModel.group_id).where(
                        ManagerGroupAccessModel.manager_id == f[5][index]
                    )
                )
            ).all()
        ) == [f[6][1]]
