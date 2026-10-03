"""Exact native source/group binding and canonical retained workbook merges."""

from __future__ import annotations

import hashlib
import io
import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken
from openpyxl import Workbook
from sqlalchemy import func, select, update

from app.application.mcp.credentials import MCPAuthError, credential_hash
from app.application.mcp.group_workbook_import import group_workbook_definition
from app.application.mcp.group_workbook_plan import (
    CHECKPOINT_KEY,
    GroupWorkbookDraft,
)
from app.application.mcp.group_workbook_source import prepare_group_workbook
from app.application.mcp.operations import (
    MCPDatabaseContext,
    MCPOperationError,
    MCPOperationService,
)
from app.domain.exceptions.exceptions import ValidationError as BusinessValidationError
from app.infrastructure.database.mcp_contact_import_models import MCPContactImportUploadModel
from app.infrastructure.database.mcp_models import MCPControlModel
from app.infrastructure.database.mcp_native_transfer_models import MCPNativeTransferModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    AuditLogModel,
    PassengerQRTokenModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.mobile_group_capacity import SqlAlchemyGroupPassengerCapacityGuard
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.security.contact_spreadsheet_security import XLSX_MEDIA, snapshot_workbook
from app.presentation.mcp.group_workbook_tools import (
    GROUP_WORKBOOK_SUPPORT,
    register_group_workbook_tools,
)
from tests.integration.test_mcp_business_admin_tools import business_admin as business_admin
from tests.integration.test_mcp_operations import operations_fixture as operations_fixture


def workbook_bytes():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Passengers"
    sheet.append(["Passenger Name", "Passport Number", "Email", "WhatsApp Number", "Notes"])
    sheet.append(
        [
            "Updated existing",
            "AB1234567",
            "updated@example.com",
            "+919876543210",
            "UNTRUSTED SOURCE TEXT",
        ]
    )
    sheet.append(["New person", "AB1234568", "new@example.com", "+919876543211", "Retained source"])
    sheet.append(["New person", "AB1234568", "new@example.com", "+919876543211", "Retained source"])
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


class MemoryOriginal:
    def __init__(self, session, payload):
        self.session, self.payload, self.calls, self.after_read = session, payload, 0, None

    async def stream_file(self, key, *, start, expected_bytes):
        assert not self.session.in_transaction(), "DB locks must be released before storage parsing"
        assert key.startswith("mcp-transfers/v1/") and start == 0
        self.calls += 1
        if self.after_read:
            await self.after_read()
        for offset in range(0, len(self.payload), 1024):
            yield self.payload[offset : offset + 1024]


@pytest.fixture
async def group_workbook(business_admin):
    base, agencies, organization, group, access, _ = business_admin
    session, settings, actor, grants, tokens = base
    control = await session.get(MCPControlModel, 1)
    names = ["upload_group_workbook", "preview_group_workbook_import", "import_group_workbook"]
    control.allowed_write_tools = names
    control.allowed_write_sections = ["group_excel_imports"]
    for grant in grants:
        grant.capabilities = ["mcp:change", "mcp:upload"]
        grant.allowed_write_sections = ["group_excel_imports"]
    now, content = datetime.now(UTC), workbook_bytes()
    handle = "gcmcp_contacts_" + "a" * 64
    upload = MCPContactImportUploadModel(
        id=uuid.uuid4(),
        user_id=actor.id,
        original_grant_id=grants[0].id,
        agency_id=agencies[0].id,
        handle_hash=credential_hash(handle, settings.app_secret_key),
        storage_key=f"mcp-transfers/v1/{uuid.uuid4()}",
        filename="Passengers.xlsx",
        media_type=XLSX_MEDIA,
        byte_size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        workbook_snapshot=snapshot_workbook(content),
        created_at=now,
        expires_at=now + timedelta(hours=1),
    )
    passenger = PassportSubmissionModel(
        id=uuid.uuid4(),
        agency_id=agencies[0].id,
        group_id=group.id,
        client_name="Original existing",
        client_email="original@example.com",
        client_phone="+919876543210",
        image_s3_key="RETAINED-PASSPORT-IMAGE",
        status="confirmed",
        confirmed_fields={"passport_number": "AB1234567", "nationality": "INDIAN"},
        extracted_fields={"passport_number": "AB1234567"},
        staff_metadata={"office_note": "retained"},
        client_reviewed_at=now - timedelta(days=1),
    )
    session.add_all([upload, passenger])
    await session.flush()
    ticket = MCPNativeTransferModel(
        id=uuid.uuid4(),
        original_grant_id=grants[0].id,
        user_id=actor.id,
        security_version=1,
        kind="upload_workbook",
        purpose="group_workbook",
        agency_id=agencies[0].id,
        group_id=group.id,
        filename=upload.filename,
        media_type=XLSX_MEDIA,
        byte_size=upload.byte_size,
        sha256=upload.sha256,
        token_hash="1" * 64,
        idempotency_hash="2" * 64,
        payload_hash="3" * 64,
        status="completed",
        created_at=now,
        expires_at=now + timedelta(minutes=10),
        completed_at=now,
        workbook_id=upload.id,
    )
    qr = PassengerQRTokenModel(
        id=uuid.uuid4(),
        agency_id=agencies[0].id,
        passenger_id=passenger.id,
        token_hash="4" * 64,
        qr_payload="pdatt:existing-fixture-credential",
        is_active=True,
        token_version=1,
        expires_at=now + timedelta(days=1),
    )
    session.add_all([ticket, qr])
    await session.commit()
    from app.application.mcp.authorization import MCPAuthorizationService

    principal = await MCPAuthorizationService(session, settings).verify_access(
        tokens[0], "mcp:upload"
    )
    await session.commit()
    draft = GroupWorkbookDraft(
        upload_id=handle, agency_id=agencies[0].id, group_id=group.id, source_sha256=upload.sha256
    )
    service = MCPOperationService(
        session, settings, [group_workbook_definition(settings, GROUP_WORKBOOK_SUPPORT)]
    )
    return SimpleNamespace(
        session=session,
        settings=settings,
        actor=actor,
        grants=grants,
        tokens=tokens,
        agency_id=agencies[0].id,
        group_id=group.id,
        passenger_id=passenger.id,
        qr_id=qr.id,
        upload_id=upload.id,
        ticket_id=ticket.id,
        draft=draft,
        principal=principal,
        service=service,
        storage=MemoryOriginal(session, content),
        source_bytes=content,
    )


