"""Canonical tracking XLSX parity, exact scopes and durable protected delivery."""

import asyncio
import threading
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.application.mcp.artifacts import ArtifactError
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.operations import MCPOperationError, MCPOperationService
from app.application.mcp.tracking_exports import (
    MCPTrackingExportService,
    TrackingExportRequest,
    tracking_export_operation,
)
from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
from app.infrastructure.database.mcp_models import MCPGrantModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportExportHistoryModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes.passport_routes.excel_exports import (
    export_whatsapp_tracking_by_group,
    tracking_excel_support,
)
from tests.integration.test_mcp_artifacts import artifacts as artifacts
from tests.integration.test_mcp_exports import downloaded, person, values


async def seed(f):
    broadcast = WhatsAppBroadcastGroupModel(
        id=uuid.uuid4(), agency_id=f.agency.id, name="Tracking fixture"
    )
    f.session.add(broadcast)
    await f.session.flush()
    link = ClientGroupWhatsAppBroadcastLinkModel(
        id=uuid.uuid4(),
        agency_id=f.agency.id,
        client_group_id=f.group.id,
        broadcast_group_id=broadcast.id,
    )
    recipients = [
        WhatsAppBroadcastRecipientModel(
            id=uuid.uuid4(),
            agency_id=f.agency.id,
            broadcast_group_id=broadcast.id,
            name=f"Synthetic Person {i}",
            phone_number=f"+91900000000{i}",
            normalized_phone_number=f"+91900000000{i}",
            imported_fields={"Zone": "West", "Office": "Pune"},
        )
        for i in (1, 2)
    ]
    passengers = [person(f, 1), person(f, 3)]
    passengers[0].client_phone = "+919000000001"
    passengers[1].client_phone = "+919000000003"
    f.session.add_all([link, *recipients, *passengers])
    await f.session.commit()
    f.broadcast, f.link, f.recipients, f.passengers = broadcast, link, recipients, passengers
    return f


def service(f):
    return MCPTrackingExportService(
        f.session, f.settings, tracking_excel_support(), artifacts=f.service
    )


async def queue(f, request=None, key=None):
    request = request or TrackingExportRequest(agency_id=f.agency.id, group_id=f.group.id)
    observed = await service(f).inspect(f.principal, request)
    definition = tracking_export_operation(f.settings, tracking_excel_support())
    payload = {
        "export": request.model_dump(mode="json"),
        "expected_revision": observed["expected_revision"],
    }
    key = key or uuid.uuid4().hex
    receipt = await MCPOperationService(f.session, f.settings, [definition]).execute(
        access_token=f.token,
        operation_name=definition.policy.name,
        idempotency_key=key,
        payload=payload,
    )
    await f.session.commit()
    return receipt, key, payload


async def generate(f, receipt, token=None):
    result = await service(f).generate(
        access_token=token or f.token, operation_id=uuid.UUID(receipt["operation_id"])
    )
    await f.session.commit()
    return result


@pytest.mark.parametrize(
    "status",
    [
        "all",
        "submitted",
        "not_submitted",
        "multiple_submissions",
        "needs_review",
        "unmatched_submission",
        "replacement",
        "rejected_upload",
    ],
)
async def test_each_website_filter_matches_real_workbook_and_never_records_history(
    artifacts, status
):
    f = await seed(artifacts)
    request = TrackingExportRequest(
        agency_id=f.agency.id,
        group_id=f.group.id,
        status=status,
        broadcast_id=None if status == "unmatched_submission" else f.broadcast.id,
    )
    receipt, _, _ = await queue(f, request)
    result = await generate(f, receipt)
    actor = await UserRepository(f.session).get_by_id(f.user.id)
    response = await export_whatsapp_tracking_by_group(
        f.group.id,
        tracking_status=status,
        broadcast_id=request.broadcast_id,
        current_user=replace(actor, agency_id=f.agency.id),
        session=f.session,
    )
    expected = b"".join([part async for part in response.body_iterator])
    received = await downloaded(f, result)
    assert values(received) == values(expected)
    if status == "submitted":
        assert "TEST1" in str(values(received)) and "TEST3" not in str(values(received))
    if status == "not_submitted":
        assert "SYNTHETIC PERSON 2" in str(values(received)) and "TEST1" not in str(
            values(received)
        )
    artifact = await f.session.scalar(select(MCPArtifactModel))
    assert artifact.delivered_at is not None and artifact.purpose == "whatsapp_tracking_excel"
    assert artifact.export_history_id is None
    for model in (PassportExportHistoryModel, WhatsAppMessageLogModel):
        assert await f.session.scalar(select(func.count()).select_from(model)) == 0


