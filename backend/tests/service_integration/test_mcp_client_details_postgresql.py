"""Real PostgreSQL correction serialization; isolated fixtures, no schema cleanup."""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, text

from app.application.mcp.client_detail_changes import CLIENT_DETAIL_POLICY, client_detail_operation
from app.application.mcp.operations import MCPOperationError, MCPOperationService
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.mcp_record_revision_models import MCPRecordRevisionModel
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    ClientGroupModel,
    PassportSubmissionModel,
)
from app.presentation.mcp.client_detail_tools import validate_client_detail_changes
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
async def correction_sessions(operation_sessions):
    sessions, settings, _, _, tokens = operation_sessions
    async with sessions() as session:
        assert (
            await session.scalar(text("SELECT to_regclass('mcp_record_revisions')")) is not None
        ), "Apply the revision history migration before this lane"
        agency = AgencyModel(
            id=uuid.uuid4(), name="Correction fixture", email=f"{uuid.uuid4()}@example.test"
        )
        session.add(agency)
        await session.flush()
        group = ClientGroupModel(
            id=uuid.uuid4(),
            agency_id=agency.id,
            name="Correction fixture",
            token=uuid.uuid4().hex,
            status="active",
        )
        session.add(group)
        await session.flush()
        submission = PassportSubmissionModel(
            id=uuid.uuid4(),
            agency_id=agency.id,
            group_id=group.id,
            client_name="Synthetic original",
            client_email="original@example.com",
            client_phone="+919876543210",
            status="ai_approved",
            extraction_status="extraction_complete",
            image_s3_key="synthetic/retained.jpg",
            extracted_fields={"passport_number": "PG-PRESERVE"},
            updated_at=datetime.now(UTC),
        )
        session.add(submission)
        await session.flush()
        payload = {
            "submission_id": str(submission.id),
            "changes": {
                "expected_updated_at": submission.updated_at.isoformat(),
                "client_email": "first@example.com",
            },
        }
        await session.commit()
    return sessions, settings, tokens, submission.id, payload


async def invoke(fixture, *, connection=0, key="pg-correction-key-001", email="first@example.com"):
    sessions, settings, tokens, _, original = fixture
    async with sessions() as session:
        service = MCPOperationService(
            session, settings, [client_detail_operation(validate_client_detail_changes)]
        )
        try:
            result = await service.execute(
                access_token=tokens[connection],
                operation_name=CLIENT_DETAIL_POLICY.name,
                idempotency_key=key,
                payload={**original, "changes": {**original["changes"], "client_email": email}},
            )
            await session.commit()
            return result
        except BaseException:
            await session.rollback()
            raise


async def assert_one_correction(fixture):
    async with fixture[0]() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(MCPRecordRevisionModel)
                .where(MCPRecordRevisionModel.entity_id == fixture[3])
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditLogModel)
                .where(
                    AuditLogModel.entity_id == str(fixture[3]),
                    AuditLogModel.action == "passport_client_details_corrected",
                )
            )
            == 1
        )
        submission = await session.get(PassportSubmissionModel, fixture[3])
        assert submission.extracted_fields == {"passport_number": "PG-PRESERVE"}
        assert submission.image_s3_key == "synthetic/retained.jpg"


async def test_concurrent_identical_correction_across_connections_has_one_history(
    correction_sessions,
):
    fixture = correction_sessions
    results = await asyncio.wait_for(
        asyncio.gather(*(invoke(fixture, connection=index % 2) for index in range(6))), 15
    )
    assert all(result == results[0] for result in results)
    await assert_one_correction(fixture)


async def test_two_intended_edits_of_same_revision_allow_only_one_writer(correction_sessions):
    fixture = correction_sessions
    results = await asyncio.wait_for(
        asyncio.gather(
            invoke(fixture, connection=0, key="pg-different-edit-001", email="first@example.com"),
            invoke(fixture, connection=1, key="pg-different-edit-002", email="second@example.com"),
            return_exceptions=True,
        ),
        15,
    )
    success = [result for result in results if isinstance(result, dict)]
    failure = [result for result in results if isinstance(result, MCPOperationError)]
    assert len(success) == len(failure) == 1
    assert failure[0].code == "client_details_changed_or_unavailable"
    await assert_one_correction(fixture)
    async with fixture[0]() as session:
        revisions = list(
            (
                await session.scalars(
                    select(MCPRecordRevisionModel).where(
                        MCPRecordRevisionModel.entity_id == fixture[3]
                    )
                )
            ).all()
        )
        revision = revisions[0]
        assert revision.before_values["client_email"]["direct"] == "original@example.com"
        assert (
            await session.scalar(
                select(func.count())
                .select_from(MCPOperationModel)
                .where(MCPOperationModel.id == revision.operation_id)
            )
            == 1
        )
