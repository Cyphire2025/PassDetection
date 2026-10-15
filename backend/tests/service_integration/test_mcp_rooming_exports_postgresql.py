"""Hotel workbook serialization and current allocation/check-in fences on PostgreSQL."""

import asyncio
import os
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.application.mcp.artifacts import ArtifactError, MCPArtifactService
from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.operations import MCPOperationError
from app.application.mcp.rooming_exports import MCPRoomingExportService
from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    PassportExportHistoryModel,
    RoomingCheckinModel,
)
from app.presentation.api.v1.routes.rooming import rooming_excel_support
from tests.integration.test_mcp_artifacts import Storage
from tests.integration.test_mcp_operations import seed_identity
from tests.integration.test_mcp_rooming_exports import queue, seed
from tests.service_integration.test_mcp_concurrency_postgresql import mcp_sessions as mcp_sessions

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required"
    ),
]


@pytest.fixture
async def rooming(mcp_sessions):
    sessions, settings = mcp_sessions
    storage = Storage()
    async with sessions() as session:
        (await session.get(MCPControlModel, 1)).enabled = True
        user, grants, tokens = await seed_identity(
            session, settings, enable_write_policy=True, email=f"rooming-{uuid.uuid4()}@example.test"
        )
        for grant in grants:
            grant.capabilities = ["mcp:export"]
        agency = AgencyModel(
            id=uuid.uuid4(), name="Synthetic rooming", email=f"{uuid.uuid4()}@example.test"
        )
        session.add(agency)
        await session.flush()
        group = ClientGroupModel(
            id=uuid.uuid4(), agency_id=agency.id, name="Rooming trip", token=uuid.uuid4().hex
        )
        session.add(group)
        await session.commit()
        principal = await MCPAuthorizationService(session, settings).verify_access(tokens[0])
        await session.commit()
        f = SimpleNamespace(
            session=session,
            settings=settings,
            user=user,
            agency=agency,
            group=group,
            principal=principal,
            token=tokens[0],
            storage=storage,
            service=MCPArtifactService(session, settings, storage=storage),
        )
        await seed(f)
        receipt, _, _ = await queue(f, "checkins")
        return SimpleNamespace(
            sessions=sessions,
            settings=settings,
            storage=storage,
            tokens=tokens,
            operation_id=uuid.UUID(receipt["operation_id"]),
            user_id=user.id,
            checkin_id=f.checkin.id,
            grant_id=grants[0].id,
        )


async def generate(f, index=0):
    async with f.sessions() as session:
        service = MCPRoomingExportService(
            session,
            f.settings,
            rooming_excel_support(),
            artifacts=MCPArtifactService(session, f.settings, storage=f.storage),
        )
        # Separate containers have independent kernel namespaces; test the DB barrier directly.
        result = await service._generate(access_token=f.tokens[index], operation_id=f.operation_id)
        await session.commit()
        return result


async def test_independent_workers_recover_one_workbook_without_history(rooming):
    f = rooming
    one, two = await asyncio.wait_for(asyncio.gather(generate(f), generate(f, 1)), 15)
    assert one["artifact"]["sha256"] == two["artifact"]["sha256"]
    assert one["artifact"]["artifact_id"] != two["artifact"]["artifact_id"]
    assert len(f.storage.objects) == 1
    async with f.sessions() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(MCPArtifactModel)
                .where(MCPArtifactModel.user_id == f.user_id)
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(PassportExportHistoryModel)
                .where(PassportExportHistoryModel.created_by_user_id == f.user_id)
            )
            == 0
        )


async def test_old_checkin_writer_is_busy_then_changed_revision_blocks(rooming):
    f = rooming
    async with f.sessions() as writer:
        checkin = await writer.scalar(
            select(RoomingCheckinModel)
            .where(RoomingCheckinModel.id == f.checkin_id)
            .with_for_update()
        )
        with pytest.raises(ArtifactError, match="busy"):
            await generate(f)
        checkin.remarks = "Changed after saved inspection"
        await writer.commit()
    with pytest.raises(MCPOperationError, match="export_revision_changed"):
        await generate(f)
    assert not f.storage.objects


async def test_revoked_connection_cannot_start_generation(rooming):
    f = rooming
    async with f.sessions() as session:
        grant = await session.get(MCPGrantModel, f.grant_id)
        grant.revoked_at = datetime.now(UTC)
        await session.commit()
    with pytest.raises(MCPAuthError):
        await generate(f)
    assert not f.storage.objects
