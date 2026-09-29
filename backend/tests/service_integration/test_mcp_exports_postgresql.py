"""Export generation races in an isolated PostgreSQL schema with synthetic records."""

import asyncio
import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import event, func, select

from app.application.mcp.artifacts import ArtifactError, MCPArtifactService
from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.export_capacity import ExportCapacityBusy
from app.application.mcp.exports import (
    ExcelExportRequest,
    MCPExcelExportService,
    excel_export_operation,
)
from app.application.mcp.operations import MCPOperationError, MCPOperationService
from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    PassportExportHistoryModel,
    PassportSubmissionModel,
)
from app.presentation.mcp.export_tools import excel_support
from tests.integration.test_mcp_artifacts import Storage
from tests.integration.test_mcp_operations import seed_identity
from tests.service_integration.test_mcp_concurrency_postgresql import mcp_sessions as mcp_sessions

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required"
    ),
]


@pytest.fixture
async def queued_export(mcp_sessions):
    sessions, settings = mcp_sessions
    storage = Storage()
    async with sessions() as session:
        (await session.get(MCPControlModel, 1)).enabled = True
        user, grants, tokens = await seed_identity(
            session, settings, email=f"export-{uuid.uuid4()}@example.test"
        )
        for grant in grants:
            grant.capabilities = ["mcp:export"]
        agency = AgencyModel(
            id=uuid.uuid4(), name="Synthetic export", email=f"{uuid.uuid4()}@example.test"
        )
        session.add(agency)
        await session.flush()
        group = ClientGroupModel(
            id=uuid.uuid4(), agency_id=agency.id, name="Synthetic trip", token=uuid.uuid4().hex
        )
        session.add(group)
        await session.flush()
        passport = PassportSubmissionModel(
            id=uuid.uuid4(),
            agency_id=agency.id,
            group_id=group.id,
            client_name="Synthetic passenger",
            image_s3_key="private/never-read",
            status="staff_approved",
            confirmed_fields={"passport_number": "SYNTHETIC"},
        )
        session.add(passport)
        await session.commit()
        principal = await MCPAuthorizationService(session, settings).verify_access(tokens[0])
        await session.commit()
        support = excel_support()
        definition = excel_export_operation(settings, support)
        service = MCPExcelExportService(
            session,
            settings,
            support,
            artifacts=MCPArtifactService(session, settings, storage=storage),
        )
        request = ExcelExportRequest(agency_id=agency.id, group_ids=[group.id])
        observed = await service.inspect(principal, request)
        receipt = await MCPOperationService(session, settings, [definition]).execute(
            access_token=tokens[0],
            operation_name=definition.policy.name,
            idempotency_key=uuid.uuid4().hex,
            payload={
                "export": request.model_dump(mode="json"),
                "expected_revision": observed["expected_revision"],
            },
        )
        await session.commit()
        return (
            sessions,
            settings,
            storage,
            tokens,
            grants[0].id,
            passport.id,
            uuid.UUID(receipt["operation_id"]),
        )


async def generate(fixture, index=0):
    sessions, settings, storage, tokens, _, _, operation_id = fixture
    async with sessions() as session:
        result = await MCPExcelExportService(
            session,
            settings,
            excel_support(),
            artifacts=MCPArtifactService(session, settings, storage=storage),
        ).generate(access_token=tokens[index], operation_id=operation_id)
        await session.commit()
        return result


async def test_two_connections_generate_one_history_and_workbook(queued_export):
    results = await asyncio.wait_for(
        asyncio.gather(generate(queued_export), generate(queued_export, 1), return_exceptions=True),
        15,
    )
    # Shared container admission now rejects one contender before bulk reads.
    # Retrying that SAME saved intent from its second grant recovers one file.
    busy = [index for index, result in enumerate(results) if isinstance(result, ExportCapacityBusy)]
    assert len(busy) == 1
    results[busy[0]] = await generate(queued_export, busy[0])
    first, second = results
    assert first["artifact"]["sha256"] == second["artifact"]["sha256"]
    assert first["artifact"]["artifact_id"] != second["artifact"]["artifact_id"]
    sessions, _, storage, _, _, _, operation_id = queued_export
    assert len(storage.objects) == 1
    async with sessions() as session:
        histories = select(PassportExportHistoryModel.id).where(
            PassportExportHistoryModel.request_id == operation_id
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(PassportExportHistoryModel)
                .where(PassportExportHistoryModel.request_id == operation_id)
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(MCPArtifactModel)
                .where(MCPArtifactModel.export_history_id.in_(histories))
            )
            == 1
        )


async def test_passport_correction_wins_before_generation_snapshot(queued_export):
    sessions, _, storage, _, _, passport_id, _ = queued_export
    attempted = asyncio.Event()
    engine = sessions.kw["bind"].sync_engine

    def observe(_conn, _cursor, statement, _parameters, _context, _many):
        if "FROM passport_submissions" in statement and "FOR UPDATE NOWAIT" in statement:
            attempted.set()

    async with sessions() as editor:
        row = await editor.scalar(
            select(PassportSubmissionModel)
            .where(PassportSubmissionModel.id == passport_id)
            .with_for_update()
        )
        event.listen(engine, "before_cursor_execute", observe)
        waiting = asyncio.create_task(generate(queued_export))
        try:
            await asyncio.wait_for(attempted.wait(), 5)
            # A legacy writer may hold passport then update group via a trigger.
            # NOWAIT releases the export's earlier group lock instead of deadlocking.
            with pytest.raises(ArtifactError, match="busy"):
                await asyncio.wait_for(waiting, 5)
            row.confirmed_fields = {"passport_number": "CORRECTED"}
            await editor.commit()
            with pytest.raises(MCPOperationError, match="export_revision_changed"):
                await asyncio.wait_for(generate(queued_export), 10)
            assert not storage.objects
        finally:
            event.remove(engine, "before_cursor_execute", observe)
            if not waiting.done():
                waiting.cancel()
                await asyncio.gather(waiting, return_exceptions=True)


async def test_revocation_wins_before_generation_barrier(queued_export):
    sessions, _, storage, _, grant_id, _, _ = queued_export
    attempted = asyncio.Event()
    engine = sessions.kw["bind"].sync_engine

    def observe(_conn, _cursor, statement, _parameters, _context, _many):
        if "FROM mcp_grants" in statement and "FOR UPDATE" in statement:
            attempted.set()

    async with sessions() as admin:
        row = await admin.scalar(
            select(MCPGrantModel).where(MCPGrantModel.id == grant_id).with_for_update()
        )
        event.listen(engine, "before_cursor_execute", observe)
        waiting = asyncio.create_task(generate(queued_export))
        try:
            await asyncio.wait_for(attempted.wait(), 5)
            assert not waiting.done()
            row.revoked_at = datetime.now(UTC)
            await admin.commit()
            with pytest.raises(MCPAuthError):
                await asyncio.wait_for(waiting, 10)
            assert not storage.objects
        finally:
            event.remove(engine, "before_cursor_execute", observe)
            if not waiting.done():
                waiting.cancel()
                await asyncio.gather(waiting, return_exceptions=True)
