"""Actual shared XLSX bytes, durable retry lifecycle and grant-bound recovery."""

from __future__ import annotations

import io
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from openpyxl import load_workbook
from pydantic import ValidationError
from sqlalchemy import func, select

from app.application.mcp.artifacts import ArtifactError
from app.application.mcp.credentials import credential_hash, new_credential
from app.application.mcp.exports import (
    ExcelExportRequest,
    MCPExcelExportService,
    excel_export_operation,
)
from app.application.mcp.operations import MCPOperationError, MCPOperationService
from app.infrastructure.database.mcp_artifact_models import MCPArtifactAccessModel, MCPArtifactModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    ClientGroupModel,
    PassportExportHistoryModel,
    PassportSubmissionModel,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes.passport_routes.excel_exports import export_passports_by_group
from app.presentation.mcp.export_tools import excel_support
from tests.integration.test_mcp_artifacts import artifacts as artifacts


def person(f, index, *, group=None, status="staff_approved"):
    group = group or f.group
    return PassportSubmissionModel(
        id=uuid.uuid4(),
        agency_id=f.agency.id,
        group_id=group.id,
        client_name=f"Synthetic Person {index}",
        image_s3_key=f"private/never-read-{index}",
        status=status,
        confirmed_fields={
            "given_name": f"Person{index}",
            "surname": "Synthetic",
            "passport_number": f"TEST{index}",
        },
    )


def values(data):
    workbook = load_workbook(io.BytesIO(data), read_only=True)
    return {
        sheet.title: [row for row in sheet.values if not str(row[0]).startswith("Generated at ")]
        for sheet in workbook
    }


def service(f):
    return MCPExcelExportService(f.session, f.settings, excel_support(), artifacts=f.service)