async def preview(f):
    value = await prepare_group_workbook(
        MCPDatabaseContext(f.session, f.principal, uuid.uuid4()),
        f.settings,
        f.draft,
        support=GROUP_WORKBOOK_SUPPORT,
        storage=f.storage,
    )
    await f.session.commit()
    return value


async def apply(f, value, *, key="exact-group-import-request-001", connection=0):
    request = {**f.draft.model_dump(mode="json"), "preview_sha256": value["preview_sha256"]}
    return await f.service.execute(
        access_token=f.tokens[connection],
        operation_name="import_group_workbook",
        idempotency_key=key,
        payload=request,
    )


async def test_original_preview_and_atomic_import_match_canonical_identity_merge_and_safe_retries(
    group_workbook,
):
    f = group_workbook
    original = (await f.session.get(MCPContactImportUploadModel, f.upload_id)).workbook_snapshot
    literal = json.dumps(original, sort_keys=True)
    await f.session.commit()
    value = await preview(f)
    assert (value["imported_count"], value["updated_count"], value["skipped_count"]) == (1, 1, 1)
    assert f.storage.calls == 1 and value["business_import"] == "not_started"
    assert await f.session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 1
    receipt = await apply(f, value)
    assert await apply(f, value, connection=1) == receipt
    records = list((await f.session.scalars(select(PassportSubmissionModel))).all())
    retained = next(row for row in records if row.id == f.passenger_id)
    added = next(row for row in records if row.id != f.passenger_id)
    assert retained.image_s3_key == "RETAINED-PASSPORT-IMAGE" and retained.status == "confirmed"
    assert (
        retained.client_name == "Updated existing"
        and retained.confirmed_fields["nationality"] == "INDIAN"
    )
    assert retained.staff_metadata["office_note"] == "retained"
    assert added.status == "client_submitted" and added.image_s3_key.endswith(".placeholder")
    assert await f.session.scalar(select(func.count()).select_from(PassengerQRTokenModel)) == 1
    qr = await f.session.get(PassengerQRTokenModel, f.qr_id)
    assert qr.qr_payload == "pdatt:existing-fixture-credential" and qr.is_active is True
    source = await f.session.get(MCPContactImportUploadModel, f.upload_id)
    assert (
        json.dumps({key: source.workbook_snapshot[key] for key in original}, sort_keys=True)
        == literal
    )
    assert source.consumed_operation_id == uuid.UUID(receipt["operation_id"])
    safe = json.dumps(receipt)
    assert (
        f.draft.upload_id not in safe
        and "RETAINED-PASSPORT-IMAGE" not in safe
        and "UNTRUSTED SOURCE TEXT" not in safe
    )
    assert f.storage.payload == f.source_bytes and f.storage.calls == 1
    source.created_at, source.expires_at = (
        datetime.now(UTC) - timedelta(hours=2),
        datetime.now(UTC) - timedelta(hours=1),
    )
    await f.session.flush()
    assert await apply(f, value, connection=1) == receipt
    observed = await f.service.inspect(
        access_token=f.tokens[1], operation_id=uuid.UUID(receipt["operation_id"])
    )
    assert observed["status"] == "succeeded"
    assert await f.session.scalar(select(func.count()).select_from(MCPOperationModel)) == 1


