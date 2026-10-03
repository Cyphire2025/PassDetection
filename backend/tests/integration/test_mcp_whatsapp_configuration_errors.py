"""Canonical configuration failures are non-input errors with rollback-safe retries."""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken
from sqlalchemy import func, select

from app.infrastructure.database.mcp_communication_models import (
    MCPWhatsAppOutboxModel,
    MCPWhatsAppPlanModel,
)
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import AuditLogModel, WhatsAppMessageLogModel
from app.infrastructure.whatsapp import template_settings
from app.presentation.api.v1.routes import whatsapp_send
from app.presentation.mcp import whatsapp_snapshots
from app.presentation.mcp.whatsapp_message_tools import register_whatsapp_message_tools
from tests.integration.test_mcp_operations import operations_fixture as operations_fixture
from tests.integration.test_mcp_whatsapp_intents import intent_fixture as intent_fixture
from tests.integration.test_mcp_whatsapp_messages import message_fixture as message_fixture
from tests.unit.presentation.test_whatsapp_repeatable_reminders import broadcast as broadcast


@pytest.fixture
async def message_sdk(message_fixture, monkeypatch):
    fixture = message_fixture
    app = FastAPI()

    @asynccontextmanager
    async def sessions():
        yield fixture.session

    app.state.mcp_session_factory, app.state.mcp_operations = sessions, {}
    server = MCPServer("Synthetic configuration failure test")
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
    arguments = {
        "draft": {
            "broadcast_id": str(fixture.broadcast.id),
            "message_type": "welcome",
            "message_content": "Welcome to the reviewed trip.",
            "media_handle": fixture.handle,
            "recipient_ids": [str(fixture.recipient.id)],
        },
        "idempotency_key": "configuration-retry-same-intent-001",
    }
    return fixture, server, arguments


async def assert_no_business_effects(fixture):
    for model in (
        MCPOperationModel,
        MCPWhatsAppPlanModel,
        MCPWhatsAppOutboxModel,
        WhatsAppMessageLogModel,
    ):
        assert await fixture.session.scalar(select(func.count()).select_from(model)) == 0
    fixture.provider.assert_not_awaited()


@pytest.mark.parametrize("missing", ["credentials", "template"])
async def test_real_queue_configuration_error_is_non_input_audited_and_same_key_recovers(
    message_sdk,
    monkeypatch,
    missing,
):
    fixture, server, arguments = message_sdk
    broken = fixture.settings.model_copy(
        update={
            "whatsapp_access_token"
            if missing == "credentials"
            else "whatsapp_welcome_template_name": ""
        }
    )
    monkeypatch.setattr(whatsapp_send, "get_settings", lambda: broken)
    monkeypatch.setattr(template_settings, "get_settings", lambda: broken)
    failed = (await server.call_tool("prepare_whatsapp_message", arguments)).structured_content
    assert failed["error"] == "whatsapp_service_unavailable", failed
    assert "requires_input" not in failed and "receipt" not in failed
    assert failed["completeness"] == "unavailable"
    assert "not missing recipient or message information" in failed["message"]
    await assert_no_business_effects(fixture)
    audit = await fixture.session.scalar(
        select(AuditLogModel).where(AuditLogModel.action == "mcp.tool.prepare_whatsapp_message")
    )
    assert audit.result == "blocked" and str(audit.id) == failed["audit_id"]
    assert audit.entity_id is None
    await fixture.session.commit()

    monkeypatch.setattr(whatsapp_send, "get_settings", lambda: fixture.settings)
    monkeypatch.setattr(template_settings, "get_settings", lambda: fixture.settings)
    recovered = (await server.call_tool("prepare_whatsapp_message", arguments)).structured_content
    assert "receipt" in recovered, recovered
    assert recovered["receipt"]["status"] == "succeeded"
    assert recovered["receipt"]["data"]["confirmation_required"] is True
    replay = (await server.call_tool("prepare_whatsapp_message", arguments)).structured_content
    assert replay["receipt"]["operation_id"] == recovered["receipt"]["operation_id"]
    assert replay["receipt"]["data"] == recovered["receipt"]["data"]
    assert await fixture.session.scalar(select(func.count()).select_from(MCPOperationModel)) == 1
    assert await fixture.session.scalar(select(func.count()).select_from(MCPWhatsAppPlanModel)) == 1
    for model in (MCPWhatsAppOutboxModel, WhatsAppMessageLogModel):
        assert await fixture.session.scalar(select(func.count()).select_from(model)) == 0
    fixture.provider.assert_not_awaited()


