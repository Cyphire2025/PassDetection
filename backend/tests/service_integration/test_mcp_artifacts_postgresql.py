"""Transfer acknowledgement races against isolated PostgreSQL, never business data."""

import asyncio
import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import event, func, select, text

from app.application.mcp.artifacts import MCPArtifactService
from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.credentials import MCPAuthError
from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel
from app.infrastructure.database.models import AgencyModel, AuditLogModel, ClientGroupModel
from app.infrastructure.repositories.passport_export_history_repository import (
    PassportExportHistoryRepository,
)
from tests.integration.test_mcp_artifacts import Storage, chunks
from tests.integration.test_mcp_operations import seed_identity
from tests.service_integration.test_mcp_concurrency_postgresql import mcp_sessions as mcp_sessions

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required"
    ),
]


@pytest.fixture
async def export_transfer(mcp_sessions):
    sessions, settings = mcp_sessions
    storage = Storage()
    async with sessions() as session:
        assert await session.scalar(text("SELECT to_regclass('mcp_artifacts')")) is not None
        (await session.get(MCPControlModel, 1)).enabled = True
        user, grants, tokens = await seed_identity(
            session, settings, email=f"artifact-{uuid.uuid4()}@example.test"
        )
        grants[0].capabilities = ["mcp:export"]
        agency = AgencyModel(
            id=uuid.uuid4(), name="Artifact PG fixture", email=f"{uuid.uuid4()}@example.test"
        )
        session.add(agency)
        await session.flush()
        group = ClientGroupModel(
            id=uuid.uuid4(), agency_id=agency.id, name="Artifact PG fixture", token=uuid.uuid4().hex
        )
        session.add(group)
        await session.flush()
        principal = await MCPAuthorizationService(session, settings).verify_access(tokens[0])
        await session.commit()
        history = await PassportExportHistoryRepository(session).record(
            group_id=group.id,
            agency_id=agency.id,
            export_kind="passport_excel",
            export_mode="all",
            request_id=uuid.uuid4(),
            snapshot_submission_ids=[],
            exported_submission_ids=[],
            exported_people_snapshot=[],
            created_by_user_id=user.id,
            actor_email=user.email,
        )
        service = MCPArtifactService(session, settings, storage=storage)
        result = await service.prepare_export(
            principal,
            agency_id=agency.id,
            group_id=group.id,
            purpose="passport_excel",
            filename="test.xlsx",
            body=chunks(b"generated fixture"),
            export_history_id=history.id,
        )
        await session.commit()
        row = await service.get(principal, result["artifact_id"])
        async for _ in service.stream(principal, result["artifact_id"], row):
            pass
        await session.commit()
    return sessions, settings, storage, principal, result


async def acknowledge(fixture):
    sessions, settings, storage, principal, result = fixture
    async with sessions() as session:
        response = await MCPArtifactService(session, settings, storage=storage).acknowledge(
            principal, result["artifact_id"], byte_size=result["byte_size"], sha256=result["sha256"]
        )
        await session.commit()
        return response


async def test_concurrent_acknowledgements_complete_history_once(export_transfer):
    responses = await asyncio.wait_for(
        asyncio.gather(*(acknowledge(export_transfer) for _ in range(6))), 15
    )
    assert len({response["delivered_at"] for response in responses}) == 1
    sessions, _, _, principal, _ = export_transfer
    async with sessions() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditLogModel)
                .where(
                    AuditLogModel.user_id == principal.user_id,
                    AuditLogModel.action == "passport_group_exported",
                )
            )
            == 1
        )


async def test_revocation_wins_before_waiting_delivery_ack(export_transfer):
    sessions, _, _, principal, _ = export_transfer
    attempted = asyncio.Event()
    engine = sessions.kw["bind"].sync_engine

    def observe(_connection, _cursor, statement, _parameters, _context, _many):
        if "FROM mcp_grants" in statement and "FOR UPDATE" in statement:
            attempted.set()

    async with sessions() as admin:
        grant = await admin.scalar(
            select(MCPGrantModel).where(MCPGrantModel.id == principal.grant_id).with_for_update()
        )
        event.listen(engine, "before_cursor_execute", observe)
        waiting = asyncio.create_task(acknowledge(export_transfer))
        try:
            await asyncio.wait_for(attempted.wait(), 5)
            assert not waiting.done()
            grant.revoked_at = datetime.now(UTC)
            await admin.commit()
            with pytest.raises(MCPAuthError):
                await asyncio.wait_for(waiting, 10)
        finally:
            event.remove(engine, "before_cursor_execute", observe)
            if not waiting.done():
                waiting.cancel()
                await asyncio.gather(waiting, return_exceptions=True)
    async with sessions() as session:
        row = await session.scalar(
            select(MCPArtifactModel).where(MCPArtifactModel.grant_id == principal.grant_id)
        )
        assert row.delivered_at is None