@pytest.mark.parametrize(
    "change",
    [
        "group",
        "purpose",
        "status",
        "grant",
        "user",
        "security",
        "sha256",
        "size",
        "mime",
        "unbound",
    ],
)
async def test_only_completed_native_ticket_for_original_group_can_read_source(
    group_workbook, change
):
    f = group_workbook
    ticket = await f.session.get(MCPNativeTransferModel, f.ticket_id)
    if change == "group":
        ticket.group_id = uuid.uuid4()
    elif change == "purpose":
        ticket.purpose = "contact_broadcast"
    elif change == "status":
        ticket.status = "pending"
    elif change == "grant":
        ticket.original_grant_id = f.grants[1].id
    elif change == "user":
        other = UserModel(
            id=uuid.uuid4(),
            email="other-owner@example.com",
            hashed_password="unusable-fixture",
            full_name="Other owner",
            role=f.actor.role,
            agency_id=f.agency_id,
        )
        f.session.add(other)
        await f.session.flush()
        ticket.user_id = other.id
    elif change == "security":
        ticket.security_version += 1
    elif change == "sha256":
        ticket.sha256 = "f" * 64
    elif change == "size":
        ticket.byte_size += 1
    elif change == "mime":
        ticket.media_type = "application/pdf"
    else:
        await f.session.delete(ticket)
    await f.session.commit()
    with pytest.raises(MCPOperationError, match="native_group_workbook_required"):
        await preview(f)
    assert f.storage.calls == 0
    assert (
        CHECKPOINT_KEY
        not in (await f.session.get(MCPContactImportUploadModel, f.upload_id)).workbook_snapshot
    )


async def test_completed_transport_expiry_does_not_shorten_valid_workbook_lifetime(group_workbook):
    f = group_workbook
    ticket = await f.session.get(MCPNativeTransferModel, f.ticket_id)
    ticket.created_at = datetime.now(UTC) - timedelta(minutes=30)
    ticket.expires_at = datetime.now(UTC) - timedelta(minutes=20)
    ticket.completed_at = datetime.now(UTC) - timedelta(minutes=25)
    await f.session.commit()
    assert (await preview(f))["source_rows"] == 3


async def test_original_hash_and_fresh_authority_rechecked_after_storage_and_parser(group_workbook):
    f = group_workbook
    f.storage.payload = f.source_bytes[:-1] + b"x"
    with pytest.raises(MCPOperationError, match="group_workbook_source_changed"):
        await preview(f)
    assert (
        CHECKPOINT_KEY
        not in (await f.session.get(MCPContactImportUploadModel, f.upload_id)).workbook_snapshot
    )
    await f.session.commit()
    f.storage.payload = f.source_bytes

    async def disable():
        await f.session.execute(
            update(MCPControlModel).where(MCPControlModel.id == 1).values(write_enabled=False)
        )
        await f.session.commit()

    f.storage.after_read = disable
    with pytest.raises(MCPAuthError):
        await preview(f)
    assert (
        CHECKPOINT_KEY
        not in (await f.session.get(MCPContactImportUploadModel, f.upload_id)).workbook_snapshot
    )


@pytest.mark.parametrize(
    "change", ["passenger_value", "group_revision", "preview_hash", "bound_group"]
)
async def test_import_fences_changed_roster_group_hash_or_original_target(group_workbook, change):
    f = group_workbook
    value = await preview(f)
    if change == "passenger_value":
        passenger = await f.session.get(PassportSubmissionModel, f.passenger_id)
        passenger.client_name = "Later website correction"
    elif change == "group_revision":
        from app.infrastructure.database.models import ClientGroupModel

        group = await f.session.get(ClientGroupModel, f.group_id)
        group.roster_revision += 1
    elif change == "preview_hash":
        value["preview_sha256"] = "f" * 64
    else:
        ticket = await f.session.get(MCPNativeTransferModel, f.ticket_id)
        ticket.group_id = uuid.uuid4()
    await f.session.flush()
    with pytest.raises(MCPOperationError):
        await apply(f, value)
    assert await f.session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 1
    assert await f.session.scalar(select(func.count()).select_from(MCPOperationModel)) == 0
    assert (
        await f.session.get(MCPContactImportUploadModel, f.upload_id)
    ).consumed_operation_id is None


