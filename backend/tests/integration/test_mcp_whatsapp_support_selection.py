"""Compose saved support discovery with a passport-link preview, without sending.

The fixture already owns a linked upload group, ready header media and an opted-in
broadcast. This qualifies read-to-prepare composition, not new-import-to-group-link
acceptance or actual Codex conversational behavior.
"""

import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from mcp import Client
from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken
from sqlalchemy import func, select

from app.infrastructure.database.mcp_communication_models import (
    MCPWhatsAppOutboxModel,
    MCPWhatsAppPlanModel,
)
from app.infrastructure.database.models import (
    AuditLogModel,
    WhatsAppBroadcastSupportContactModel,
    WhatsAppMessageLogModel,
    WhatsAppPhoneWelcomeModel,
    WhatsAppRecipientMessageStateModel,
)
from app.presentation.mcp.whatsapp_message_tools import register_whatsapp_message_tools
from app.presentation.mcp.whatsapp_read_tools import register_whatsapp_read_tools
from tests.integration.test_mcp_operations import operations_fixture as operations_fixture
from tests.integration.test_mcp_whatsapp_intents import intent_fixture as intent_fixture
from tests.integration.test_mcp_whatsapp_messages import message_fixture as message_fixture
from tests.unit.presentation.test_whatsapp_repeatable_reminders import broadcast as broadcast


async def test_tool_discovered_support_phone_selects_exact_passport_preview_without_queue(
    message_fixture,
    monkeypatch,
):
    fixture = message_fixture
    now = datetime.now(UTC)
    requested_name, requested_phone = "Trip support", "+919123456788"
    other_phone = "+919123456700"
    fixture.contact.name = requested_name
    fixture.contact.created_at = now - timedelta(days=2)
    # The wrong same-name contact deliberately sorts first. A name/first-row
    # shortcut would select it instead of the explicitly requested phone.
    fixture.session.add(
        WhatsAppBroadcastSupportContactModel(
            id=uuid.uuid4(),
            agency_id=fixture.broadcast.agency_id,
            broadcast_group_id=fixture.broadcast.id,
            name=requested_name,
            phone_number=other_phone,
            normalized_phone_number=other_phone,
            created_at=now - timedelta(days=1),
        )
    )
    # Established eligibility is fixture state, not a provider action in this test.
    fixture.session.add_all(
        [
            WhatsAppRecipientMessageStateModel(
                broadcast_group_id=fixture.broadcast.id,
                agency_id=fixture.broadcast.agency_id,
                recipient_id=fixture.recipient.id,
                message_type="welcome",
                status="delivered",
                batch_id=uuid.uuid4(),
                submitted_at=now,
                provider_status_at=now,
            ),
            WhatsAppPhoneWelcomeModel(
                agency_id=fixture.broadcast.agency_id,
                normalized_phone_number=fixture.recipient.normalized_phone_number,
                status="delivered",
                attempt_id=uuid.uuid4(),
                attempt_kind="broadcast",
            ),
        ]
    )
    await fixture.session.commit()
    app = FastAPI()

    @asynccontextmanager
    async def sessions():
        yield fixture.session

    app.state.mcp_session_factory, app.state.mcp_operations = sessions, {}
    server = MCPServer("Synthetic support-contact composition")
    register_whatsapp_read_tools(server, app, fixture.settings)
    register_whatsapp_message_tools(app, server, fixture.settings)
    grant = fixture.grants[0]
    token = AccessToken(
        token=fixture.tokens[0],
        client_id=grant.client_id,
        scopes=["mcp:read", "mcp:communicate", "mcp:upload"],
        subject=str(fixture.actor.id),
        resource=fixture.settings.mcp.resource,
        claims={"grant_id": str(grant.id)},
    )
    monkeypatch.setattr("app.presentation.mcp.invocation.get_access_token", lambda: token)
    read_arguments = {
        "broadcast_id": str(fixture.broadcast.id),
        "agency_id": str(fixture.broadcast.agency_id),
        "kind": "support_contacts",
        "page_size": 2,
    }
    async with Client(server, mode="legacy") as client:
        redacted = (
            await client.call_tool("list_whatsapp_audience", read_arguments)
        ).structured_content
        assert len(redacted["items"]) == 2
        assert {row["name"] for row in redacted["items"]} == {requested_name}
        assert all("normalized_phone_number" not in row for row in redacted["items"])
        assert requested_phone not in json.dumps(redacted)
        assert other_phone not in json.dumps(redacted)

        details = (
            await client.call_tool(
                "list_whatsapp_audience",
                {
                    **read_arguments,
                    "include_contact_details": True,
                },
            )
        ).structured_content
        assert details["send_eligibility_evaluated"] is False
        assert details["next_cursor"] is None
        assert details["items"][0]["normalized_phone_number"] == other_phone
        matching = [
            row
            for row in details["items"]
            if row["name"] == requested_name and row["normalized_phone_number"] == requested_phone
        ]
        assert len(matching) == 1
        selected = matching[0]
        assert selected["id"] != details["items"][0]["id"]

        # The support ID comes exclusively from the registered read tool result.
        draft = {
            "broadcast_id": str(fixture.broadcast.id),
            "message_type": "passport_link",
            "message_content": "Please submit your passport for the trip.",
            "passport_intro": "Use your secure trip upload link.",
            "media_handle": fixture.handle,
            "recipient_ids": [str(fixture.recipient.id)],
            "client_group_id": str(fixture.group.id),
            "support_contact_ids": [selected["id"]],
        }
        prepared = (
            await client.call_tool(
                "prepare_whatsapp_message",
                {
                    "draft": draft,
                    "idempotency_key": "discovered-support-preview-001",
                },
            )
        ).structured_content

    assert "receipt" in prepared, prepared
    data = prepared["receipt"]["data"]
    assert data["status"] == "prepared" and data["confirmation_required"] is True
    assert len(data["plan_hash"]) == 64
    preview = data["preview"]
    assert preview["request"]["support_contact_ids"] == [selected["id"]]
    assert len(preview["recipients"]) == 1
    exact = preview["recipients"][0]
    assert exact["recipient_id"] == str(fixture.recipient.id)
    assert requested_name in exact["rendered_message"]
    assert requested_phone in exact["rendered_message"]
    assert other_phone not in exact["rendered_message"]
    assert requested_name in exact["body_parameters"][-1]
    assert requested_phone in exact["body_parameters"][-1]
    assert other_phone not in json.dumps(preview)
    assert await fixture.session.scalar(select(func.count()).select_from(MCPWhatsAppPlanModel)) == 1
    for model in (MCPWhatsAppOutboxModel, WhatsAppMessageLogModel):
        assert await fixture.session.scalar(select(func.count()).select_from(model)) == 0
    assert (
        await fixture.session.scalar(
            select(func.count()).select_from(WhatsAppBroadcastSupportContactModel)
        )
        == 2
    )
    assert (
        await fixture.session.scalar(
            select(func.count())
            .select_from(AuditLogModel)
            .where(AuditLogModel.action == "mcp.whatsapp.contact_read")
        )
        == 1
    )
    fixture.provider.assert_not_awaited()
