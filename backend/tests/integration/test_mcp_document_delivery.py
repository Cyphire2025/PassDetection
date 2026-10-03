"""Exact document previews, durable queue and real worker with synthetic providers."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken
from sqlalchemy import func, insert, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.document_delivery import document_delivery_operations
from app.application.mcp.document_delivery_dto import (
    MCPDocumentDeliveryConfirmation,
    MCPDocumentDeliveryDraft,
)
from app.application.mcp.operations import MCPOperationError, MCPOperationService
from app.infrastructure.database.mcp_document_delivery_models import (
    MCPDocumentDeliveryOutboxModel,
    MCPDocumentDeliveryPlanModel,
)
from app.infrastructure.database.mcp_models import MCPControlModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    AuditLogModel,
    DistributedDocumentModel,
    DocumentWhatsAppDeliveryModel,
)
from app.infrastructure.whatsapp import (
    document_delivery_runtime,
    mcp_document_publication,
    template_settings,
)
from app.infrastructure.whatsapp.cloud_api_provider import WhatsAppCloudApiError
from app.infrastructure.whatsapp.mcp_document_progress import refresh_document_dispatch_progress
from app.infrastructure.whatsapp.receipt_bindings import bind_source_provider_message
from app.infrastructure.whatsapp.receipt_inbox import VerifiedReceipt, persist_verified_receipts
from app.infrastructure.whatsapp.receipt_runtime import reconcile_pending_receipts
from app.presentation.api.v1.routes import document_distribution_delivery_preview
from app.presentation.mcp.document_delivery_snapshots import document_delivery_snapshot
from app.presentation.mcp.document_delivery_tools import register_document_delivery_tools
from tests.integration.test_mcp_operations import operations_fixture as operations_fixture
from tests.traveller_delivery_fixtures import (
    FATHER_PHONE,
    MOTHER_PHONE,
    QUALIFIER_PHONE,
    seed_traveller_delivery,
)


@pytest.fixture
async def document_delivery(operations_fixture, client, monkeypatch):
    session, original, user, grants, tokens = operations_fixture
    context = await seed_traveller_delivery(session, client)
    for grant in grants:
        grant.capabilities = ["mcp:read", "mcp:communicate"]
    settings = original.model_copy(update={
        "whatsapp_access_token": "synthetic-document-token",
        "whatsapp_phone_number_id": "synthetic-sender",
        "whatsapp_document_template_name": "document_template",
        "whatsapp_delivery_concurrency": 1,
    })
    monkeypatch.setattr(document_distribution_delivery_preview, "get_settings", lambda: settings)
    monkeypatch.setattr(document_delivery_runtime, "get_settings", lambda: settings)
    monkeypatch.setattr(mcp_document_publication, "get_settings", lambda: settings)
    monkeypatch.setattr(template_settings, "get_settings", lambda: settings)
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    monkeypatch.setattr(document_delivery_runtime, "AsyncSessionFactory", factory)
    monkeypatch.setattr(mcp_document_publication, "AsyncSessionFactory", factory)
    upload = AsyncMock(return_value="synthetic-media")
    provider = AsyncMock(side_effect=lambda **_kwargs: "wamid." + uuid.uuid4().hex)
    publication = AsyncMock()
    monkeypatch.setattr(document_delivery_runtime, "MinioStorageRepository", lambda: SimpleNamespace(
        get_file=AsyncMock(return_value=b"%PDF-1.7\nsynthetic fixture\n%%EOF")))
    monkeypatch.setattr(document_delivery_runtime, "upload_whatsapp_document", upload)
    monkeypatch.setattr(document_delivery_runtime, "send_whatsapp_document_template", provider)
    monkeypatch.setattr(document_delivery_runtime, "_propagate_first_released_document_batch", AsyncMock(return_value=0))
    monkeypatch.setattr(mcp_document_publication, "publish_whatsapp_task", publication)
    await session.commit()
    await session.execute(text("BEGIN"))
    return SimpleNamespace(session=session, settings=settings, user=user, grants=grants, tokens=tokens,
        context=context, service=MCPOperationService(session, settings,
            document_delivery_operations(settings, document_delivery_snapshot)),
        upload=upload, provider=provider, publication=publication, factory=factory)


def draft(f):
    return {"agency_id": str(f.context.agency.id), "group_id": str(f.context.group.id),
            "batch_id": str(f.context.batch.id), "document_ids": sorted(str(row.id) for row in f.context.documents),
            "message_content_1": "Your personally assigned travel document.",
            "message_content_2": "Please check your details before travelling."}


async def invoke(f, name, payload, *, key=None, connection=0):
    return await f.service.execute(access_token=f.tokens[connection], operation_name=name,
        idempotency_key=key or "fixture-" + name + "-0001", payload=payload)


async def prepare(f, payload=None):
    return await invoke(f, "prepare_whatsapp_document_delivery", payload or draft(f))


async def confirm(f, prepared, **kwargs):
    return await invoke(f, "confirm_whatsapp_document_delivery", {
        "plan_id": prepared["data"]["plan_id"], "plan_hash": prepared["data"]["plan_hash"],
        "user_confirmed": True,
    }, **kwargs)


async def count(f, model):
    return await f.session.scalar(select(func.count()).select_from(model))


async def test_preparation_projects_actual_travellers_attachments_without_queue_or_provider(document_delivery):
    f = document_delivery
    result = await prepare(f)
    preview = result["data"]["preview"]
    assert result["data"]["confirmation_required"] and result["data"]["status"] == "prepared"
    assert {item["phone_number"] for item in preview["recipients"]} == {MOTHER_PHONE, FATHER_PHONE}
    assert QUALIFIER_PHONE not in {item["phone_number"] for item in preview["recipients"]}
    assert len(preview["sources"]) == 2 and "file-byte checksum" in preview["source_binding"]
    assert all("storage_key" not in item and "sha256" not in item for item in preview["sources"])
    assert preview["body_parameters"] == [draft(f)["message_content_1"], draft(f)["message_content_2"]]
    assert "personally assigned" in preview["rendered_message"]
    assert await count(f, DocumentWhatsAppDeliveryModel) == 0
    assert await count(f, MCPDocumentDeliveryOutboxModel) == 0
    assert await f.session.scalar(select(func.count()).select_from(AuditLogModel).where(
        AuditLogModel.action == "document_whatsapp_broadcast_queued")) == 0
    f.upload.assert_not_awaited()
    f.provider.assert_not_awaited()
    f.publication.assert_not_awaited()


@pytest.mark.parametrize("value", [None, False, 0, 1])
async def test_final_confirmation_must_be_literal_true(document_delivery, value):
    f = document_delivery
    prepared = await prepare(f)
    payload = {"plan_id": prepared["data"]["plan_id"], "plan_hash": prepared["data"]["plan_hash"]}
    if value is not None:
        payload["user_confirmed"] = value
    with pytest.raises(MCPOperationError, match="invalid_document_delivery_confirmation"):
        await invoke(f, "confirm_whatsapp_document_delivery", payload)
    with pytest.raises(ValueError):
        MCPDocumentDeliveryConfirmation.model_validate(payload)
    assert await count(f, DocumentWhatsAppDeliveryModel) == 0


async def test_exact_replay_creates_one_durable_batch_and_retains_original_authority(document_delivery):
    f = document_delivery
    prepared = await prepare(f)
    first = await confirm(f, prepared, connection=1)
    await f.session.commit()
    await f.session.execute(text("BEGIN"))
    assert await confirm(f, prepared) == first
    plan = await f.session.scalar(select(MCPDocumentDeliveryPlanModel))
    assert plan.original_grant_id == f.grants[0].id
    assert await count(f, DocumentWhatsAppDeliveryModel) == 2
    assert await count(f, MCPDocumentDeliveryOutboxModel) == 1
    f.publication.assert_not_awaited()
    f.provider.assert_not_awaited()


@pytest.mark.parametrize("change", ["phone", "storage", "revision", "assignment", "filename", "template", "batch_tenant"])
async def test_changed_preview_rolls_back_confirmation_and_every_queue_effect(document_delivery, change):
    f = document_delivery
    prepared = await prepare(f)
    if change == "phone":
        f.context.passengers[0].client_phone = "+919900000077"
    elif change == "storage":
        f.context.documents[0].storage_key += ".changed"
    elif change == "revision":
        f.context.documents[0].updated_at = datetime.now(UTC) + timedelta(seconds=1)
    elif change == "assignment":
        f.context.documents[0].passenger_id = f.context.passengers[1].id
    elif change == "filename":
        f.context.documents[0].original_filename = "changed.pdf"
    elif change == "template":
        f.settings.whatsapp_document_template_name = "another_template"
    else:
        from app.infrastructure.database.models import AgencyModel
        other = AgencyModel(id=uuid.uuid4(), name="Other test agency", email="other@example.test")
        f.session.add(other)
        await f.session.flush()
        f.context.batch.agency_id = other.id
    await f.session.flush()
    with pytest.raises((MCPOperationError, MCPAuthError)):
        await confirm(f, prepared)
    assert await count(f, DocumentWhatsAppDeliveryModel) == 0
    assert await count(f, MCPDocumentDeliveryOutboxModel) == 0
    f.provider.assert_not_awaited()


@pytest.mark.parametrize("change", ["disabled", "revoked", "section", "global", "expiry"])
async def test_original_authority_and_plan_expiry_block_cross_connection_confirmation(document_delivery, change):
    f = document_delivery
    prepared = await prepare(f)
    if change == "disabled":
        f.grants[0].enabled = False
    elif change == "revoked":
        f.grants[0].revoked_at = datetime.now(UTC)
    elif change == "section":
        f.grants[0].allowed_write_sections = ["whatsapp_broadcasts"]
    elif change == "global":
        control = await f.session.get(MCPControlModel, 1)
        control.write_enabled = False
    else:
        plan = await f.session.scalar(select(MCPDocumentDeliveryPlanModel))
        plan.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        plan.prepared_at = plan.expires_at - timedelta(minutes=15)
    await f.session.flush()
    with pytest.raises((MCPAuthError, MCPOperationError)):
        await confirm(f, prepared, connection=1)
    assert await count(f, DocumentWhatsAppDeliveryModel) == 0


async def test_broker_failure_retries_exact_batch_not_provider_or_queued_rows(document_delivery):
    f = document_delivery
    prepared = await prepare(f)
    queued = await confirm(f, prepared)
    batch = uuid.UUID(queued["data"]["send_batch_id"])
    await f.session.commit()
    f.publication.side_effect = RuntimeError("synthetic unavailable broker")
    assert await mcp_document_publication.run_mcp_document_publication() == 0
    outbox = await f.session.scalar(select(MCPDocumentDeliveryOutboxModel).execution_options(populate_existing=True))
    assert outbox.status == "pending" and outbox.publication_attempts == 1
    assert await count(f, DocumentWhatsAppDeliveryModel) == 2
    outbox.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
    await f.session.commit()
    f.publication.side_effect = None
    assert await mcp_document_publication.run_mcp_document_publication() == 1
    assert all(call.kwargs["payload"] == {"send_batch_id": str(batch)} for call in f.publication.await_args_list)
    f.provider.assert_not_awaited()
    f.upload.assert_not_awaited()


async def test_real_worker_checks_preview_and_sends_each_exact_pdf_once(document_delivery):
    f = document_delivery
    prepared = await prepare(f)
    queued = await confirm(f, prepared)
    batch = queued["data"]["send_batch_id"]
    await f.session.commit()
    await document_delivery_runtime.run_document_whatsapp_broadcast(send_batch_id=batch)
    assert f.upload.await_count == 2 and f.provider.await_count == 2
    assert {call.kwargs["to_number"] for call in f.provider.await_args_list} == {MOTHER_PHONE, FATHER_PHONE}
    assert all(call.kwargs["parameters"] == prepared["data"]["preview"]["body_parameters"] for call in f.provider.await_args_list)
    await document_delivery_runtime.run_document_whatsapp_broadcast(send_batch_id=batch)
    assert f.provider.await_count == 2
    rows = (await f.session.scalars(select(DocumentWhatsAppDeliveryModel).execution_options(populate_existing=True))).all()
    assert all(row.status == "submitted" for row in rows)


@pytest.mark.parametrize("change", ["disabled", "section", "source", "template", "recipient"])
async def test_worker_blocks_current_authority_or_source_drift_without_sending(document_delivery, change):
    f = document_delivery
    prepared = await prepare(f)
    queued = await confirm(f, prepared)
    if change == "disabled":
        f.grants[0].enabled = False
    elif change == "section":
        f.grants[0].allowed_write_sections = []
    elif change == "source":
        for document in f.context.documents:
            document.storage_key += ".changed"
    elif change == "template":
        f.settings.whatsapp_document_template_name = "changed_template"
    else:
        for passenger in f.context.passengers:
            passenger.client_phone = "+919900000077"
    await f.session.commit()
    await document_delivery_runtime.run_document_whatsapp_broadcast(send_batch_id=queued["data"]["send_batch_id"])
    f.provider.assert_not_awaited()
    if change != "recipient":
        f.upload.assert_not_awaited()


async def test_mcp_provider_transient_is_not_automatically_retried(document_delivery):
    f = document_delivery
    queued = await confirm(f, await prepare(f))
    await f.session.commit()
    f.provider.side_effect = WhatsAppCloudApiError("Synthetic rejection", transient=True)
    await document_delivery_runtime.run_document_whatsapp_broadcast(send_batch_id=queued["data"]["send_batch_id"])
    assert f.provider.await_count == 2
    await document_delivery_runtime.run_document_whatsapp_broadcast(send_batch_id=queued["data"]["send_batch_id"])
    assert f.provider.await_count == 2


def test_draft_requires_explicit_unique_bounded_selection():
    identifiers = [uuid.uuid4() for _ in range(101)]
    payload = {"agency_id": uuid.uuid4(), "group_id": uuid.uuid4(), "batch_id": uuid.uuid4(),
               "document_ids": identifiers, "message_content_1": "One", "message_content_2": "Two"}
    for selection in ([], identifiers, [identifiers[0], identifiers[0]]):
        with pytest.raises(ValueError):
            MCPDocumentDeliveryDraft.model_validate({**payload, "document_ids": selection})


async def test_small_selection_cannot_hydrate_an_unbounded_document_ledger(document_delivery, monkeypatch):
    f = document_delivery
    selected = draft(f)
    await f.session.execute(insert(DistributedDocumentModel), [{
        "id": uuid.uuid4(), "batch_id": f.context.batch.id, "agency_id": f.context.agency.id,
        "group_id": f.context.group.id, "passenger_id": f.context.passengers[0].id,
        "document_type": "visa", "original_filename": "bounded-fixture.pdf",
        "storage_key": "synthetic/bounded-fixture.pdf", "match_status": "matched",
    } for _ in range(1500)])
    hydration = AsyncMock()
    monkeypatch.setattr("app.presentation.api.v1.routes.document_distribution_delivery._build_document_delivery_preview", hydration)
    with pytest.raises(MCPOperationError, match="document_delivery_preview_capacity_exceeded"):
        await prepare(f, selected)
    hydration.assert_not_awaited()
    assert await count(f, MCPDocumentDeliveryPlanModel) == 0
    assert await count(f, DocumentWhatsAppDeliveryModel) == 0


async def test_unknown_provider_outcomes_never_automatically_resend_or_reprepare(document_delivery):
    f = document_delivery
    queued = await confirm(f, await prepare(f))
    await f.session.commit()
    f.provider.side_effect = TimeoutError("Synthetic uncertain request")
    await document_delivery_runtime.run_document_whatsapp_broadcast(send_batch_id=queued["data"]["send_batch_id"])
    assert f.provider.await_count == 2
    operation = await f.session.get(MCPOperationModel, uuid.UUID(queued["operation_id"]))
    assert operation.status == "unknown" and operation.stage == "dispatch_unknown"
    await f.session.commit()
    await document_delivery_runtime.run_document_whatsapp_broadcast(send_batch_id=queued["data"]["send_batch_id"])
    assert f.provider.await_count == 2
    await f.session.execute(text("BEGIN"))
    with pytest.raises(MCPOperationError, match="document_delivery_unavailable"):
        await invoke(f, "prepare_whatsapp_document_delivery", draft(f), key="fresh-after-unknown-0001")
    assert await count(f, MCPDocumentDeliveryOutboxModel) == 1


async def test_orphaned_publication_marker_blocks_upload_and_send(document_delivery):
    f = document_delivery
    queued = await confirm(f, await prepare(f))
    outbox = await f.session.scalar(select(MCPDocumentDeliveryOutboxModel))
    outbox.plan_id = None
    await f.session.commit()
    assert await mcp_document_publication.run_mcp_document_publication() == 0
    await document_delivery_runtime.run_document_whatsapp_broadcast(send_batch_id=queued["data"]["send_batch_id"])
    f.upload.assert_not_awaited()
    f.provider.assert_not_awaited()
    await f.session.refresh(outbox)
    assert outbox.status == "blocked"


@pytest.mark.parametrize("received_status", ["sent", "delivered"])
async def test_later_verified_document_receipts_resolve_unknown_without_new_send(document_delivery, monkeypatch, received_status):
    f = document_delivery
    queued = await confirm(f, await prepare(f))
    rows = list((await f.session.scalars(select(DocumentWhatsAppDeliveryModel))).all())
    events = []
    for row in rows:
        row.status, row.provider_message_id = "delivery_unknown", "wamid.reconcile." + uuid.uuid4().hex
        await bind_source_provider_message(f.session, row, provider_phone_number_id="synthetic-sender")
        events.append(VerifiedReceipt("synthetic-sender", row.provider_message_id, received_status,
                                     datetime.now(UTC), None))
    await refresh_document_dispatch_progress(f.session, uuid.UUID(queued["data"]["send_batch_id"]))
    await f.session.commit()
    operation = await f.session.get(MCPOperationModel, uuid.UUID(queued["operation_id"]))
    assert operation.status == "unknown"
    ids = await persist_verified_receipts(f.session, events)
    await f.session.commit()
    monkeypatch.setattr("app.infrastructure.whatsapp.receipt_runtime.propagate_mobile_passenger_change", AsyncMock())
    await reconcile_pending_receipts(f.session, receipt_ids=ids)
    await f.session.refresh(operation)
    assert operation.status == "succeeded" and operation.stage == "dispatch_complete"
    assert operation.initial_result == queued
    assert list((await f.session.scalars(select(DocumentWhatsAppDeliveryModel.status))).all()) == [received_status] * 2
    f.provider.assert_not_awaited()
    f.upload.assert_not_awaited()


async def test_native_sdk_accepts_explicit_preview_and_confirm_model_without_provider(document_delivery, monkeypatch):
    f = document_delivery
    payload = draft(f)
    grant_id, client_id, user_id = f.grants[0].id, f.grants[0].client_id, f.user.id
    await f.session.commit()
    app, server = FastAPI(), MCPServer("Synthetic document sender")
    app.state.mcp_session_factory, app.state.mcp_operations = f.factory, {}
    register_document_delivery_tools(server, app, f.settings)
    monkeypatch.setattr("app.presentation.mcp.invocation.get_access_token", lambda: AccessToken(
        token=f.tokens[0], client_id=client_id, scopes=["mcp:read", "mcp:communicate"],
        subject=str(user_id), resource=f.settings.mcp.resource, claims={"grant_id": str(grant_id)},
    ))
    tools = {tool.name: tool for tool in await server.list_tools()}
    annotations = tools["confirm_whatsapp_document_delivery"].annotations.model_dump(by_alias=True)
    assert annotations["destructiveHint"] is True and annotations["openWorldHint"] is True
    prepared = (await server.call_tool("prepare_whatsapp_document_delivery", {
        "draft": payload, "idempotency_key": "sdk-document-preview-0001",
    })).structured_content
    assert "receipt" in prepared, prepared
    preview = prepared["receipt"]["data"]
    confirmed = (await server.call_tool("confirm_whatsapp_document_delivery", {
        "confirmation": {"plan_id": preview["plan_id"], "plan_hash": preview["plan_hash"], "user_confirmed": True},
        "idempotency_key": "sdk-document-confirm-0001",
    })).structured_content
    assert confirmed["receipt"]["status"] == "queued", confirmed
    f.provider.assert_not_awaited()
    f.upload.assert_not_awaited()
    f.publication.assert_not_awaited()