async def test_one_source_claim_and_business_audit_failure_leave_no_partial_import(
    group_workbook, monkeypatch
):
    f = group_workbook
    value = await preview(f)
    original = AuditLogRepository.record
    monkeypatch.setattr(
        AuditLogRepository, "record", AsyncMock(side_effect=RuntimeError("qualified audit failure"))
    )
    with pytest.raises(RuntimeError, match="qualified audit failure"):
        await apply(f, value)
    assert await f.session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 1
    assert (
        await f.session.get(PassportSubmissionModel, f.passenger_id)
    ).client_name == "Original existing"
    assert (
        await f.session.get(MCPContactImportUploadModel, f.upload_id)
    ).consumed_operation_id is None
    monkeypatch.setattr(AuditLogRepository, "record", original)
    await apply(f, value)
    with pytest.raises(MCPOperationError, match="group_workbook_already_used"):
        await apply(f, value, key="different-source-consume-001")
    assert await f.session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 2


async def test_ambiguous_existing_identity_blocks_preview_without_checkpoint_or_merge(
    group_workbook,
):
    f = group_workbook
    f.session.add(
        PassportSubmissionModel(
            id=uuid.uuid4(),
            agency_id=f.agency_id,
            group_id=f.group_id,
            client_name="Conflicting record",
            image_s3_key="RETAINED-OTHER-IMAGE",
            status="confirmed",
            confirmed_fields={"passport_number": "AB1234567"},
        )
    )
    await f.session.commit()
    with pytest.raises(MCPOperationError, match="group_workbook_identity_conflict"):
        await preview(f)
    assert (
        await f.session.get(MCPContactImportUploadModel, f.upload_id)
    ).consumed_operation_id is None
    assert (
        CHECKPOINT_KEY
        not in (await f.session.get(MCPContactImportUploadModel, f.upload_id)).workbook_snapshot
    )
    assert await f.session.scalar(select(func.count()).select_from(MCPOperationModel)) == 0


async def test_capacity_guard_and_missing_preparation_fail_before_updates(
    group_workbook, monkeypatch
):
    f = group_workbook
    with pytest.raises(MCPOperationError, match="group_workbook_preview_required"):
        await apply(f, {"preview_sha256": "f" * 64})
    value = await preview(f)
    monkeypatch.setattr(
        SqlAlchemyGroupPassengerCapacityGuard,
        "assert_available",
        AsyncMock(side_effect=BusinessValidationError("quota", field="group_capacity")),
    )
    with pytest.raises(MCPOperationError, match="group_workbook_group_capacity"):
        await apply(f, value)
    passenger = await f.session.get(PassportSubmissionModel, f.passenger_id)
    assert passenger.client_name == "Original existing"
    assert await f.session.scalar(select(func.count()).select_from(MCPOperationModel)) == 0


async def test_actual_sdk_preview_and_import_commit_safe_metadata_without_file_bytes(
    group_workbook, monkeypatch
):
    f = group_workbook
    app, server = FastAPI(), MCPServer("Native group workbook fixture")

    @asynccontextmanager
    async def sessions():
        try:
            yield f.session
        except BaseException:
            await f.session.rollback()
            raise

    app.state.mcp_session_factory, app.state.mcp_operations, app.state.mcp_artifact_storage = (
        sessions,
        {},
        f.storage,
    )
    register_group_workbook_tools(server, app, f.settings)
    monkeypatch.setattr(
        "app.presentation.mcp.invocation.get_access_token",
        lambda: AccessToken(
            token=f.tokens[0],
            client_id=f.grants[0].client_id,
            scopes=["mcp:upload", "mcp:change"],
            subject=str(f.actor.id),
        ),
    )
    result = (
        await server.call_tool(
            "preview_group_workbook_import", {"draft": f.draft.model_dump(mode="json")}
        )
    ).structured_content
    assert result["imported_count"] == 1
    imported = (
        await server.call_tool(
            "import_group_workbook",
            {
                "import_request": {
                    **f.draft.model_dump(mode="json"),
                    "preview_sha256": result["preview_sha256"],
                },
                "idempotency_key": "native-sdk-group-import-001",
            },
        )
    ).structured_content
    assert imported["receipt"]["data"]["imported_count"] == 1 and not f.session.in_transaction()
    audits = list(
        (
            await f.session.scalars(
                select(AuditLogModel).where(AuditLogModel.action.like("mcp.tool.%"))
            )
        ).all()
    )
    assert len(audits) == 2 and all(row.result == "success" for row in audits)
