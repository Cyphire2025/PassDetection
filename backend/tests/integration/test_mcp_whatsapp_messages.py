"""Real template queue projection, owned media and original-grant dispatch gates."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.application.mcp.credentials import MCPAuthError, credential_hash
from app.application.mcp.operations import MCPOperationError, MCPOperationService
from app.application.mcp.whatsapp_media_access import MCPWhatsAppMediaAccess
from app.infrastructure.database.mcp_communication_models import MCPWhatsAppPlanModel
from app.infrastructure.database.mcp_whatsapp_media_models import (
    MCPWhatsAppHeaderAccessModel,
    MCPWhatsAppHeaderMediaModel,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastSupportContactModel,
    WhatsAppMessageLogModel,
    WhatsAppPhoneWelcomeModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.whatsapp import template_settings, worker_runtime
from app.infrastructure.whatsapp.mcp_dispatch import BLOCKED, authorize_mcp_batch_dispatch
from app.presentation.api.v1.routes import whatsapp_send
from app.presentation.mcp.invocation import MCPInputError
from app.presentation.mcp.whatsapp_message_tools import message_operations
from tests.integration.test_mcp_operations import operations_fixture as operations_fixture
from tests.integration.test_mcp_whatsapp_intents import intent_fixture as intent_fixture
from tests.unit.presentation.test_whatsapp_repeatable_reminders import broadcast as broadcast


@pytest.fixture
async def message_fixture(intent_fixture, monkeypatch):
    original, broadcast, settings, _service, provider = intent_fixture
    session, _, actor, grants, tokens = original
    for grant in grants:
        grant.capabilities = ["mcp:read", "mcp:communicate", "mcp:upload"]
    settings = settings.model_copy(
        update={
            "whatsapp_welcome_template_name": "welcome_v1",
            "whatsapp_passport_link_template_name": "passport_v1",
        }
    )
    monkeypatch.setattr(whatsapp_send, "get_settings", lambda: settings)
    monkeypatch.setattr(template_settings, "get_settings", lambda: settings)
    monkeypatch.setattr(worker_runtime, "get_settings", lambda: settings)
    recipient = WhatsAppBroadcastRecipientModel(
        id=uuid.uuid4(),
        broadcast_group_id=broadcast.group.id,
        agency_id=broadcast.group.agency_id,
        name="Explicit new recipient",
        phone_number="+919123456789",
        normalized_phone_number="+919123456789",
    )
    group = ClientGroupModel(
        id=uuid.uuid4(),
        agency_id=broadcast.group.agency_id,
        name="Explicit linked upload",
        token=uuid.uuid4().hex,
        status="active",
    )
    contact = WhatsAppBroadcastSupportContactModel(
        id=uuid.uuid4(),
        broadcast_group_id=broadcast.group.id,
        agency_id=broadcast.group.agency_id,
        name="Reviewed support",
        phone_number="+919123456788",
        normalized_phone_number="+919123456788",
    )
    session.add_all([recipient, group, contact])
    await session.flush()
    session.add(
        ClientGroupWhatsAppBroadcastLinkModel(
            client_group_id=group.id,
            broadcast_group_id=broadcast.group.id,
            agency_id=group.agency_id,
        )
    )
    now = datetime.now(UTC)
    media = MCPWhatsAppHeaderMediaModel(
        id=uuid.uuid4(),
        user_id=actor.id,
        original_grant_id=grants[0].id,
        agency_id=group.agency_id,
        broadcast_id=broadcast.group.id,
        idempotency_hash="a" * 64,
        request_hash="b" * 64,
        handle_hash="c" * 64,
        original_storage_key=f"original-{uuid.uuid4()}",
        normalized_storage_key=f"normalized-{uuid.uuid4()}",
        original_sha256="d" * 64,
        normalized_sha256="e" * 64,
        original_byte_size=12,
        normalized_byte_size=15,
        filename="scanned.png",
        original_media_type="image/png",
        normalized_media_type="image/jpeg",
        provider_media_id="private-provider-image",
        provider_phone_number_id=settings.whatsapp_phone_number_id,
        status="ready",
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(hours=1),
        revision=3,
    )
    handle = MCPWhatsAppMediaAccess(session, settings).handle(media, grants[0].id)
    media.handle_hash = credential_hash(handle, settings.app_secret_key)
    session.add(media)
    await session.flush()
    session.add(
        MCPWhatsAppHeaderAccessModel(
            media_id=media.id, grant_id=grants[0].id, handle_hash=media.handle_hash
        )
    )
    await session.commit()
    return SimpleNamespace(
        session=session,
        actor=actor,
        grants=grants,
        tokens=tokens,
        settings=settings,
        broadcast=broadcast.group,
        recipient=recipient,
        group=group,
        contact=contact,
        media=media,
        handle=handle,
        provider=provider,
        service=MCPOperationService(session, settings, message_operations(settings)),
    )


async def prepare(f, kind="group_invite", **overrides):
    if kind != "welcome":
        f.session.add(
            WhatsAppRecipientMessageStateModel(
                broadcast_group_id=f.broadcast.id,
                agency_id=f.broadcast.agency_id,
                recipient_id=f.recipient.id,
                message_type="welcome",
                status="delivered",
                batch_id=uuid.uuid4(),
                submitted_at=datetime.now(UTC),
                provider_status_at=datetime.now(UTC),
            )
        )
        f.session.add(
            WhatsAppPhoneWelcomeModel(
                agency_id=f.broadcast.agency_id,
                normalized_phone_number=f.recipient.normalized_phone_number,
                status="delivered",
                attempt_id=uuid.uuid4(),
                attempt_kind="broadcast",
            )
        )
        await f.session.flush()
    payload = {
        "broadcast_id": str(f.broadcast.id),
        "message_type": kind,
        "message_content": "Exact reviewed message",
        "media_handle": f.handle,
        "recipient_ids": [str(f.recipient.id)],
    }
    if kind == "passport_link":
        payload.update(
            passport_intro="Upload your passport securely",
            client_group_id=str(f.group.id),
            support_contact_ids=[str(f.contact.id)],
        )
    if kind == "group_invite":
        payload["group_invite_link"] = "https://chat.whatsapp.com/AbCdEfGhIjKlMnOpQrStUv"
    payload.update(overrides)
    return await f.service.execute(
        access_token=f.tokens[0],
        operation_name="prepare_whatsapp_message",
        idempotency_key="prepare-template-intent-001",
        payload=payload,
    )


async def confirm(f, preview, connection=0):
    return await f.service.execute(
        access_token=f.tokens[connection],
        operation_name="confirm_whatsapp_message",
        idempotency_key="confirm-template-intent-001",
        payload={"plan_id": preview["data"]["plan_id"], "plan_hash": preview["data"]["plan_hash"]},
    )


@pytest.mark.parametrize("kind", ["welcome", "passport_link", "group_invite"])
async def test_supported_templates_exact_preview_queue_replay_and_dispatch(message_fixture, kind):
    f = message_fixture
    preview = await prepare(f, kind)
    assert "private-provider-image" not in json.dumps(preview)
    assert len(preview["data"]["preview"]["recipients"]) == 1
    assert await f.session.scalar(select(func.count()).select_from(WhatsAppMessageLogModel)) == 0
    result = await confirm(f, preview, connection=1)
    await f.session.commit()
    assert await confirm(f, preview) == result
    log = await f.session.scalar(select(WhatsAppMessageLogModel))
    assert log.message_type == kind and log.header_parameter_values == ["private-provider-image"]
    assert await authorize_mcp_batch_dispatch(f.session, log=log, settings=f.settings) is None
    if kind == "passport_link":
        assert f.settings.mcp.frontend_origin + "/upload/" + f.group.token in log.rendered_message
        assert "Reviewed support" in log.rendered_message
    f.provider.assert_not_awaited()
    plan = await f.session.get(MCPWhatsAppPlanModel, uuid.UUID(preview["data"]["plan_id"]))
    await f.session.commit()
    await worker_runtime.run_whatsapp_broadcast(
        **{**plan.snapshot["worker_payload"], "batch_id": result["data"]["batch_id"]}
    )
    await f.session.refresh(log)
    assert log.status == "submitted"
    assert f.provider.await_count == 1
    assert f.provider.await_args.kwargs["header_parameters"] == ["private-provider-image"]


@pytest.mark.parametrize("drift", ["recipient", "image", "support", "upload_token"])
async def test_exact_plan_content_drift_aborts_without_queueing(message_fixture, drift):
    f = message_fixture
    preview = await prepare(f, "passport_link")
    if drift == "recipient":
        f.recipient.name = "Changed recipient"
    if drift == "image":
        f.media.normalized_sha256 = "f" * 64
    if drift == "support":
        f.contact.name = "Changed support"
    if drift == "upload_token":
        f.group.token = uuid.uuid4().hex
    await f.session.flush()
    with pytest.raises(MCPOperationError, match="whatsapp_plan_changed"):
        await confirm(f, preview)
    assert await f.session.scalar(select(func.count()).select_from(WhatsAppMessageLogModel)) == 0
    plan = await f.session.get(MCPWhatsAppPlanModel, uuid.UUID(preview["data"]["plan_id"]))
    assert plan.status == "prepared"


@pytest.mark.parametrize(
    "change",
    ["revoked", "narrowed", "expired_media", "missing_access", "token_rotated", "opt_in_removed"],
)
async def test_dispatch_rechecks_original_authority_owned_header_and_link(message_fixture, change):
    f = message_fixture
    preview = await prepare(f, "passport_link")
    await confirm(f, preview, connection=1)
    if change == "revoked":
        f.grants[0].revoked_at = datetime.now(UTC)
    if change == "narrowed":
        f.grants[0].capabilities = ["mcp:read", "mcp:communicate"]
    if change == "expired_media":
        f.media.created_at = datetime.now(UTC) - timedelta(hours=2)
        f.media.expires_at = datetime.now(UTC) - timedelta(hours=1)
    if change == "missing_access":
        await f.session.delete(
            await f.session.get(MCPWhatsAppHeaderAccessModel, (f.media.id, f.grants[0].id))
        )
    if change == "token_rotated":
        f.group.token = uuid.uuid4().hex
    if change == "opt_in_removed":
        f.broadcast.recipient_opt_in_confirmed_at = None
    await f.session.flush()
    log = await f.session.scalar(select(WhatsAppMessageLogModel))
    assert await authorize_mcp_batch_dispatch(f.session, log=log, settings=f.settings) == BLOCKED
    f.provider.assert_not_awaited()


@pytest.mark.parametrize(
    "invalid",
    [
        {"header_image_id": "arbitrary"},
        {"message_type": "custom"},
        {"passport_link": "https://example.test/override"},
        {"group_invite_link": "https://example.test/invite"},
    ],
)
async def test_no_arbitrary_templates_header_ids_or_link_overrides(message_fixture, invalid):
    with pytest.raises((MCPInputError, MCPOperationError)):
        await prepare(message_fixture, **invalid)
    assert (
        await message_fixture.session.scalar(
            select(func.count()).select_from(WhatsAppMessageLogModel)
        )
        == 0
    )


async def test_same_actor_replay_still_requires_current_media_capability(message_fixture):
    f = message_fixture
    preview = await prepare(f)
    await confirm(f, preview)
    await f.session.commit()
    f.grants[1].capabilities = ["mcp:read", "mcp:communicate"]
    await f.session.flush()
    with pytest.raises(MCPAuthError):
        await confirm(f, preview, connection=1)
