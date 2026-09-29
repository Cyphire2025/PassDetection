"""Image ZIP source locks and cross-connection receipt recovery on PostgreSQL."""

import asyncio
import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.application.mcp.artifacts import ArtifactError, MCPArtifactService
from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.image_exports import (
    ImageExportRequest,
    MCPImageExportService,
    image_export_operation,
)
from app.application.mcp.operations import MCPOperationError, MCPOperationService
from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    PassportExportHistoryModel,
    PassportImageCropModel,
    PassportSubmissionModel,
)
from app.presentation.api.v1.routes.document_distribution_match_source import (
    _read_linked_document_match_source,
)
from app.presentation.api.v1.routes.passport_routes.image_exports import image_export_support
from tests.integration.test_mcp_artifacts import Storage
from tests.integration.test_mcp_image_exports import Images
from tests.integration.test_mcp_operations import seed_identity
from tests.service_integration.test_mcp_concurrency_postgresql import mcp_sessions as mcp_sessions

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required"
    ),
]


@pytest.fixture
async def queued_images(mcp_sessions):
    sessions, settings = mcp_sessions
    images, storage = Images(), Storage()
    images.retain("original/front.png", "red")
    images.retain("original/back.png", "blue")
    images.retain("crop/derived.jpg", "green")
    async with sessions() as session:
        (await session.get(MCPControlModel, 1)).enabled = True
        user, grants, tokens = await seed_identity(
            session, settings, email=f"images-{uuid.uuid4()}@example.test"
        )
        for grant in grants:
            grant.capabilities = ["mcp:export"]
        agency = AgencyModel(
            id=uuid.uuid4(), name="Synthetic image export", email=f"{uuid.uuid4()}@example.test"
        )
        session.add(agency)
        await session.flush()
        group = ClientGroupModel(
            id=uuid.uuid4(),
            agency_id=agency.id,
            name="Synthetic image trip",
            token=uuid.uuid4().hex,
        )
        session.add(group)
        await session.flush()
        passport = PassportSubmissionModel(
            id=uuid.uuid4(),
            agency_id=agency.id,
            group_id=group.id,
            client_name="Synthetic image traveller",
            image_s3_key="original/front.png",
            passport_back_s3_key="original/back.png",
            status="staff_approved",
            confirmed_fields={"passport_number": "SYNTHETIC"},
        )
        session.add(passport)
        await session.flush()
        crop = PassportImageCropModel(
            submission_id=passport.id,
            image_type="passport_front",
            source_storage_key=passport.image_s3_key,
            derived_storage_key="crop/derived.jpg",
            active=True,
            crop_x=0,
            crop_y=0,
            crop_width=1,
            crop_height=1,
            rotation_degrees=0,
            sharpness=1,
            source_width=64,
            source_height=64,
            revision=1,
            updated_by_user_id=user.id,
        )
        session.add(crop)
        await session.commit()
        principal = await MCPAuthorizationService(session, settings).verify_access(tokens[0])
        await session.commit()
        support = image_export_support()
        definition = image_export_operation(
            settings, support, linked_source=_read_linked_document_match_source
        )
        service = MCPImageExportService(
            session,
            settings,
            support,
            linked_source=_read_linked_document_match_source,
            artifacts=MCPArtifactService(session, settings, storage=storage),
            image_storage=images,
        )
        request = ImageExportRequest(agency_id=agency.id, group_id=group.id)
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
            images,
            storage,
            tokens,
            grants[0].id,
            crop.id,
            uuid.UUID(receipt["operation_id"]),
        )


async def generate(f, index=0, independent_worker=False):
    sessions, settings, images, storage, tokens, _, _, operation_id = f
    async with sessions() as session:
        service = MCPImageExportService(
            session,
            settings,
            image_export_support(),
            linked_source=_read_linked_document_match_source,
            artifacts=MCPArtifactService(session, settings, storage=storage),
            image_storage=images,
        )
        # Independent workers have distinct process-local admission limits. Exercise
        # their shared SQL serialization directly, retaining the actual service body.
        generator = service._generate if independent_worker else service.generate
        result = await generator(access_token=tokens[index], operation_id=operation_id)
        await session.commit()
        return result


async def test_two_workers_recover_one_image_archive_and_history(queued_images):
    f = queued_images
    entered, release = asyncio.Event(), asyncio.Event()
    put = f[3].put_transfer

    async def slow_put(*args, **kwargs):
        entered.set()
        await release.wait()
        return await put(*args, **kwargs)

    f[3].put_transfer = slow_put
    first = asyncio.create_task(generate(f, independent_worker=True))
    await asyncio.wait_for(entered.wait(), 10)
    second = asyncio.create_task(generate(f, 1, independent_worker=True))
    try:
        await asyncio.sleep(0.05)
        assert not second.done()
        release.set()
        results = await asyncio.wait_for(asyncio.gather(first, second), 10)
    finally:
        release.set()
        await asyncio.gather(first, second, return_exceptions=True)
    assert results[0]["artifact"]["sha256"] == results[1]["artifact"]["sha256"]
    assert results[0]["artifact"]["artifact_id"] != results[1]["artifact"]["artifact_id"]
    assert len(f[3].objects) == 1
    async with f[0]() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(PassportExportHistoryModel)
                .where(PassportExportHistoryModel.request_id == f[-1])
            )
            == 1
        )


async def test_crop_writer_returns_busy_then_invalidates_saved_revision(queued_images):
    f = queued_images
    async with f[0]() as editor:
        crop = await editor.scalar(
            select(PassportImageCropModel)
            .where(PassportImageCropModel.id == f[6])
            .with_for_update()
        )
        with pytest.raises(ArtifactError) as busy:
            await asyncio.wait_for(generate(f), 5)
        assert busy.value.status_code == 503
        crop.revision += 1
        await editor.commit()
    with pytest.raises(MCPOperationError, match="export_revision_changed"):
        await generate(f)
    assert not f[3].objects


async def test_revocation_before_generation_prevents_source_reads(queued_images):
    f = queued_images
    async with f[0]() as session:
        grant = await session.get(MCPGrantModel, f[5])
        grant.revoked_at = datetime.now(UTC)
        await session.commit()
    with pytest.raises(MCPAuthError):
        await generate(f)
    assert not f[2].read_sizes and not f[3].objects
