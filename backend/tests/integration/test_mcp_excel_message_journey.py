"""Synthetic Excel → actual MCP HTTP → exact welcome plan → fake dispatch receipts.

This is local component integration, not real Codex or Meta delivery qualification.
"""

from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.infrastructure.database.mcp_communication_models import (
    MCPWhatsAppOutboxModel,
    MCPWhatsAppPlanModel,
)
from app.infrastructure.database.mcp_contact_import_models import MCPContactImportUploadModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    AuditLogModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastRejectedContactModel,
    WhatsAppBroadcastSupportContactModel,
    WhatsAppMessageLogModel,
)
from app.infrastructure.whatsapp import mcp_publication, worker_runtime
from app.infrastructure.whatsapp.receipt_inbox import VerifiedReceipt, persist_verified_receipts
from app.infrastructure.whatsapp.receipt_runtime import reconcile_pending_receipts
from tests.integration.test_mcp_authorization import mcp_fixture as mcp_fixture
from tests.integration.test_mcp_contact_imports import workbook
from tests.mcp_excel_message_journey_fixtures import (
    all_audience,
    broadcast_draft,
    create_reviewed,
    tool,
)
from tests.mcp_excel_message_journey_fixtures import (
    excel_message_journey as excel_message_journey,
)


async def count(f, model):
    return await f.session.scalar(select(func.count()).select_from(model))


def message_draft(broadcast_id, handle, recipients):
    return {
        "broadcast_id": broadcast_id,
        "message_type": "welcome",
        "message_content": "Welcome to our September trip.",
        "media_handle": handle,
        "recipient_ids": [item["id"] for item in recipients],
    }


