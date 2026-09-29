"""PostgreSQL contact-source consumption races; isolated unique fixtures only."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update

from app.application.mcp.contact_broadcasts import (
    ContactBroadcastDraft,
    contact_broadcast_operation,
    project_import,
)
from app.application.mcp.credentials import credential_hash
from app.application.mcp.operations import MCPOperationError, MCPOperationService
from app.infrastructure.database.mcp_contact_import_models import MCPContactImportUploadModel
from app.infrastructure.database.mcp_models import MCPGrantModel
from app.infrastructure.database.models import (
    AgencyModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastRejectedContactModel,
)
from app.infrastructure.security.contact_spreadsheet_security import XLSX_MEDIA, snapshot_workbook
from app.presentation.mcp.contact_import_support import CONTACT_IMPORT_SUPPORT
from tests.integration.test_mcp_contact_imports import workbook
from tests.service_integration.test_mcp_concurrency_postgresql import mcp_sessions as mcp_sessions
from tests.service_integration.test_mcp_operations_postgresql import (
    operation_sessions as operation_sessions,
)

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1",
        reason="isolated PostgreSQL required",
    ),
]


@pytest.fixture
async def contact_sessions(operation_sessions):
    sessions, settings, user_id, grants, tokens = operation_sessions
    handle = "gcmcp_contacts_" + base64.urlsafe_b64encode(os.urandom(48)).decode()
    async with sessions() as session:
        await session.execute(
            update(MCPGrantModel)
            .where(MCPGrantModel.id.in_(grants))
            .values(capabilities=["mcp:change", "mcp:upload"])
        )
        agency = AgencyModel(
            id=uuid.uuid4(), name="Contact import race", email=f"{uuid.uuid4()}@example.test"
        )
        session.add(agency)
        await session.flush()
        now, content, source_id = datetime.now(UTC), workbook(), uuid.uuid4()
        source = MCPContactImportUploadModel(
            id=source_id,
            agency_id=agency.id,
            user_id=user_id,
            original_grant_id=grants[0],
            handle_hash=credential_hash(handle, settings.app_secret_key),
            storage_key=f"mcp-transfers/v1/{source_id}",
            filename="contacts.xlsx",
            media_type=XLSX_MEDIA,
            byte_size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            workbook_snapshot=snapshot_workbook(content),
            created_at=now,
            expires_at=now + timedelta(hours=1),
        )
        session.add(source)
        draft = ContactBroadcastDraft(
            upload_id=handle,
            agency_id=agency.id,
            name="Race broadcast",
            organizing_company_name="Fixture company",
            support_contacts=[{"name": "Support", "phone_number": "9876543299"}],
            recipient_opt_in_confirmed=True,
            column_mappings=[
                {"sheet_name": "Contacts", "header_row": 1, "phone_column": 2, "name_column": 1}
            ],
        )
        _, preview = project_import(source, draft, support=CONTACT_IMPORT_SUPPORT)
        payload = draft.model_dump(mode="json") | {"preview_sha256": preview["preview_sha256"]}
        await session.commit()
    return sessions, settings, tokens, agency.id, source_id, payload


async def create(f, *, key="pg-contact-import-001", token_index=0):
    async with f[0]() as session:
        try:
            result = await MCPOperationService(
                session, f[1], [contact_broadcast_operation(f[1], CONTACT_IMPORT_SUPPORT)]
            ).execute(
                access_token=f[2][token_index],
                operation_name="create_contact_broadcast",
                idempotency_key=key,
                payload=f[5],
            )
            await session.commit()
            return result
        except BaseException:
            await session.rollback()
            raise


async def assert_one_import(f):
    async with f[0]() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(WhatsAppBroadcastGroupModel)
                .where(WhatsAppBroadcastGroupModel.agency_id == f[3])
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(WhatsAppBroadcastRecipientModel)
                .where(WhatsAppBroadcastRecipientModel.agency_id == f[3])
            )
            == 2
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(WhatsAppBroadcastRejectedContactModel)
                .where(WhatsAppBroadcastRejectedContactModel.agency_id == f[3])
            )
            == 4
        )
        row = await session.get(MCPContactImportUploadModel, f[4])
        assert row.consumed_operation_id is not None and row.workbook_snapshot["row_count"] == 8


async def test_same_key_six_claims_create_once_and_replay_across_connections(contact_sessions):
    f = contact_sessions
    results = await asyncio.wait_for(asyncio.gather(*(create(f) for _ in range(6))), 20)
    assert all(result == results[0] for result in results)
    assert await create(f, token_index=1) == results[0]
    await assert_one_import(f)


async def test_distinct_intent_keys_cannot_consume_same_workbook_twice(contact_sessions):
    f = contact_sessions
    results = await asyncio.wait_for(
        asyncio.gather(
            create(f, key="pg-contact-first-intent"),
            create(f, key="pg-contact-second-intent"),
            return_exceptions=True,
        ),
        20,
    )
    assert sum(isinstance(result, dict) for result in results) == 1
    errors = [result for result in results if isinstance(result, MCPOperationError)]
    assert len(errors) == 1 and errors[0].code == "contact_upload_already_used"
    await assert_one_import(f)


async def test_failure_after_business_insert_rolls_back_source_claim_and_retry_succeeds(
    contact_sessions, monkeypatch
):
    from app.infrastructure.repositories.audit_log_repository import AuditLogRepository

    f = contact_sessions
    original = AuditLogRepository.record

    async def fail(self, **kwargs):
        if kwargs["action"] == "mcp.contact_broadcast_created":
            raise RuntimeError("synthetic failure after insertion")
        return await original(self, **kwargs)

    monkeypatch.setattr(AuditLogRepository, "record", fail)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        await create(f)
    async with f[0]() as session:
        source = await session.get(MCPContactImportUploadModel, f[4])
        assert source.consumed_operation_id is None
        assert (
            await session.scalar(
                select(func.count())
                .select_from(WhatsAppBroadcastGroupModel)
                .where(WhatsAppBroadcastGroupModel.agency_id == f[3])
            )
            == 0
        )
    monkeypatch.setattr(AuditLogRepository, "record", original)
    await create(f)
    await assert_one_import(f)