async def test_retry_reconnect_retains_one_workbook_and_expired_result_never_regenerates(artifacts):
    f = await seed(artifacts)
    receipt, key, payload = await queue(f)
    first = await generate(f, receipt)
    definition = tracking_export_operation(f.settings, tracking_excel_support())
    replay = await MCPOperationService(f.session, f.settings, [definition]).execute(
        access_token=f.token,
        operation_name=definition.policy.name,
        idempotency_key=key,
        payload=payload,
    )
    await f.session.commit()
    assert replay == receipt
    token, _ = await f.connect()
    recovered = await generate(f, receipt, token)
    assert recovered["artifact"]["artifact_id"] != first["artifact"]["artifact_id"]
    assert recovered["artifact"]["sha256"] == first["artifact"]["sha256"]
    row = await f.session.scalar(select(MCPArtifactModel))
    row.created_at = datetime.now(UTC) - timedelta(hours=2)
    row.expires_at = datetime.now(UTC) - timedelta(hours=1)
    await f.session.commit()
    with pytest.raises(ArtifactError):
        await generate(f, receipt)
    await f.session.rollback()
    assert len(f.storage.objects) == 1
    assert await f.session.scalar(select(func.count()).select_from(MCPArtifactModel)) == 1


async def test_changed_recipient_and_broadcast_link_fence_saved_revision(artifacts):
    f = await seed(artifacts)
    receipt, _, _ = await queue(f)
    f.recipients[0].imported_fields = {"Zone": "Changed"}
    await f.session.commit()
    with pytest.raises(MCPOperationError, match="export_revision_changed"):
        await generate(f, receipt)
    await f.session.rollback()
    await f.session.refresh(f.group)
    await f.session.refresh(f.agency)
    await f.session.refresh(f.broadcast)
    selected = TrackingExportRequest(
        agency_id=f.agency.id, group_id=f.group.id, broadcast_id=f.broadcast.id
    )
    receipt2, _, _ = await queue(f, selected)
    await f.session.delete(f.link)
    await f.session.commit()
    with pytest.raises(ArtifactError, match="no longer linked"):
        await generate(f, receipt2)
    await f.session.rollback()
    assert not f.storage.objects


async def test_storage_failure_rolls_back_and_same_operation_resumes(artifacts):
    f = await seed(artifacts)
    receipt, _, _ = await queue(f)
    original = f.storage.put_transfer

    async def unavailable(*args, **kwargs):
        raise OSError("Synthetic storage failure")

    f.storage.put_transfer = unavailable
    with pytest.raises(OSError):
        await generate(f, receipt)
    await f.session.rollback()
    operation = await f.session.get(MCPOperationModel, uuid.UUID(receipt["operation_id"]))
    assert operation.status == "queued"
    assert await f.session.scalar(select(func.count()).select_from(MCPArtifactModel)) == 0
    f.storage.put_transfer = original
    await generate(f, receipt)
    assert len(f.storage.objects) == 1


async def test_authority_and_scope_are_live_for_generation_and_retained_transfer(artifacts):
    f = await seed(artifacts)
    receipt, _, _ = await queue(f)
    result = await generate(f, receipt)
    # Removing a link blocks resume, but existing bytes are a group-authorized
    # historical snapshot. This does not broaden the originating group scope.
    await f.session.delete(f.link)
    await f.session.commit()
    assert (await f.client.get(result["artifact"]["content_path"])).status_code == 200
    with pytest.raises(ArtifactError):
        await generate(f, receipt)
    await f.session.rollback()
    grant = await f.session.get(MCPGrantModel, f.principal.grant_id)
    grant.revoked_at = datetime.now(UTC)
    await f.session.commit()
    with pytest.raises(MCPAuthError):
        await generate(f, receipt)
    await f.session.rollback()
    assert (await f.client.get(result["artifact"]["content_path"])).status_code in {401, 403}


async def test_prepare_is_db_only_and_bounds_reject_without_partial_export(artifacts, monkeypatch):
    from app.application.mcp import artifacts as artifacts_module
    from app.application.mcp import tracking_export_source
    from app.application.use_cases.passports.prepare_group_excel import PreparedGroupExcel

    f = await seed(artifacts)

    def forbidden(*args, **kwargs):
        raise AssertionError("queued callback cannot render or initialize object storage")

    monkeypatch.setattr(artifacts_module, "MCPArtifactStorage", forbidden)
    monkeypatch.setattr(PreparedGroupExcel, "render", forbidden)
    receipt, _, _ = await queue(f)
    assert receipt["status"] == "queued" and not f.storage.objects
    monkeypatch.setattr(tracking_export_source, "MAX_TRACKING_ROWS", 1)
    with pytest.raises(ArtifactError, match="source row limit"):
        await queue(f)
    await f.session.rollback()
    assert await f.session.scalar(select(func.count()).select_from(MCPArtifactModel)) == 0


