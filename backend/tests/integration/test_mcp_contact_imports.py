"""Real HTTP/SQL Excel staging and append-only creation; deterministic scanner/storage."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import io
import json
import threading
import uuid
from datetime import UTC, datetime, timedelta
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from openpyxl import Workbook
from sqlalchemy import delete, func, select

from app.application.mcp.artifacts import ArtifactError
from app.application.mcp.contact_broadcasts import (
    ContactBroadcastDraft,
    contact_broadcast_operation,
    project_import,
)
from app.application.mcp.contact_mapping import ContactColumnMapping, map_contacts
from app.application.mcp.contact_uploads import MCPContactUploadService
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.operations import MCPOperationError, MCPOperationService
from app.infrastructure.database.mcp_contact_import_models import MCPContactImportUploadModel
from app.infrastructure.database.mcp_models import MCPGrantModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    AuditLogModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastRejectedContactModel,
    WhatsAppBroadcastSupportContactModel,
    WhatsAppMessageLogModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.security.contact_spreadsheet_security import (
    XLSX_MEDIA,
    ContactSpreadsheetSecurity,
    snapshot_workbook,
)
from app.infrastructure.security.upload_validator import (
    MalwareScannerUnavailableError,
    MalwareScanRejectedError,
)
from app.presentation.api.v1.routes.mcp_contact_imports import router
from app.presentation.mcp.contact_import_support import CONTACT_IMPORT_SUPPORT
from tests.integration.test_mcp_artifacts import artifacts as artifacts
from tests.integration.test_mcp_artifacts import chunks


def workbook(rows=None):
    book, output = Workbook(), io.BytesIO()
    sheet = book.active
    sheet.title = "Contacts"
    for row in rows or [
        ["Name", "Phone", "Staff code"],
        ["Aarav", "9876543210", "ONE"],
        ["Aarav duplicate", "+919876543210", "TWO"],
        ["Missing number", "", "THREE"],
        ["Bad number", "not-a-number", "FOUR"],
        ["", "9876543211", "FIVE"],
        ["Mira", "9876543212", "SIX"],
    ]:
        sheet.append(row)
    book.create_sheet("Notes").append(["Do not guess recipients from this sheet", "1234567890"])
    book.save(output)
    book.close()
    return output.getvalue()


def rewrite_archive(content, name, replacement):
    output = io.BytesIO()
    with ZipFile(io.BytesIO(content)) as original, ZipFile(output, "w", ZIP_DEFLATED) as changed:
        for member in original.infolist():
            changed.writestr(
                member.filename, replacement if member.filename == name else original.read(member)
            )
    return output.getvalue()


@pytest.fixture
async def contact_import(artifacts):
    f = artifacts
    f.token, f.principal = await f.connect(["mcp:upload", "mcp:change", "mcp:read"])
    f.agency_id = f.agency.id
    f.contact_security = ContactSpreadsheetSecurity(
        settings=f.settings,
        scanner=f.scanner,
        session_factory=lambda: f.evidence,
        storage=f.storage,
    )
    f.contacts = MCPContactUploadService(
        f.session, f.settings, storage=f.storage, security=f.contact_security
    )
    f.definition = contact_broadcast_operation(f.settings, CONTACT_IMPORT_SUPPORT)
    f.operations = MCPOperationService(f.session, f.settings, [f.definition])
    app = FastAPI()
    app.state.settings = f.settings
    app.state.mcp_contact_import_storage, app.state.mcp_contact_import_security = (
        f.storage,
        f.contact_security,
    )
    app.include_router(router)

    async def database():
        yield f.session

    app.dependency_overrides[get_db_session] = database
    async with AsyncClient(
        transport=ASGITransport(app),
        base_url="http://localhost:8000",
        headers={"Authorization": f"Bearer {f.token}"},
    ) as client:
        f.contact_client = client
        yield f


async def upload(f, content=None, **headers):
    content = content if content is not None else workbook()
    return await f.contact_client.post(
        "/mcp/contact-imports/uploads",
        params={"agency_id": str(f.agency_id), "filename": "contacts.xlsx"},
        content=chunks(content),
        headers={
            "Content-Type": XLSX_MEDIA,
            "X-Artifact-Size": str(len(content)),
            "X-Artifact-SHA256": hashlib.sha256(content).hexdigest(),
            **headers,
        },
    )


async def prepared(f):
    response = await upload(f)
    assert response.status_code == 201, response.text
    metadata = response.json()
    draft = ContactBroadcastDraft(
        upload_id=metadata["upload_id"],
        agency_id=f.agency_id,
        name="September departures",
        organizing_company_name="Global Connect",
        support_contacts=[{"name": "Help desk", "phone_number": "9876543299"}],
        recipient_opt_in_confirmed=True,
        column_mappings=[
            ContactColumnMapping(sheet_name="Contacts", header_row=1, phone_column=2, name_column=1)
        ],
    )
    row = await f.contacts.get(f.principal, draft.upload_id)
    _, preview = project_import(row, draft, support=CONTACT_IMPORT_SUPPORT)
    return (
        row.id,
        draft.model_dump(mode="json") | {"preview_sha256": preview["preview_sha256"]},
        preview,
    )


async def create(f, payload, *, key="contact-create-operation-001", token=None):
    return await f.operations.execute(
        access_token=token or f.token,
        operation_name=f.definition.policy.name,
        idempotency_key=key,
        payload=payload,
    )


async def total(f, model):
    return await f.session.scalar(select(func.count()).select_from(model))


async def test_upload_is_agency_scoped_scanned_immutable_and_has_no_business_effect(contact_import):
    f = contact_import
    content = workbook()
    response = await upload(f, content)
    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert data["agency_id"] == str(f.agency_id) and "group_id" not in data
    assert data["business_import"] == "not_started" and len(data["worksheets"]) == 2
    assert "storage_key" not in data and "workbook_snapshot" not in data
    source = await f.contacts.get(f.principal, data["upload_id"])
    assert f.storage.objects[source.storage_key][0] == content
    assert f.scanner.calls == 1 and f.evidence.records[-1].scan_status == "clean"
    assert await total(f, WhatsAppBroadcastGroupModel) == 0
    assert await total(f, WhatsAppMessageLogModel) == 0


async def test_creation_preserves_rejected_rows_source_and_exact_cross_connection_receipt(
    contact_import,
):
    f = contact_import
    source_id, payload, preview = await prepared(f)
    source = await f.session.get(MCPContactImportUploadModel, source_id)
    original = copy.deepcopy(source.workbook_snapshot)
    assert preview["accepted_count"] == 2 and preview["rejected_count"] == 4
    assert preview["rejected_counts"] == {
        "duplicate_phone": 1,
        "missing_phone": 1,
        "invalid_phone": 1,
        "missing_name": 1,
    }
    assert preview["excluded_sheets"] == ["Notes"] and preview["rejected_rows_truncated"] is False
    result = await create(f, payload)
    await f.session.commit()
    token, _ = await f.connect(["mcp:upload", "mcp:change"])
    assert await create(f, payload, token=token) == result
    await f.session.commit()
    assert await total(f, WhatsAppBroadcastGroupModel) == 1
    assert await total(f, WhatsAppBroadcastRecipientModel) == 2
    assert await total(f, WhatsAppBroadcastRejectedContactModel) == 4
    assert await total(f, WhatsAppBroadcastSupportContactModel) == 1
    assert await total(f, WhatsAppMessageLogModel) == 0
    source = await f.session.get(MCPContactImportUploadModel, source_id)
    assert source.workbook_snapshot == original and source.consumed_operation_id == uuid.UUID(
        result["operation_id"]
    )
    assert result["data"]["messages_queued"] == 0 and "recipients" not in result["data"]
    recipient = await f.session.scalar(
        select(WhatsAppBroadcastRecipientModel).where(
            WhatsAppBroadcastRecipientModel.name == "Aarav"
        )
    )
    assert recipient.imported_fields["staff_code"] == "ONE"
    assert recipient.imported_fields["staff_code_2"] == "TWO"
    audit = await f.session.scalar(
        select(AuditLogModel).where(AuditLogModel.action == "mcp.contact_broadcast_created")
    )
    audit_json = json.dumps(audit.metadata_json)
    assert "987654" not in audit_json and "Aarav" not in audit_json


@pytest.mark.parametrize("change", ["hash", "name", "support", "agency", "opt_in", "mapping"])
async def test_changed_review_or_invalid_input_rolls_back_every_business_row(
    contact_import, change
):
    f = contact_import
    source_id, payload, _ = await prepared(f)
    if change == "hash":
        payload["preview_sha256"] = "0" * 64
    if change == "name":
        payload["name"] = "Changed name"
    if change == "support":
        payload["support_contacts"][0]["phone_number"] = "badbad"
    if change == "agency":
        payload["agency_id"] = str(uuid.uuid4())
    if change == "opt_in":
        payload["recipient_opt_in_confirmed"] = False
    if change == "mapping":
        payload["column_mappings"][0]["phone_column"] = 1
    with pytest.raises((MCPOperationError, MCPAuthError)):
        await create(f, payload)
    await f.session.rollback()
    assert await total(f, WhatsAppBroadcastGroupModel) == 0
    assert await total(f, MCPOperationModel) == 0
    source = await f.session.get(MCPContactImportUploadModel, source_id)
    assert source.consumed_operation_id is None and source.workbook_snapshot["row_count"] > 0


async def test_upload_cannot_be_consumed_twice_or_read_by_another_grant(contact_import):
    f = contact_import
    _, payload, _ = await prepared(f)
    token, principal = await f.connect(["mcp:upload", "mcp:change"])
    with pytest.raises(ArtifactError):
        await f.contacts.get(principal, payload["upload_id"])
    await create(f, payload)
    await f.session.commit()
    with pytest.raises(MCPOperationError, match="contact_upload_already_used"):
        await create(f, payload, key="second-intent-same-upload")
    await f.session.rollback()
    changed = payload | {"name": "Different"}
    with pytest.raises(MCPOperationError, match="idempotency_conflict"):
        await create(f, changed, token=token)
    assert await total(f, WhatsAppBroadcastGroupModel) == 1


@pytest.mark.parametrize("scope", [["mcp:change"], ["mcp:upload"]])
async def test_successful_replay_requires_both_current_capabilities(contact_import, scope):
    f = contact_import
    _, payload, _ = await prepared(f)
    await create(f, payload)
    await f.session.commit()
    token, _ = await f.connect(scope)
    with pytest.raises(MCPAuthError):
        await create(f, payload, token=token)


@pytest.mark.parametrize("state", ["revoked", "expired", "inactive_agency", "missing_broadcast"])
async def test_expired_or_lost_authority_never_leaks_source_or_saved_record(contact_import, state):
    f = contact_import
    source_id, payload, _ = await prepared(f)
    if state == "missing_broadcast":
        receipt = await create(f, payload)
        await f.session.commit()
        await f.session.execute(
            delete(WhatsAppBroadcastGroupModel).where(
                WhatsAppBroadcastGroupModel.id == uuid.UUID(receipt["data"]["broadcast_id"])
            )
        )
    elif state == "revoked":
        grant = await f.session.get(MCPGrantModel, f.principal.grant_id)
        grant.revoked_at = datetime.now(UTC)
    elif state == "expired":
        row = await f.session.get(MCPContactImportUploadModel, source_id)
        row.created_at = datetime.now(UTC) - timedelta(hours=2)
        row.expires_at = datetime.now(UTC) - timedelta(hours=1)
    else:
        await f.session.refresh(f.agency)
        f.agency.is_active = False
    await f.session.commit()
    with pytest.raises((MCPOperationError, MCPAuthError)):
        await create(f, payload)


@pytest.mark.parametrize("failure", [MalwareScanRejectedError, MalwareScannerUnavailableError])
async def test_malware_or_unavailable_scanner_leaves_no_staged_source(contact_import, failure):
    f = contact_import
    f.scanner.error = failure
    response = await upload(f)
    assert response.status_code in {422, 503}
    assert await total(f, MCPContactImportUploadModel) == 0 and not f.storage.objects


@pytest.mark.parametrize(
    "headers,status",
    [
        ({"X-Artifact-SHA256": "0" * 64}, 422),
        ({"X-Artifact-Size": "5242881"}, 422),
        ({"Content-Type": "application/pdf"}, 415),
        ({"Authorization": "Bearer dashboard-jwt"}, 401),
    ],
)
async def test_http_transport_rejects_wrong_checksum_size_media_or_credential(
    contact_import, headers, status
):
    response = await upload(contact_import, **headers)
    assert response.status_code == status
    assert await total(contact_import, MCPContactImportUploadModel) == 0


@pytest.mark.parametrize(
    "kind", ["formula", "external", "macro", "doctype", "wide", "long", "rows", "zip_bomb"]
)
async def test_active_or_excessive_workbooks_fail_before_staging(contact_import, kind):
    content = workbook()
    if kind == "formula":
        content = workbook([["Name", "Phone"], ["=SUM(1,2)", "9876543210"]])
    if kind == "external":
        content = rewrite_archive(
            content,
            "_rels/.rels",
            b'<Relationships><Relationship TargetMode="External" Target="https://invalid.test/"/></Relationships>',
        )
    if kind == "macro":
        content = rewrite_archive(
            content,
            "[Content_Types].xml",
            b'<Types><Override ContentType="application/vnd.ms-excel.sheet.macroEnabled.main+xml"/></Types>',
        )
    if kind == "doctype":
        content = rewrite_archive(
            content, "_rels/.rels", b'<!DOCTYPE x [<!ENTITY y "z">]><x>&y;</x>'
        )
    if kind == "wide":
        content = workbook([["x"] * 65])
    if kind == "long":
        content = workbook([["x" * 1025]])
    if kind == "rows":
        content = workbook([["x", str(index)] for index in range(2001)])
    if kind == "zip_bomb":
        content = rewrite_archive(content, "xl/worksheets/sheet1.xml", b"x" * (3 * 1024 * 1024))
    response = await upload(contact_import, content)
    assert response.status_code == 422, response.text
    assert await total(contact_import, MCPContactImportUploadModel) == 0
    assert contact_import.evidence.records[-1].scan_status == "malformed"


def test_more_than_500_failed_rows_are_not_silently_truncated():
    snapshot = snapshot_workbook(
        workbook([["Name", "Phone"], *[[f"Name {i}", "bad"] for i in range(501)]])
    )
    with pytest.raises(MCPOperationError, match="contact_import_capacity_exceeded"):
        map_contacts(
            snapshot,
            support=CONTACT_IMPORT_SUPPORT.mapping,
            filename="contacts.xlsx",
            mappings=[
                ContactColumnMapping(
                    sheet_name="Contacts", header_row=1, phone_column=2, name_column=1
                )
            ],
        )


def test_explicit_mapping_composes_names_and_does_not_guess_other_sheets():
    snapshot = snapshot_workbook(
        workbook([["First", "Last", "Mobile"], ["Ada", "Lovelace", "9876543210"]])
    )
    parsed = map_contacts(
        snapshot,
        support=CONTACT_IMPORT_SUPPORT.mapping,
        filename="contacts.xlsx",
        mappings=[
            ContactColumnMapping(
                sheet_name="Contacts",
                header_row=1,
                phone_column=3,
                given_name_column=1,
                surname_column=2,
            )
        ],
    )
    assert len(parsed.contacts) == 1 and parsed.contacts[0].name == "Ada Lovelace"
    assert parsed.excluded_sheets == ["Notes"]


@pytest.mark.parametrize("boundary", ["cell_count", "total_text"])
def test_total_workbook_cell_and_text_budgets_fail_without_truncation(boundary):
    rows = (
        [[uuid.uuid4().hex for _ in range(64)] for _ in range(782)]
        if boundary == "cell_count"
        else [[uuid.uuid4().hex * 32 for _ in range(64)] for _ in range(34)]
    )
    with pytest.raises(ValueError, match="Workbook (cell|text|snapshot) limit"):
        snapshot_workbook(workbook(rows))


async def test_parser_cancellation_drains_thread_before_releasing_request(
    contact_import, monkeypatch
):
    f = contact_import
    entered, release = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()

    def slow_parser(_content):
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(5)
        return {"schema_version": 1, "sheets": [], "row_count": 0}

    monkeypatch.setattr(
        "app.infrastructure.security.contact_spreadsheet_security.snapshot_workbook", slow_parser
    )
    content = workbook()
    task = asyncio.create_task(
        f.contacts.stage(
            f.principal,
            agency_id=f.agency_id,
            filename="contacts.xlsx",
            expected_size=len(content),
            expected_sha256=hashlib.sha256(content).hexdigest(),
            body=chunks(content),
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not f.storage.objects and await total(f, MCPContactImportUploadModel) == 0


async def test_revocation_during_scan_blocks_storage_and_staging(contact_import, monkeypatch):
    f = contact_import
    original = f.contact_security.validate_spreadsheet

    async def scan_then_revoke(**kwargs):
        result = await original(**kwargs)
        grant = await f.session.get(MCPGrantModel, f.principal.grant_id)
        grant.revoked_at = datetime.now(UTC)
        await f.session.commit()
        return result

    monkeypatch.setattr(f.contact_security, "validate_spreadsheet", scan_then_revoke)
    response = await upload(f)
    assert response.status_code in {401, 403}
    assert not f.storage.objects and await total(f, MCPContactImportUploadModel) == 0


async def test_post_creation_failure_preserves_source_and_rolls_back_entire_import(
    contact_import, monkeypatch
):
    from app.infrastructure.repositories.audit_log_repository import AuditLogRepository

    f = contact_import
    source_id, payload, _ = await prepared(f)
    original = AuditLogRepository.record

    async def fail_creation(self, **kwargs):
        if kwargs["action"] == "mcp.contact_broadcast_created":
            raise RuntimeError("synthetic audit failure")
        return await original(self, **kwargs)

    monkeypatch.setattr(AuditLogRepository, "record", fail_creation)
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        await create(f, payload)
    await f.session.rollback()
    assert await total(f, WhatsAppBroadcastGroupModel) == 0
    assert await total(f, WhatsAppBroadcastRecipientModel) == 0
    assert await total(f, WhatsAppBroadcastRejectedContactModel) == 0
    row = await f.session.get(MCPContactImportUploadModel, source_id)
    assert row.consumed_operation_id is None and row.storage_key in f.storage.objects


async def test_real_sdk_preview_create_replay_and_sensitive_read_audit(contact_import, monkeypatch):
    from contextlib import asynccontextmanager

    from mcp.server import MCPServer
    from mcp.server.auth.provider import AccessToken

    from app.presentation.mcp.contact_import_tools import register_contact_import_tools

    f = contact_import
    _, payload, _ = await prepared(f)
    app = FastAPI()

    @asynccontextmanager
    async def sessions():
        yield f.session

    app.state.mcp_session_factory, app.state.mcp_operations = sessions, {}
    server = MCPServer("Contact import fixture")
    register_contact_import_tools(app, server, f.settings)
    monkeypatch.setattr(
        "app.presentation.mcp.invocation.get_access_token",
        lambda: AccessToken(
            token=f.token,
            client_id=f.principal.client_id,
            scopes=["mcp:upload", "mcp:change"],
            subject=str(f.principal.user_id),
            resource=f.principal.resource,
        ),
    )
    tools = {tool.name: tool for tool in await server.list_tools()}
    assert tools["create_contact_broadcast"].meta == {"capability": "mcp:change"}
    inspect = (
        await server.call_tool(
            "inspect_contact_workbook",
            {"upload_id": payload["upload_id"], "sheet_name": "Contacts", "limit": 1},
        )
    ).structured_content
    assert inspect["rows"][0]["cells"] == ["Name", "Phone", "Staff code"]
    draft = {key: value for key, value in payload.items() if key != "preview_sha256"}
    preview = (
        await server.call_tool("preview_contact_broadcast", {"draft": draft})
    ).structured_content
    assert preview["preview_sha256"] == payload["preview_sha256"] and preview["rejected_count"] == 4
    request = {"draft": payload, "idempotency_key": "sdk-contact-creation-001"}
    created = (await server.call_tool("create_contact_broadcast", request)).structured_content
    assert created["receipt"]["data"]["accepted_count"] == 2
    replay = (await server.call_tool("create_contact_broadcast", request)).structured_content
    assert created["receipt"] == replay["receipt"] and created["audit_id"] != replay["audit_id"]
    assert not f.session.in_transaction()
    assert await total(f, WhatsAppMessageLogModel) == 0
    actions = list((await f.session.scalars(select(AuditLogModel.action))).all())
    assert "mcp.contact_upload_inspected" in actions and "mcp.contact_upload_previewed" in actions