async def test_excel_to_message_reconnect_and_receipts_never_duplicate_or_infer_delivery(
    excel_message_journey,
):
    f = excel_message_journey
    content = workbook(
        [
            ["Name", "Phone", "Staff code"],
            ["Aarav", "9876543210", "ONE"],
            ["Aarav duplicate", "+919876543210", "TWO"],
            ["Missing", "", "THREE"],
            ["Invalid", "not-a-number", "FOUR"],
            ["", "9876543211", "FIVE"],
            ["Mira", "9876543212", "SIX"],
            ["Rehan", "9876543213", "SEVEN"],
        ]
    )
    staged = await f.upload_workbook(content)
    assert staged["business_import"] == "not_started"
    assert len(staged["worksheets"]) == 2
    assert (
        await count(f, WhatsAppBroadcastGroupModel) == await count(f, WhatsAppMessageLogModel) == 0
    )
    source = await f.session.scalar(select(MCPContactImportUploadModel))
    source_id, original_snapshot = source.id, copy.deepcopy(source.workbook_snapshot)
    original_key = source.storage_key
    await f.session.commit()

    async with f.sdk() as sdk:
        inspected = await tool(
            sdk,
            "inspect_contact_workbook",
            {"upload_id": staged["upload_id"], "sheet_name": "Contacts", "limit": 1},
        )
        assert inspected["rows"][0]["cells"] == ["Name", "Phone", "Staff code"]
        preview, create_request, created = await create_reviewed(
            sdk, broadcast_draft(f, staged["upload_id"])
        )
        assert preview["accepted_count"] == 3 and preview["rejected_count"] == 4
        assert preview["rejected_counts"] == {
            "duplicate_phone": 1,
            "missing_phone": 1,
            "invalid_phone": 1,
            "missing_name": 1,
        }
        assert (
            preview["excluded_sheets"] == ["Notes"] and preview["rejected_rows_truncated"] is False
        )
        assert {row["sheet_name"] for row in preview["rejected_rows"]} == {"Contacts"}
        assert {row["source_file_name"] for row in preview["rejected_rows"]} == {"journey.xlsx"}
        assert created["receipt"]["data"]["messages_queued"] == 0
        broadcast_id = created["receipt"]["data"]["broadcast_id"]
        recipients = await all_audience(sdk, broadcast_id)
        rejected = await all_audience(sdk, broadcast_id, kind="rejected_contacts")
        assert len(recipients) == 3 and len(rejected) == 4
        assert len({row["id"] for row in recipients}) == 3
        assert all("phone_number" not in row for row in recipients)
        support = await all_audience(sdk, broadcast_id, kind="support_contacts")
        assert len(support) == 1 and support[0]["name"] == "Help desk"
        support_id = uuid.UUID(support[0]["id"])
        assert "phone_number" not in support[0] and "normalized_phone_number" not in support[0]
        details = await tool(
            sdk,
            "list_whatsapp_audience",
            {
                "broadcast_id": broadcast_id,
                "agency_id": f.agency_id,
                "kind": "support_contacts",
                "include_contact_details": True,
            },
        )
        assert details["items"][0]["id"] == str(support_id)
        assert details["items"][0]["normalized_phone_number"] == "+919876543299"
        assert details["send_eligibility_evaluated"] is False
        assert details["content_trust"] == "untrusted_business_data"
        contact_audit = await f.session.scalar(
            select(AuditLogModel).where(AuditLogModel.action == "mcp.whatsapp.contact_read")
        )
        assert contact_audit.metadata_json == {"authorized_result_count": 1}
        assert await count(f, WhatsAppMessageLogModel) == await count(f, MCPWhatsAppPlanModel) == 0
        await f.session.commit()
        f.provider.assert_not_awaited()
        f.publication.assert_not_awaited()

    # New SDK session models a lost create response/reconnect: same business key,
    # same result, fresh audit, no second broadcast and no re-uploaded workbook.
    async with f.sdk() as sdk:
        replay = await tool(sdk, "create_contact_broadcast", create_request)
        assert replay["receipt"] == created["receipt"] and replay["audit_id"] != created["audit_id"]
        assert await all_audience(sdk, broadcast_id, kind="support_contacts") == support
        conflicting = await sdk.call_tool(
            "create_contact_broadcast",
            {
                **create_request,
                "draft": {**create_request["draft"], "name": "Different requested broadcast"},
            },
        )
        assert conflicting.structured_content["error"] == "idempotency_conflict"
        assert await count(f, WhatsAppBroadcastGroupModel) == 1
        await f.session.commit()
        header = await f.upload_header(broadcast_id)
        assert header["status"] == "ready" and header["messages_queued"] == 0
        assert await f.upload_header(broadcast_id) == header
        f.media_provider.assert_awaited_once()
        draft = message_draft(broadcast_id, header["media_handle"], recipients)
        prepare_request = {"draft": draft, "idempotency_key": "journey-prepare-welcome-001"}
        prepared = await tool(sdk, "prepare_whatsapp_message", prepare_request)
        plan_data = prepared["receipt"]["data"]
        assert len(plan_data["preview"]["recipients"]) == 3
        assert {row["recipient_id"] for row in plan_data["preview"]["recipients"]} == {
            row["id"] for row in recipients
        }
        assert all(
            row["template_name"] == "welcome_v1" for row in plan_data["preview"]["recipients"]
        )
        assert all(
            row["header_parameters"] == [header["media_handle"]]
            for row in plan_data["preview"]["recipients"]
        )
        assert all(
            draft["message_content"] in row["rendered_message"]
            for row in plan_data["preview"]["recipients"]
        )
        assert (
            await count(f, WhatsAppMessageLogModel) == await count(f, MCPWhatsAppOutboxModel) == 0
        )
        f.provider.assert_not_awaited()
        await f.session.commit()
        confirm_request = {
            "plan_id": plan_data["plan_id"],
            "plan_hash": plan_data["plan_hash"],
            "idempotency_key": "journey-confirm-welcome-001",
        }
        wrong = await sdk.call_tool(
            "confirm_whatsapp_message", {**confirm_request, "plan_hash": "0" * 64}
        )
        assert wrong.structured_content["error"] == "whatsapp_plan_hash_mismatch"
        assert wrong.structured_content["completeness"] == "unavailable"
        assert await count(f, WhatsAppMessageLogModel) == 0
        await f.session.commit()
        confirmed = await tool(sdk, "confirm_whatsapp_message", confirm_request)
        queued = await tool(sdk, "inspect_whatsapp_intent", {"plan_id": plan_data["plan_id"]})
        assert queued["receipts"]["status_counts"]["queued"] == 3
        assert queued["receipts"]["confirmed_delivery_count"] == 0
        f.provider.assert_not_awaited()

    async with f.sdk() as sdk:
        assert (await tool(sdk, "prepare_whatsapp_message", prepare_request))[
            "receipt"
        ] == prepared["receipt"]
        assert (await tool(sdk, "confirm_whatsapp_message", confirm_request))[
            "receipt"
        ] == confirmed["receipt"]
        # A lost broker acknowledgement preserves the same batch. No provider I/O
        # occurs until the actual worker consumes its already-published payload.
        f.publication.side_effect = RuntimeError("Synthetic broker acknowledgement lost")
        assert await mcp_publication.run_mcp_whatsapp_publication() == 0
        payload = f.publication.await_args.kwargs["payload"]
        await worker_runtime.run_whatsapp_broadcast(**payload)
        partial = await tool(sdk, "inspect_whatsapp_intent", {"plan_id": plan_data["plan_id"]})
        counts = partial["receipts"]["status_counts"]
        assert {
            key: counts[key]
            for key in ("submitted", "delivery_unknown", "failed", "sent", "delivered")
        } == {"submitted": 1, "delivery_unknown": 1, "failed": 1, "sent": 0, "delivered": 0}
        assert partial["receipts"]["confirmed_delivery_count"] == 0
        assert f.provider.await_count == 3
        await worker_runtime.run_whatsapp_broadcast(**payload)
        assert f.provider.await_count == 3
        outbox = await f.session.scalar(select(MCPWhatsAppOutboxModel))
        outbox.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        await f.session.commit()
        assert await mcp_publication.run_mcp_whatsapp_publication() == 0
        assert f.publication.await_count == 1
        # Recorded provider events, not submission or completed dispatch, establish
        # sent/delivered. Unknown and definitive failure remain separate throughout.
        for status in ("sent", "delivered"):
            ids = await persist_verified_receipts(
                f.session,
                [
                    VerifiedReceipt(
                        f.settings.whatsapp_phone_number_id,
                        "wamid.synthetic.3210",
                        status,
                        datetime.now(UTC),
                        None,
                    )
                ],
            )
            await f.session.commit()
            await reconcile_pending_receipts(f.session, receipt_ids=ids)
            await f.session.commit()
            observed = await tool(sdk, "inspect_whatsapp_intent", {"plan_id": plan_data["plan_id"]})
            assert observed["receipts"]["status_counts"][status] == 1
            assert observed["receipts"]["status_counts"]["delivery_unknown"] == 1
            assert observed["receipts"]["confirmed_delivery_count"] == (
                1 if status == "delivered" else 0
            )
        assert (await tool(sdk, "confirm_whatsapp_message", confirm_request))[
            "receipt"
        ] == confirmed["receipt"]
        assert f.provider.await_count == 3

    assert await count(f, WhatsAppBroadcastGroupModel) == 1
    assert await count(f, WhatsAppBroadcastRecipientModel) == 3
    assert await count(f, WhatsAppBroadcastRejectedContactModel) == 4
    assert await count(f, WhatsAppBroadcastSupportContactModel) == 1
    saved_support = await f.session.get(WhatsAppBroadcastSupportContactModel, support_id)
    assert (
        saved_support.name == "Help desk" and str(saved_support.broadcast_group_id) == broadcast_id
    )
    assert await count(f, WhatsAppMessageLogModel) == 3
    assert await count(f, MCPWhatsAppPlanModel) == await count(f, MCPWhatsAppOutboxModel) == 1
    assert await count(f, MCPOperationModel) == 3
    operation = await f.session.get(
        MCPOperationModel, uuid.UUID(confirmed["receipt"]["operation_id"])
    )
    assert operation.status == "unknown" and operation.initial_result == confirmed["receipt"]
    source = await f.session.get(MCPContactImportUploadModel, source_id, populate_existing=True)
    assert (
        source.workbook_snapshot == original_snapshot
        and f.storage.objects[original_key][0] == content
    )
    recipient = await f.session.scalar(
        select(WhatsAppBroadcastRecipientModel).where(
            WhatsAppBroadcastRecipientModel.name == "Aarav"
        )
    )
    assert (
        recipient.imported_fields["staff_code"] == "ONE"
        and recipient.imported_fields["staff_code_2"] == "TWO"
    )
    assert all(
        row.removed_at is None
        for row in (await f.session.scalars(select(WhatsAppBroadcastRecipientModel))).all()
    )