async def test_cancellation_drains_native_work_before_releasing_generation_capacity(
    artifacts, monkeypatch
):
    from app.infrastructure.export.passport_excel_exporter import PassportExcelExporter

    f = await seed(artifacts)
    receipt, _, _ = await queue(f)
    entered, release = threading.Event(), threading.Event()
    original = PassportExcelExporter.export_group

    def slow(self, *args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(PassportExcelExporter, "export_group", slow)
    task = asyncio.create_task(generate(f, receipt))
    assert await asyncio.to_thread(entered.wait, 5)
    task.cancel()
    await asyncio.sleep(0.05)
    assert not task.done()
    with pytest.raises(ArtifactError, match="capacity is busy"):
        await generate(f, receipt)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    await f.session.rollback()
    assert not f.storage.objects
    monkeypatch.setattr(PassportExcelExporter, "export_group", original)
    await generate(f, receipt)


def test_requests_reject_unknown_status_and_scope_widening():
    base = {"agency_id": uuid.uuid4(), "group_id": uuid.uuid4()}
    for extra in (
        {"status": "any"},
        {"all_agencies": True},
        {"mode": "incremental"},
        {"group_ids": []},
    ):
        with pytest.raises(ValidationError):
            TrackingExportRequest(**base, **extra)


@pytest.mark.parametrize("limit", ["MAX_FIELDS", "MAX_SNAPSHOT_BYTES", "MAX_WORKBOOK_BYTES"])
async def test_field_snapshot_and_output_bounds_reject_without_artifact(
    artifacts, monkeypatch, limit
):
    from app.application.mcp import tracking_exports
    from app.application.use_cases.passports.prepare_group_excel import ExcelPreparationError

    f = await seed(artifacts)
    receipt, _, _ = await queue(f)
    monkeypatch.setattr(tracking_exports, limit, 1)
    with pytest.raises((ArtifactError, ExcelPreparationError)):
        await generate(f, receipt)
    await f.session.rollback()
    assert not f.storage.objects
    assert await f.session.scalar(select(func.count()).select_from(MCPArtifactModel)) == 0


async def test_scope_requires_exact_agency_group_and_current_link(artifacts):
    f = await seed(artifacts)
    base = {"agency_id": f.agency.id, "group_id": f.group.id}
    for change in (
        {"agency_id": uuid.uuid4()},
        {"group_id": uuid.uuid4()},
        {"broadcast_id": uuid.uuid4()},
    ):
        with pytest.raises(ArtifactError):
            await service(f).inspect(f.principal, TrackingExportRequest(**{**base, **change}))
        await f.session.rollback()
    assert not f.storage.objects


async def test_post_storage_revision_fence_rolls_back_private_copy_receipt(artifacts):
    f = await seed(artifacts)
    receipt, _, _ = await queue(f)
    original = f.storage.put_transfer

    async def changed(*args, **kwargs):
        await original(*args, **kwargs)
        f.recipients[0].imported_fields = {"Zone": "Changed while storing"}
        await f.session.flush()

    f.storage.put_transfer = changed
    with pytest.raises(MCPOperationError, match="export_revision_changed"):
        await generate(f, receipt)
    await f.session.rollback()
    assert len(f.storage.objects) == 1  # Expiring private orphan, never a source object.
    assert await f.session.scalar(select(func.count()).select_from(MCPArtifactModel)) == 0
    operation = await f.session.get(MCPOperationModel, uuid.UUID(receipt["operation_id"]))
    assert operation.status == "queued"


async def test_existing_replacement_export_uses_website_resolution_without_mutating_it(artifacts):
    from app.infrastructure.database.models import PassportRosterResolutionModel

    f = await seed(artifacts)
    replacement = PassportRosterResolutionModel(
        id=uuid.uuid4(),
        agency_id=f.agency.id,
        client_group_id=f.group.id,
        submission_id=f.passengers[1].id,
        broadcast_recipient_id=f.recipients[1].id,
        replaced_recipient_normalized_phone=f.recipients[1].normalized_phone_number,
        original_recipient_phone=f.recipients[1].phone_number,
        resolution_type="replacement",
        suppressed_recipient_ids=[str(f.recipients[1].id)],
    )
    f.session.add(replacement)
    await f.session.commit()
    selected = TrackingExportRequest(
        agency_id=f.agency.id,
        group_id=f.group.id,
        status="replacement",
        broadcast_id=f.broadcast.id,
    )
    receipt, _, _ = await queue(f, selected)
    result = await generate(f, receipt)
    content = await downloaded(f, result)
    assert "TEST3" in str(values(content)) and "TEST1" not in str(values(content))
    await f.session.refresh(replacement)
    assert replacement.status == "active" and replacement.restored_at is None