async def test_missing_recipient_opt_in_remains_input_error_without_side_effects(message_sdk):
    fixture, server, arguments = message_sdk
    fixture.broadcast.recipient_opt_in_confirmed_at = None
    await fixture.session.commit()
    result = (await server.call_tool("prepare_whatsapp_message", arguments)).structured_content
    assert result["error"] == "whatsapp_preparation_blocked", result
    assert result["requires_input"] is True
    await assert_no_business_effects(fixture)


async def test_configuration_failure_at_confirmation_preserves_exact_plan_and_retry_key(
    message_sdk,
    monkeypatch,
):
    fixture, server, arguments = message_sdk
    prepared = (await server.call_tool("prepare_whatsapp_message", arguments)).structured_content
    preview = prepared["receipt"]["data"]
    confirmation = {
        "plan_id": preview["plan_id"],
        "plan_hash": preview["plan_hash"],
        "user_confirmed": True,
        "idempotency_key": "configuration-confirm-same-intent-001",
    }
    broken = fixture.settings.model_copy(update={"whatsapp_access_token": ""})
    monkeypatch.setattr(whatsapp_send, "get_settings", lambda: broken)
    failed = (await server.call_tool("confirm_whatsapp_message", confirmation)).structured_content
    assert failed["error"] == "whatsapp_service_unavailable"
    assert "requires_input" not in failed
    plan = await fixture.session.scalar(select(MCPWhatsAppPlanModel))
    assert plan.status == "prepared" and plan.snapshot_hash == preview["plan_hash"]
    assert plan.batch_id is None and plan.confirmed_at is None
    assert await fixture.session.scalar(select(func.count()).select_from(MCPOperationModel)) == 1
    for model in (MCPWhatsAppOutboxModel, WhatsAppMessageLogModel):
        assert await fixture.session.scalar(select(func.count()).select_from(model)) == 0
    await fixture.session.commit()

    monkeypatch.setattr(whatsapp_send, "get_settings", lambda: fixture.settings)
    wrong_hash = (
        await server.call_tool(
            "confirm_whatsapp_message",
            {
                **confirmation,
                "plan_hash": "0" * 64,
            },
        )
    ).structured_content
    assert wrong_hash["error"] == "whatsapp_plan_hash_mismatch"
    confirmed = (
        await server.call_tool("confirm_whatsapp_message", confirmation)
    ).structured_content
    assert confirmed["receipt"]["status"] == "queued"
    replay = (await server.call_tool("confirm_whatsapp_message", confirmation)).structured_content
    assert replay["receipt"] == confirmed["receipt"]
    for model in (MCPWhatsAppPlanModel, MCPWhatsAppOutboxModel, WhatsAppMessageLogModel):
        assert await fixture.session.scalar(select(func.count()).select_from(model)) == 1
    assert await fixture.session.scalar(select(func.count()).select_from(MCPOperationModel)) == 2
    fixture.provider.assert_not_awaited()


async def test_unavailable_error_never_exposes_raw_provider_details(
    message_sdk, monkeypatch, caplog
):
    fixture, server, arguments = message_sdk
    sentinel = "PRIVATE_PROVIDER_TOKEN_AND_RESPONSE_SENTINEL"
    queue = AsyncMock(side_effect=HTTPException(503, detail={"provider_token": sentinel}))
    monkeypatch.setattr(whatsapp_snapshots, "queue_broadcast_message", queue)
    result = (await server.call_tool("prepare_whatsapp_message", arguments)).structured_content
    assert result["error"] == "whatsapp_service_unavailable"
    assert "requires_input" not in result and result["audit_id"]
    audits = list((await fixture.session.scalars(select(AuditLogModel))).all())
    assert len(audits) == 1 and audits[0].result == "blocked"
    assert sentinel not in json.dumps(result)
    assert sentinel not in json.dumps([audit.metadata_json for audit in audits])
    assert sentinel not in caplog.text
    queue.assert_awaited_once()
    await assert_no_business_effects(fixture)