async def queue(f, request=None, key=None):
    await f.session.refresh(f.agency)
    await f.session.refresh(f.group)
    request = request or ExcelExportRequest(agency_id=f.agency.id, group_ids=[f.group.id])
    observed = await service(f).inspect(f.principal, request)
    definition = excel_export_operation(f.settings, excel_support())
    operations = MCPOperationService(f.session, f.settings, [definition])
    payload = {
        "export": request.model_dump(mode="json"),
        "expected_revision": observed["expected_revision"],
    }
    key = key or uuid.uuid4().hex
    receipt = await operations.execute(
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


async def downloaded(f, result):
    metadata = result["artifact"]
    response = await f.client.get(metadata["content_path"])
    assert response.status_code == 200, response.text
    ack = await f.client.post(
        f"/mcp/artifacts/{metadata['artifact_id']}/delivery",
        json={"byte_size": metadata["byte_size"], "sha256": metadata["sha256"]},
    )
    assert ack.status_code == 200, ack.text
    return response.content


async def test_group_workbook_web_parity_incremental_and_ack_only_history(artifacts):
    f = artifacts
    first, draft = person(f, 1), person(f, 99, status="uploaded")
    f.session.add_all([first, draft])
    await f.session.commit()
    receipt, _, _ = await queue(f)
    result = await generate(f, receipt)
    history = await f.session.scalar(select(PassportExportHistoryModel))
    assert history.status == "prepared" and history.completed_at is None
    assert history.exported_submission_ids == [str(first.id)]
    actor = await UserRepository(f.session).get_by_id(f.user.id)
    response = await export_passports_by_group(
        f.group.id,
        export_mode="all",
        baseline_export_id=None,
        request_id=uuid.uuid4(),
        supplemental_fields=None,
        group_by_field=None,
        agency_match_field=None,
        current_user=replace(actor, agency_id=f.agency.id),
        session=f.session,
    )
    web_bytes = b"".join([part async for part in response.body_iterator])
    received = await downloaded(f, result)
    assert values(received) == values(web_bytes)
    assert "TEST1" in str(values(received)) and "TEST99" not in str(values(received))
    await f.session.refresh(history)
    assert history.status == "completed"
    second = person(f, 2)
    f.session.add(second)
    await f.session.commit()
    request = ExcelExportRequest(
        agency_id=f.agency.id,
        group_ids=[f.group.id],
        mode="incremental",
        baseline_export_id=history.id,
    )
    receipt2, _, _ = await queue(f, request)
    result2 = await generate(f, receipt2)
    received2 = await downloaded(f, result2)
    assert "TEST2" in str(values(received2)) and "TEST1" not in str(values(received2))
    second_history = await f.session.scalar(
        select(PassportExportHistoryModel).where(
            PassportExportHistoryModel.request_id == uuid.UUID(receipt2["operation_id"])
        )
    )
    assert second_history.exported_submission_ids == [str(second.id)]
    assert set(second_history.snapshot_submission_ids) == {str(first.id), str(second.id)}


async def test_retry_and_new_connection_keep_one_artifact_history_and_original_receipt(artifacts):
    f = artifacts
    f.session.add(person(f, 1))
    await f.session.commit()
    receipt, key, payload = await queue(f)
    first = await generate(f, receipt)
    definition = excel_export_operation(f.settings, excel_support())
    replay = await MCPOperationService(f.session, f.settings, [definition]).execute(
        access_token=f.token,
        operation_name=definition.policy.name,
        idempotency_key=key,
        payload=payload,
    )
    await f.session.commit()
    assert replay == receipt and replay["status"] == "queued"
    second = await generate(f, receipt)
    assert first["artifact"] == second["artifact"]
    token, principal = await f.connect()
    recovered = await generate(f, receipt, token)
    assert recovered["artifact"]["artifact_id"] != first["artifact"]["artifact_id"]
    assert recovered["artifact"]["sha256"] == first["artifact"]["sha256"]
    with pytest.raises(ArtifactError):
        await f.service.get(principal, first["artifact"]["artifact_id"])
    assert (
        await f.service.get(principal, recovered["artifact"]["artifact_id"])
    ).user_id == f.user.id
    assert len(f.storage.objects) == 1
    for model in (MCPArtifactModel, PassportExportHistoryModel, MCPOperationModel):
        assert await f.session.scalar(select(func.count()).select_from(model)) == 1
    assert await f.session.scalar(select(func.count()).select_from(MCPArtifactAccessModel)) == 2


async def test_queued_callback_never_initializes_storage_or_renders(artifacts, monkeypatch):
    from app.application.mcp import artifacts as artifact_module
    from app.application.use_cases.passports.prepare_group_excel import PreparedGroupExcel

    def forbidden_storage():
        raise AssertionError("DB-only callback must not initialize storage")

    async def forbidden_render(_self):
        raise AssertionError("DB-only callback must not render workbooks")

    monkeypatch.setattr(artifact_module, "MCPArtifactStorage", forbidden_storage)
    monkeypatch.setattr(PreparedGroupExcel, "render", forbidden_render)
    receipt, _, _ = await queue(artifacts)
    assert receipt["status"] == "queued" and not artifacts.storage.objects
    for model in (MCPArtifactModel, PassportExportHistoryModel):
        assert await artifacts.session.scalar(select(func.count()).select_from(model)) == 0


async def test_stale_revision_blocks_generation_and_storage_failure_keeps_queued(artifacts):
    f = artifacts
    f.session.add(person(f, 1))
    await f.session.commit()
    receipt, _, _ = await queue(f)
    f.group.name = "Changed after inspection"
    await f.session.commit()
    with pytest.raises(MCPOperationError, match="export_revision_changed"):
        await generate(f, receipt)
    await f.session.rollback()
    assert not f.storage.objects
    receipt2, _, _ = await queue(f)
    original = f.storage.put_transfer

    async def unavailable(*args, **kwargs):
        raise OSError("private fixture storage unavailable")

    f.storage.put_transfer = unavailable
    with pytest.raises(OSError):
        await generate(f, receipt2)
    await f.session.rollback()
    assert await f.session.scalar(select(func.count()).select_from(PassportExportHistoryModel)) == 0
    operation = await f.session.get(MCPOperationModel, uuid.UUID(receipt2["operation_id"]))
    assert operation.status == "queued"
    f.storage.put_transfer = original
    await generate(f, receipt2)


async def test_selected_groups_retain_every_scope_and_selected_passports_are_exact(artifacts):
    f = artifacts
    other = ClientGroupModel(
        id=uuid.uuid4(), agency_id=f.agency.id, name="Second fixture", token=uuid.uuid4().hex
    )
    f.session.add(other)
    await f.session.flush()
    first, second = person(f, 1), person(f, 2, group=other)
    f.session.add_all([first, second])
    await f.session.commit()
    request = ExcelExportRequest(
        agency_id=f.agency.id, group_ids=[f.group.id, other.id], selection="selected_groups"
    )
    receipt, _, _ = await queue(f, request)
    result = await generate(f, receipt)
    workbook = await downloaded(f, result)
    assert "TEST1" in str(values(workbook)) and "TEST2" in str(values(workbook))
    assert await f.session.scalar(select(func.count()).select_from(PassportExportHistoryModel)) == 0
    selected = request.model_copy(
        update={"selection": "selected_passports", "submission_ids": [second.id]}
    )
    selected_receipt, _, _ = await queue(f, selected)
    selected_result = await generate(f, selected_receipt)
    selected_workbook = await downloaded(f, selected_result)
    assert "TEST1" not in str(values(selected_workbook)) and "TEST2" in str(
        values(selected_workbook)
    )
    other.deleted_at = datetime.now(UTC)
    await f.session.commit()
    assert (await f.client.get(result["artifact"]["content_path"])).status_code == 404
    with pytest.raises(ArtifactError):
        await generate(f, receipt)


async def test_expired_export_does_not_regenerate_and_legacy_locator_stays_valid(artifacts):
    f = artifacts
    f.session.add(person(f, 1))
    await f.session.commit()
    receipt, _, _ = await queue(f)
    await generate(f, receipt)
    row = await f.session.scalar(select(MCPArtifactModel))
    access = await f.session.get(MCPArtifactAccessModel, (row.id, f.principal.grant_id))
    legacy = new_credential("artifact")
    row.handle_hash = access.handle_hash = credential_hash(legacy, f.settings.app_secret_key)
    access.handle_version = 0
    await f.session.commit()
    assert (await f.service.get(f.principal, legacy)).id == row.id
    with pytest.raises(ArtifactError, match="Legacy"):
        await generate(f, receipt)
    token, _ = await f.connect()
    recovered = await generate(f, receipt, token)
    assert recovered["artifact"]["artifact_id"] != legacy
    row.created_at = datetime.now(UTC) - timedelta(hours=2)
    row.expires_at = datetime.now(UTC) - timedelta(hours=1)
    await f.session.commit()
    with pytest.raises(ArtifactError, match="expired"):
        await generate(f, receipt)
    assert len(f.storage.objects) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"mode": "incremental"},
        {"selection": "selected_groups", "mode": "incremental", "baseline_export_id": uuid.uuid4()},
        {"selection": "selected_passports"},
        {"supplemental_fields": ["a,b"]},
    ],
)
def test_unsupported_or_ambiguous_modes_rejected(changes):
    with pytest.raises(ValidationError):
        ExcelExportRequest(agency_id=uuid.uuid4(), group_ids=[uuid.uuid4()], **changes)