@pytest.mark.parametrize("missing", ["agency_id", "name", "support_contacts", "column_mappings"])
async def test_incomplete_import_details_never_guess_or_create(excel_message_journey, missing):
    f = excel_message_journey
    staged = await f.upload_workbook(workbook())
    draft = broadcast_draft(f, staged["upload_id"])
    draft.pop(missing)
    async with f.sdk() as sdk:
        result = await sdk.call_tool("preview_contact_broadcast", {"draft": draft})
        assert result.is_error
    assert await count(f, WhatsAppBroadcastGroupModel) == await count(f, MCPOperationModel) == 0
    f.provider.assert_not_awaited()
    f.media_provider.assert_not_awaited()


async def test_101_imported_contacts_require_explicit_selection_without_truncation(
    excel_message_journey,
):
    f = excel_message_journey
    content = workbook(
        [["Name", "Phone"]]
        + [[f"Synthetic traveller {index}", str(9876500000 + index)] for index in range(101)]
    )
    staged = await f.upload_workbook(content)
    async with f.sdk() as sdk:
        preview, _request, created = await create_reviewed(
            sdk, broadcast_draft(f, staged["upload_id"])
        )
        assert preview["accepted_count"] == 101 and preview["rejected_count"] == 0
        broadcast_id = created["receipt"]["data"]["broadcast_id"]
        recipients = await all_audience(sdk, broadcast_id, page_size=100)
        assert len(recipients) == len({row["id"] for row in recipients}) == 101
        header = await f.upload_header(broadcast_id)
        key = "journey-explicit-selection-001"
        oversized = await sdk.call_tool(
            "prepare_whatsapp_message",
            {
                "draft": message_draft(broadcast_id, header["media_handle"], recipients),
                "idempotency_key": key,
            },
        )
        assert oversized.is_error
        assert await count(f, MCPWhatsAppPlanModel) == await count(f, WhatsAppMessageLogModel) == 0
        await f.session.commit()
        # A user-selected first page is a separate explicit audience. Its saved
        # preview contains exactly those IDs; the remaining person is preserved.
        prepared = await tool(
            sdk,
            "prepare_whatsapp_message",
            {
                "draft": message_draft(broadcast_id, header["media_handle"], recipients[:100]),
                "idempotency_key": key,
            },
        )
        selected = prepared["receipt"]["data"]["preview"]["recipients"]
        assert len(selected) == 100
        assert {row["recipient_id"] for row in selected} == {row["id"] for row in recipients[:100]}
        assert recipients[100]["id"] not in {row["recipient_id"] for row in selected}
    assert await count(f, WhatsAppBroadcastRecipientModel) == 101
    assert await count(f, MCPWhatsAppPlanModel) == 1
    assert await count(f, MCPWhatsAppOutboxModel) == await count(f, WhatsAppMessageLogModel) == 0
    f.provider.assert_not_awaited()
    f.publication.assert_not_awaited()


@pytest.mark.parametrize("missing", ["message_content", "media_handle", "recipient_ids"])
async def test_missing_message_details_do_not_guess_or_prepare(excel_message_journey, missing):
    f = excel_message_journey
    staged = await f.upload_workbook(workbook())
    async with f.sdk() as sdk:
        _preview, _request, created = await create_reviewed(
            sdk, broadcast_draft(f, staged["upload_id"])
        )
        broadcast_id = created["receipt"]["data"]["broadcast_id"]
        recipients = await all_audience(sdk, broadcast_id)
        header = await f.upload_header(broadcast_id)
        draft = message_draft(broadcast_id, header["media_handle"], recipients)
        draft.pop(missing)
        result = await sdk.call_tool(
            "prepare_whatsapp_message",
            {
                "draft": draft,
                "idempotency_key": "journey-incomplete-message-001",
            },
        )
        assert result.is_error
    assert await count(f, MCPOperationModel) == 1  # Contact creation only.
    assert await count(f, MCPWhatsAppPlanModel) == await count(f, MCPWhatsAppOutboxModel) == 0
    assert await count(f, WhatsAppMessageLogModel) == 0
    f.provider.assert_not_awaited()
    f.publication.assert_not_awaited()
