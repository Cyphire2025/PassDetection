"""Native HTTP handoff with real file scanning, source binding and current policy."""

import hashlib
import io
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from openpyxl import Workbook
from sqlalchemy import func, select

from app.application.mcp.artifacts import ArtifactError
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.native_source_bindings import require_native_pdf_source
from app.application.mcp.native_transfer_dto import MCPNativeUploadRequest
from app.application.mcp.native_transfer_runtime import download_content, prepare_download
from app.application.mcp.native_transfers import MCPNativeTransferService
from app.application.mcp.pdf_ingestion import PDFIngestRequest
from app.infrastructure.database.mcp_artifact_models import MCPArtifactModel
from app.infrastructure.database.mcp_contact_import_models import MCPContactImportUploadModel
from app.infrastructure.database.mcp_models import MCPControlModel, MCPGrantModel
from app.infrastructure.database.mcp_native_transfer_models import MCPNativeTransferModel
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    PassportSubmissionModel,
    UserSecurityStateModel,
)
from app.infrastructure.security.contact_spreadsheet_security import ContactSpreadsheetSecurity
from app.infrastructure.security.upload_validator import MalwareScanRejectedError
from app.presentation.api.v1.routes.mcp_native_transfers import router
from tests.integration.test_mcp_artifacts import artifacts as artifacts
from tests.integration.test_mcp_artifacts import pdf, prepared
from tests.integration.test_mcp_pdf_ingestion import ingest, queue, seed, visa_pdf


@pytest.fixture
async def native(artifacts):
    fixture = artifacts
    fixture.client._transport.app.include_router(router)
    fixture.client._transport.app.state.mcp_contact_security = ContactSpreadsheetSecurity(
        settings=fixture.settings,
        scanner=fixture.scanner,
        session_factory=lambda: fixture.evidence,
        storage=fixture.storage,
    )
    fixture.native = MCPNativeTransferService(
        fixture.session,
        fixture.settings,
        artifacts=fixture.service,
        contact_storage=fixture.storage,
        contact_security=fixture.client._transport.app.state.mcp_contact_security,
    )
    return fixture


def workbook(*, formula=False):
    book, output = Workbook(), io.BytesIO()
    book.active.append(["Name", "Passport"])
    book.active.append(["=1+1" if formula else "Test traveller", "P123"])
    book.save(output)
    book.close()
    return output.getvalue()


