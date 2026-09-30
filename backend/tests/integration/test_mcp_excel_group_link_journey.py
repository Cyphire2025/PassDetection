"""New workbook import -> actual SDK group/link -> exact passport-link preview.

All identities, storage and provider boundaries are synthetic. This closes a
local composition gap; it is not real Codex or customer delivery acceptance.
"""

from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.infrastructure.database.gc_mobile_models import MobilePassengerIdentityModel
from app.infrastructure.database.mcp_communication_models import (
    MCPWhatsAppOutboxModel,
    MCPWhatsAppPlanModel,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    UserModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
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


async def test_new_import_group_link_requires_delivered_welcome_for_exact_passport_preview(
    excel_message_journey,
):
    f = excel_message_journey
    f.settings.whatsapp_passport_link_template_name = "passport_link_v1"
    owner = UserModel(
        id=uuid.uuid4(),
        email="journey-group-owner@example.test",
        full_name="Explicit synthetic group owner",
        hashed_password="fixture-not-a-credential",
        role="agency_staff",
        agency_id=uuid.UUID(f.agency_id),
        is_active=True,
    )
    f.session.add(owner)
    await f.session.commit()
    owner_id = str(owner.id)
    content = workbook([["Name", "Phone"], ["Aarav", "9876543210"], ["Mira", "9876543212"]])
    staged = await f.upload_workbook(content)
    draft = broadcast_draft(f, staged["upload_id"])
    draft["support_contacts"] = [
        {"name": "Help desk", "phone_number": "9876543298"},
        {"name": "Help desk", "phone_number": "9876543299"},
    ]
    group_request = {
        "group": {
            "agency_id": f.agency_id,
            "owner_user_id": owner_id,
            "name": "Explicit October collection group",
            "destination": "Japan",
            "travel_date": "2026-10-10",
            "return_date": "2026-10-18",
            "timezone": "Asia/Tokyo",
            "import_only": False,
        },
        "idempotency_key": "journey-create-collection-group-001",
    }

    async with f.sdk() as sdk:
        _preview, import_request, imported = await create_reviewed(sdk, draft)
        broadcast_id = imported["receipt"]["data"]["broadcast_id"]
        recipients = await all_audience(sdk, broadcast_id)
        assert len(recipients) == 2
        # Pagination orders retained rows by their stable keys, not the user's
        # intended name. Put the other person first and resolve the exact name.
        recipients.sort(key=lambda row: row["name"], reverse=True)
        assert recipients[0]["name"] == "Mira"
        selected_recipients = [row for row in recipients if row["name"] == "Aarav"]
        assert len(selected_recipients) == 1
        selected_recipient_id = selected_recipients[0]["id"]
        assert await count(f, ClientGroupModel) == 0
        created = await tool(sdk, "create_group", group_request)
        group_id = created["receipt"]["data"]["group_id"]
        assert created["receipt"]["data"]["public_collection_enabled"] is True
        assert await count(f, ClientGroupWhatsAppBroadcastLinkModel) == 0
        group = await f.session.get(ClientGroupModel, uuid.UUID(group_id))
        upload_url = f.settings.mcp.frontend_origin.rstrip("/") + "/upload/" + group.token
        retained_token = group.token
        await f.session.commit()

        # Both saved contacts came from this import. Names alone are ambiguous;
        # the user's explicitly provided phone resolves the tool-returned ID.
        support = await tool(
            sdk,
            "list_whatsapp_audience",
            {
                "broadcast_id": broadcast_id,
                "kind": "support_contacts",
                "include_contact_details": True,
            },
        )
        assert len(support["items"]) == 2
        assert {row["name"] for row in support["items"]} == {"Help desk"}
        selected = [
            row for row in support["items"] if row["normalized_phone_number"] == "+919876543299"
        ]
        assert len(selected) == 1
        support_id = selected[0]["id"]
        header = await f.upload_header(broadcast_id)
        message_request = {
            "draft": {
                "broadcast_id": broadcast_id,
                "message_type": "passport_link",
                "message_content": "Please complete the October trip details.",
                "media_handle": header["media_handle"],
                "recipient_ids": [selected_recipient_id],
                "passport_intro": "Upload your passport using the collection link.",
                "client_group_id": group_id,
                "support_contact_ids": [support_id],
            },
            "idempotency_key": "journey-prepare-linked-passport-001",
        }
        unlinked = await sdk.call_tool(
            "prepare_whatsapp_message",
            {**message_request, "idempotency_key": "journey-deny-unlinked-passport-001"},
        )
        assert unlinked.structured_content["error"] == "whatsapp_plan_audience_unavailable"
        assert await count(f, MCPWhatsAppPlanModel) == 0
        selection = {
            "agency_id": f.agency_id,
            "group_id": group_id,
            "broadcast_id": broadcast_id,
        }
        inspection = await tool(sdk, "inspect_group_broadcast_addition", {"selection": selection})
        assert inspection["outcome"] == "would_add"
        assert inspection["source_row_count"] == 0
        assert inspection["recipient_additions"] == inspection["mobile_identity_additions"] == 0
        link_request = {
            "association": {**selection, "expected_revision": inspection["source_revision"]},
            "idempotency_key": "journey-add-import-collection-link-001",
        }
        linked = await tool(sdk, "add_group_broadcast_link", link_request)
        assert linked["receipt"]["data"]["outcome"] == "added"
        assert linked["receipt"]["data"]["recipients_added"] == 0
        assert linked["receipt"]["data"]["mobile_identities_added"] == 0

        before_welcome = await sdk.call_tool(
            "prepare_whatsapp_message",
            {**message_request, "idempotency_key": "journey-deny-missing-welcome-001"},
        )
        assert before_welcome.structured_content["error"] == "whatsapp_preparation_blocked"
        assert await count(f, MCPWhatsAppPlanModel) == 0
        f.provider.assert_not_awaited()

        welcome_request = {
            "draft": {
                "broadcast_id": broadcast_id,
                "message_type": "welcome",
                "message_content": "Welcome to the October trip.",
                "media_handle": header["media_handle"],
                "recipient_ids": [selected_recipient_id],
            },
            "idempotency_key": "journey-prepare-before-passport-001",
        }
        welcome = await tool(sdk, "prepare_whatsapp_message", welcome_request)
        welcome_data = welcome["receipt"]["data"]
        welcome_confirmation = {
            "plan_id": welcome_data["plan_id"],
            "plan_hash": welcome_data["plan_hash"],
            "idempotency_key": "journey-confirm-before-passport-001",
        }
        await tool(sdk, "confirm_whatsapp_message", welcome_confirmation)
        await f.session.commit()
        assert await mcp_publication.run_mcp_whatsapp_publication() == 1
        await worker_runtime.run_whatsapp_broadcast(**f.publication.await_args.kwargs["payload"])
        submitted = await tool(sdk, "inspect_whatsapp_intent", {"plan_id": welcome_data["plan_id"]})
        assert submitted["receipts"]["status_counts"]["submitted"] == 1
        assert submitted["receipts"]["confirmed_delivery_count"] == 0
        after_submission = await sdk.call_tool(
            "prepare_whatsapp_message",
            {**message_request, "idempotency_key": "journey-deny-submitted-welcome-001"},
        )
        assert after_submission.structured_content["error"] == "whatsapp_preparation_blocked"
        assert await count(f, MCPWhatsAppPlanModel) == 1

        receipt_ids = await persist_verified_receipts(
            f.session,
            [
                VerifiedReceipt(
                    f.settings.whatsapp_phone_number_id,
                    "wamid.synthetic.3210",
                    "delivered",
                    datetime.now(UTC),
                    None,
                )
            ],
        )
        await f.session.commit()
        await reconcile_pending_receipts(f.session, receipt_ids=receipt_ids)
        await f.session.commit()
        delivered = await tool(sdk, "inspect_whatsapp_intent", {"plan_id": welcome_data["plan_id"]})
        assert delivered["receipts"]["status_counts"]["delivered"] == 1
        assert delivered["receipts"]["confirmed_delivery_count"] == 1
        prepared = await tool(sdk, "prepare_whatsapp_message", message_request)
        data = prepared["receipt"]["data"]
        exact = data["preview"]["recipients"]
        assert len(exact) == 1
        assert exact[0]["recipient_id"] == selected_recipient_id
        assert upload_url in exact[0]["rendered_message"]
        assert "9876543299" in exact[0]["rendered_message"]
        assert "9876543298" not in exact[0]["rendered_message"]
        snapshot = copy.deepcopy(prepared["receipt"])
        assert (
            await count(f, WhatsAppMessageLogModel) == await count(f, MCPWhatsAppOutboxModel) == 1
        )

    # Recover each accepted operation through another actual SDK session with
    # original immutable inputs/keys, without creating or sending again.
    async with f.sdk() as sdk:
        for name, request, receipt in (
            ("create_contact_broadcast", import_request, imported["receipt"]),
            ("create_group", group_request, created["receipt"]),
            ("add_group_broadcast_link", link_request, linked["receipt"]),
            ("prepare_whatsapp_message", welcome_request, welcome["receipt"]),
            ("prepare_whatsapp_message", message_request, snapshot),
        ):
            replay = await tool(sdk, name, request)
            assert replay["receipt"] == receipt
        wrong = await sdk.call_tool(
            "confirm_whatsapp_message",
            {
                "plan_id": data["plan_id"],
                "plan_hash": "0" * 64,
                "idempotency_key": "journey-wrong-linked-plan-hash-001",
            },
        )
        assert wrong.structured_content["error"] == "whatsapp_plan_hash_mismatch"

    assert await count(f, WhatsAppBroadcastGroupModel) == await count(f, ClientGroupModel) == 1
    assert await count(f, ClientGroupWhatsAppBroadcastLinkModel) == 1
    assert await count(f, WhatsAppBroadcastRecipientModel) == 2
    assert await count(f, MobilePassengerIdentityModel) == 0
    assert await count(f, MCPWhatsAppPlanModel) == 2
    assert await count(f, WhatsAppMessageLogModel) == await count(f, MCPWhatsAppOutboxModel) == 1
    logs = (await f.session.scalars(select(WhatsAppMessageLogModel))).all()
    assert len(logs) == 1 and logs[0].message_type == "welcome" and logs[0].status == "delivered"
    group = await f.session.get(ClientGroupModel, uuid.UUID(group_id), populate_existing=True)
    assert group.token == retained_token
    f.provider.assert_awaited_once()
    f.publication.assert_awaited_once()
    f.media_provider.assert_awaited_once()