async def upload_ticket(
    fixture, *, data=None, purpose="document_pdf", key="native-upload-key-0001"
):
    data = data if data is not None else pdf()
    request = MCPNativeUploadRequest(
        purpose=purpose,
        agency_id=fixture.agency.id,
        group_id=fixture.group.id if purpose != "contact_broadcast" else None,
        document_type="visa" if purpose == "document_pdf" else None,
        filename="visa.pdf" if purpose == "document_pdf" else "people.xlsx",
        byte_size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    result = await fixture.native.create_upload(fixture.token, request, key)
    await fixture.session.commit()
    return result, data


def headers(ticket):
    return {"Authorization": ticket["authorization_header"], "Origin": "http://localhost:3000"}


def path(ticket, suffix=""):
    return f"/mcp/native-transfers/{ticket['id']}{suffix}"


async def put(fixture, ticket, data):
    return await fixture.client.put(
        path(ticket, "/content"),
        content=data,
        headers={**headers(ticket), "Content-Type": ticket["media_type"]},
    )


async def test_ticket_retry_secret_binding_and_safe_retained_metadata(native):
    f = native
    ticket, _ = await upload_ticket(f)
    repeated, _ = await upload_ticket(f)
    assert repeated == ticket
    assert ticket["browser_url"].split("#token=")[1] == ticket["authorization_header"][7:]
    assert "token=" not in ticket["content_url"]
    row = await f.session.get(MCPNativeTransferModel, uuid.UUID(ticket["id"]))
    assert row.token_hash != ticket["authorization_header"][7:]
    with pytest.raises(ArtifactError, match="different transfer input"):
        await upload_ticket(f, data=pdf() + b" ")
    await f.session.rollback()
    assert await f.session.scalar(select(func.count()).select_from(MCPNativeTransferModel)) == 1
    logs = (await f.session.scalars(select(AuditLogModel))).all()
    assert all("gcmcp_transfer_" not in str(log.metadata_json) for log in logs)
    assert all("browser_url" not in str(log.metadata_json) for log in logs)


async def test_limited_token_only_no_ambient_dashboard_or_oauth_and_origin_guard(native):
    f = native
    ticket, _ = await upload_ticket(f)
    for credential in (
        "Bearer dashboard.jwt",
        f"Bearer {f.token}",
        "Bearer gcmcp_transfer_" + "x" * 64,
    ):
        response = await f.client.get(path(ticket), headers={"Authorization": credential})
        assert response.status_code == 401
    denied = await f.client.get(
        path(ticket), headers={**headers(ticket), "Origin": "https://attacker.test"}
    )
    assert denied.status_code == 403
    wrong_id = {**ticket, "id": str(uuid.uuid4())}
    assert (await f.client.get(path(wrong_id), headers=headers(ticket))).status_code == 401
    assert (
        await f.client.get(path(ticket) + "?token=forbidden", headers=headers(ticket))
    ).status_code == 401
    result = await f.client.get(path(ticket), headers=headers(ticket))
    assert result.status_code == 200 and result.json()["destination_label"] == "Fixture trip"
    assert (
        result.headers["cache-control"] == "no-store"
        and result.headers["referrer-policy"] == "no-referrer"
    )
    assert (
        not {"authorization_header", "browser_url", "staged_source", "storage_key"}
        & result.json().keys()
    )


async def test_scanned_pdf_upload_is_bound_idempotent_and_separate_from_ingestion(native):
    f = native
    ticket, data = await upload_ticket(f)
    result = await put(f, ticket, data)
    assert result.status_code == 200 and result.json()["status"] == "completed", result.text
    assert f.scanner.calls == 1
    again = await put(f, ticket, data)
    assert again.status_code == 200 and f.scanner.calls == 1
    row = await f.session.get(MCPNativeTransferModel, uuid.UUID(ticket["id"]))
    source = await f.session.get(MCPArtifactModel, row.artifact_id)
    assert source.grant_id == f.principal.grant_id and source.group_id == f.group.id
    assert row.document_type == "visa" and source.ingestion_operation_id is None
    assert await f.session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 0
    inspected = await f.native.inspect(f.token, row.id)
    assert inspected["staged_source"]["business_ingestion"] == "not_started"
    assert "gcmcp_artifact_" in inspected["staged_source"]["artifact_id"]
    assert "gcmcp_transfer_" not in str(inspected)


@pytest.mark.parametrize("purpose", ["group_workbook", "contact_broadcast"])
async def test_literal_workbook_original_scan_and_target_binding(native, purpose):
    f = native
    ticket, data = await upload_ticket(f, data=workbook(), purpose=purpose)
    result = await put(f, ticket, data)
    assert result.status_code == 200, result.text
    row = await f.session.get(MCPNativeTransferModel, uuid.UUID(ticket["id"]))
    source = await f.session.get(MCPContactImportUploadModel, row.workbook_id)
    assert source.workbook_snapshot["sheets"][0]["rows"][1] == ["Test traveller", "P123"]
    assert source.original_grant_id == row.original_grant_id and source.sha256 == row.sha256
    assert row.group_id == (f.group.id if purpose == "group_workbook" else None)
    assert (
        f.scanner.calls == 1
        and await f.session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 0
    )
    inspected = await f.native.inspect(f.token, row.id)
    assert inspected["staged_source"]["upload_id"].startswith("gcmcp_contacts_")


@pytest.mark.parametrize("failure", ["formula", "scanner", "checksum"])
async def test_upload_validation_failure_leaves_no_business_source(native, failure):
    f = native
    data = workbook(formula=failure == "formula")
    ticket, _ = await upload_ticket(f, data=data, purpose="group_workbook")
    if failure == "scanner":
        f.scanner.error = MalwareScanRejectedError
    sent = data + b"wrong" if failure == "checksum" else data

    # Streaming content without Content-Length exercises checksum/size validation,
    # rather than just the explicit length header admission.
    async def body():
        yield sent

    result = await f.client.put(
        path(ticket, "/content"),
        content=body(),
        headers={**headers(ticket), "Content-Type": ticket["media_type"]},
    )
    assert result.status_code == 422, result.text
    row = await f.session.get(MCPNativeTransferModel, uuid.UUID(ticket["id"]))
    assert row.status == "failed" and row.workbook_id is None and row.artifact_id is None
    assert not f.storage.objects
    assert (
        await f.session.scalar(select(func.count()).select_from(MCPContactImportUploadModel)) == 0
    )


@pytest.mark.parametrize(
    "change", ["global", "device", "revoked", "security", "section", "tool", "expired", "moved"]
)
async def test_current_authority_denies_prepared_ticket_before_body(native, change):
    f = native
    ticket, data = await upload_ticket(f)
    grant = await f.session.get(MCPGrantModel, f.principal.grant_id)
    control = await f.session.get(MCPControlModel, 1)
    if change == "global":
        control.write_enabled = False
    elif change == "device":
        grant.enabled = False
    elif change == "revoked":
        grant.revoked_at = datetime.now(UTC)
    elif change == "security":
        (await f.session.get(UserSecurityStateModel, f.user.id)).session_version = 2
    elif change == "section":
        grant.allowed_write_sections = ["exports"]
    elif change == "tool":
        control.allowed_write_tools = [
            name for name in control.allowed_write_tools if name != "create_native_upload"
        ]
    elif change == "expired":
        row = await f.session.get(MCPNativeTransferModel, uuid.UUID(ticket["id"]))
        row.created_at = datetime.now(UTC) - timedelta(minutes=15)
        row.expires_at = datetime.now(UTC) - timedelta(minutes=5)
    else:
        other_agency = AgencyModel(id=uuid.uuid4(), name="Other agency", email="other@example.test")
        f.session.add(other_agency)
        await f.session.flush()
        f.group.agency_id = other_agency.id
    await f.session.commit()
    result = await put(f, ticket, data)
    assert result.status_code in {400, 401, 403, 404}, result.text
    assert f.scanner.calls == 0 and not f.storage.objects


async def test_claim_rejects_parallel_upload_and_expired_lease_can_retry(native):
    f = native
    ticket, data = await upload_ticket(f)
    row = await f.session.get(MCPNativeTransferModel, uuid.UUID(ticket["id"]))
    row.status, row.claim_id, row.claim_expires_at = (
        "transferring",
        uuid.uuid4(),
        datetime.now(UTC) + timedelta(minutes=1),
    )
    await f.session.commit()
    assert (await put(f, ticket, data)).status_code == 409
    assert f.scanner.calls == 0
    await f.session.refresh(row)
    row.claim_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await f.session.commit()
    assert (await put(f, ticket, data)).status_code == 200
    assert f.scanner.calls == 1


async def test_revocation_after_scanner_recheck_rolls_back_staged_source(native, monkeypatch):
    f = native
    ticket, data = await upload_ticket(f)
    original = f.security.validate_document

    async def revoke_after_scan(**arguments):
        await original(**arguments)
        grant = await f.session.get(MCPGrantModel, f.principal.grant_id)
        grant.revoked_at = datetime.now(UTC)
        await f.session.commit()

    monkeypatch.setattr(f.security, "validate_document", revoke_after_scan)
    result = await put(f, ticket, data)
    assert result.status_code in {400, 401, 403}, result.text
    row = await f.session.get(MCPNativeTransferModel, uuid.UUID(ticket["id"]))
    assert row.status == "failed" and row.artifact_id is None
    assert await f.session.scalar(select(func.count()).select_from(MCPArtifactModel)) == 0
    assert not f.storage.objects and f.scanner.calls == 1


async def download_ticket(fixture):
    source, history, data = await prepared(fixture)
    ticket = await fixture.native.create_download(
        fixture.token, source["artifact_id"], "native-download-key-0001"
    )
    await fixture.session.commit()
    return ticket, history, data


async def test_native_download_requires_exact_saved_copy_ack_and_allows_transport_retry(native):
    f = native
    ticket, history, data = await download_ticket(f)
    response = await f.client.post(
        path(ticket, "/delivery"),
        headers=headers(ticket),
        json={"byte_size": len(data), "sha256": ticket["sha256"]},
    )
    await f.session.refresh(history)
    assert response.status_code == 409 and history.status == "prepared"
    response = await f.client.get(path(ticket, "/content"), headers=headers(ticket))
    assert response.status_code == 200 and response.content == data
    await f.session.refresh(history)
    assert history.status == "prepared"
    assert response.headers["content-disposition"] == 'attachment; filename="people.xlsx"'
    wrong = await f.client.post(
        path(ticket, "/delivery"),
        headers=headers(ticket),
        json={"byte_size": len(data), "sha256": "0" * 64},
    )
    assert wrong.status_code == 422
    for _ in range(2):
        ack = await f.client.post(
            path(ticket, "/delivery"),
            headers=headers(ticket),
            json={"byte_size": len(data), "sha256": ticket["sha256"]},
        )
        assert ack.status_code == 200 and ack.json()["delivered"] is True
    await f.session.refresh(history)
    assert history.status == "completed"
    assert (
        await f.session.scalar(
            select(func.count())
            .select_from(AuditLogModel)
            .where(AuditLogModel.action == "mcp.native_transfer_delivered")
        )
        == 1
    )
    assert (await f.client.get(path(ticket, "/content"), headers=headers(ticket))).content == data
    assert (
        await f.client.get(
            path(ticket, "/content"), headers={**headers(ticket), "Range": "bytes=0-5"}
        )
    ).status_code == 416


async def test_source_family_pause_denies_native_download_and_foreign_ticket(native):
    f = native
    ticket, _, _ = await download_ticket(f)
    other, _ = await f.connect()
    with pytest.raises(ArtifactError):
        await f.native.inspect(other, uuid.UUID(ticket["id"]))
    await f.session.rollback()
    control = await f.session.get(MCPControlModel, 1)
    control.allowed_write_tools = [
        name for name in control.allowed_write_tools if name != "prepare_excel_export"
    ]
    await f.session.commit()
    response = await f.client.get(path(ticket, "/content"), headers=headers(ticket))
    assert response.status_code == 403 and f.storage.read_sizes == []


async def test_interrupted_stream_or_expiry_never_marks_saved_delivery(native):
    f = native
    ticket, history, _ = await download_ticket(f)
    identifier, secret = uuid.UUID(ticket["id"]), ticket["authorization_header"][7:]
    row, principal, artifact = await prepare_download(f.native, identifier, secret)
    stream = download_content(f.native, identifier, secret, principal, artifact)
    await anext(stream)
    await stream.aclose()
    await f.session.refresh(row)
    assert (
        row.download_completed_at is None
        and row.delivered_at is None
        and history.status == "prepared"
    )
    grant = await f.session.get(MCPGrantModel, f.principal.grant_id)
    grant.write_enabled = False
    await f.session.commit()
    with pytest.raises(MCPAuthError):
        await f.native.limited(identifier, secret, name="read_native_artifact")


async def native_pdf_source(fixture):
    ticket, data = await upload_ticket(fixture, data=visa_pdf())
    response = await put(fixture, ticket, data)
    assert response.status_code == 200, response.text
    transfer = await fixture.session.get(MCPNativeTransferModel, uuid.UUID(ticket["id"]))
    source = await fixture.session.get(MCPArtifactModel, transfer.artifact_id)
    return transfer, source


async def test_native_pdf_ingestion_preserves_prepared_lane_after_transport_expiry(native):
    f = await seed(native)
    transfer, source = await native_pdf_source(f)
    request = PDFIngestRequest(
        artifact_id=f.native.artifact_handle(transfer),
        agency_id=f.agency.id,
        group_id=f.group.id,
        document_type="visa",
    )
    transfer.created_at = datetime.now(UTC) - timedelta(minutes=15)
    transfer.expires_at = datetime.now(UTC) - timedelta(minutes=5)
    await f.session.commit()
    inspection = await f.native.inspect(f.token, transfer.id)
    assert inspection["staged_source"]["artifact_id"] == request.artifact_id
    public_status = await f.client.get(
        path({"id": str(transfer.id)}),
        headers={"Authorization": "Bearer " + f.native.token(transfer)},
    )
    assert public_status.status_code == 403
    receipt, _, _, _ = await queue(f, request=request)
    result = await ingest(f, receipt)
    assert result["business_ingestion"] == "ingested" and result["document_type"] == "visa"
    assert result["batch_status"] == "draft" and result["assignment_count"] == 1
    await f.session.refresh(source)
    assert source.ingestion_operation_id is not None


@pytest.mark.parametrize("change", ["source_expired", "revoked", "moved"])
async def test_completed_upload_inspection_source_lifetime_keeps_current_authority(native, change):
    f = native
    transfer, source = await native_pdf_source(f)
    transfer.created_at = datetime.now(UTC) - timedelta(minutes=15)
    transfer.expires_at = datetime.now(UTC) - timedelta(minutes=5)
    if change == "source_expired":
        source.created_at = datetime.now(UTC) - timedelta(hours=2)
        source.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    elif change == "revoked":
        (await f.session.get(MCPGrantModel, f.principal.grant_id)).revoked_at = datetime.now(UTC)
    else:
        f.group.deleted_at = datetime.now(UTC)
    await f.session.commit()
    with pytest.raises((ArtifactError, MCPAuthError)):
        await f.native.inspect(f.token, transfer.id)


@pytest.mark.parametrize(
    "change", ["lane", "group", "pending", "security", "checksum", "media", "original_grant"]
)
async def test_native_pdf_binding_rejects_changed_prepared_source(native, change):
    f = native
    transfer, source = await native_pdf_source(f)
    if change == "lane":
        transfer.document_type = "other"
    elif change == "group":
        transfer.group_id = uuid.uuid4()
    elif change == "pending":
        transfer.status = "pending"
    elif change == "security":
        transfer.security_version = 2
    elif change == "checksum":
        transfer.sha256 = "0" * 64
    elif change == "media":
        transfer.media_type = "application/octet-stream"
    else:
        _, other = await f.connect()
        transfer.original_grant_id = other.grant_id
    await f.session.commit()
    with pytest.raises(ArtifactError, match="prepared target and document lane"):
        await require_native_pdf_source(
            f.session,
            f.principal,
            source,
            agency_id=f.agency.id,
            group_id=f.group.id,
            document_type="visa",
            lock=True,
        )
