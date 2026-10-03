"""Original MCP authority precedes every document provider upload/submission."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPAuthorizationService, MCPPrincipal
from app.application.mcp.credentials import MCPAuthError, utc
from app.application.mcp.document_delivery import authorized_document_plan
from app.application.mcp.document_delivery_capacity import document_delivery_within_capacity
from app.application.mcp.document_delivery_sources import document_source
from app.application.mcp.operations import MCPDatabaseContext
from app.application.mcp.whatsapp_intents import snapshot_hash
from app.core.config.settings import Settings
from app.infrastructure.database.mcp_document_delivery_models import (
    MCPDocumentDeliveryOutboxModel,
    MCPDocumentDeliveryPlanModel,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    DocumentWhatsAppDeliveryModel,
    PlatformSettingModel,
)
from app.infrastructure.whatsapp.cloud_api_provider import WhatsAppCloudApiError
from app.infrastructure.whatsapp.template_settings import TEMPLATE_SETTINGS_KEY, snapshot_from_row

BLOCKED = "MCP_DOCUMENT_DISPATCH_BLOCKED: original authority or the approved document preview changed"


async def authorize_mcp_document_dispatch(
    session: AsyncSession, *, delivery: DocumentWhatsAppDeliveryModel, settings: Settings,
) -> tuple[str | None, MCPDocumentDeliveryPlanModel | None]:
    """Web batches pass through. Orphaned MCP markers fail closed.

    Control -> original grant -> identity -> plan comes BEFORE final existing
    group/recipient/source locks. Hold this transaction through provider I/O.
    """
    binding = (await session.execute(select(MCPDocumentDeliveryOutboxModel.plan_id).where(
        MCPDocumentDeliveryOutboxModel.send_batch_id == delivery.send_batch_id,
    ))).first()
    if binding is None:
        return None, None
    if binding.plan_id is None:
        return BLOCKED, None
    identity = await session.scalar(select(MCPDocumentDeliveryPlanModel).where(
        MCPDocumentDeliveryPlanModel.id == binding.plan_id,
    ))
    if identity is None:
        return BLOCKED, None
    try:
        grant = await MCPAuthorizationService(session, settings).require_grant(identity.original_grant_id, lock=True)
        principal = MCPPrincipal(grant.id, grant.user_id, grant.client_id, tuple(grant.capabilities),
                                 grant.expires_at, grant.resource)
        plan = await authorized_document_plan(MCPDatabaseContext(session, principal, identity.operation_id),
                                               identity.id, settings)
    except MCPAuthError:
        return BLOCKED, None
    snapshot = plan.snapshot
    current_group = await session.scalar(select(ClientGroupModel.id).where(
        ClientGroupModel.id == plan.group_id, ClientGroupModel.agency_id == plan.agency_id,
        ClientGroupModel.deleted_at.is_(None),
    ).with_for_update())
    if current_group is None:
        return BLOCKED, plan
    if not await document_delivery_within_capacity(session, agency_id=plan.agency_id,
            group_id=plan.group_id, document_type=snapshot["document_type"]):
        return BLOCKED, plan
    template_row = await session.scalar(select(PlatformSettingModel).where(
        PlatformSettingModel.key == TEMPLATE_SETTINGS_KEY,
    ).with_for_update(read=True).execution_options(populate_existing=True))
    current_template = snapshot_from_row(template_row).name("document", settings=settings)
    if (plan.status != "queued" or plan.send_batch_id != delivery.send_batch_id
            or plan.user_id != delivery.created_by_user_id or plan.agency_id != delivery.agency_id
            or plan.group_id != delivery.group_id or snapshot_hash(snapshot) != plan.snapshot_hash
            or snapshot.get("language") != settings.whatsapp_template_language
            or snapshot.get("template_name") != current_template):
        return BLOCKED, plan
    item = next((item for item in snapshot["recipients"]
                 if item["document_id"] == str(delivery.distributed_document_id)), None)
    if item is None or any((
        item["passenger_id"] != str(delivery.passenger_id),
        item["passenger_name"] != delivery.passenger_name,
        item["passport_number"] != delivery.passport_number,
        item["filename"] != delivery.document_filename,
        item["document_type"] != delivery.document_type,
        item["recipient_id"] != (str(delivery.recipient_id) if delivery.recipient_id else None),
        item["broadcast_id"] != str(delivery.broadcast_group_id),
        item["phone_number"] != delivery.normalized_phone_number,
        snapshot["template_name"] != delivery.template_name,
        snapshot["body_parameters"] != delivery.template_parameter_values,
    )):
        return BLOCKED, plan
    return None, plan


def approved_document_source(
    plan: MCPDocumentDeliveryPlanModel | None, document: DistributedDocumentModel,
    batch: DocumentDistributionBatchModel,
) -> bool:
    if plan is None:
        return True
    source = next((item for item in plan.snapshot["sources"] if item["id"] == str(document.id)), None)
    source_batch = next((item for item in plan.snapshot["source_batches"] if item["id"] == str(batch.id)), None)
    return (source == document_source(document) and source_batch == {
        "id": str(batch.id), "revision": utc(batch.updated_at).isoformat(), "document_type": batch.document_type,
    } and batch.status == "saved")


async def upload_mcp_document_media(
    session: AsyncSession, *, delivery: DocumentWhatsAppDeliveryModel,
    document: DistributedDocumentModel, content: bytes, client: httpx.AsyncClient, settings: Settings,
    upload: Callable[..., Awaitable[str]],
) -> tuple[bool, str | None, str | None]:
    """One provider upload under original authority/source locks; web behavior stays separate."""
    error, plan = await authorize_mcp_document_dispatch(session, delivery=delivery, settings=settings)
    if error:
        return True, None, error
    if plan is None:
        return False, None, None
    row = (await session.execute(select(DistributedDocumentModel, DocumentDistributionBatchModel)
        .join(DocumentDistributionBatchModel, DocumentDistributionBatchModel.id == DistributedDocumentModel.batch_id)
        .where(DistributedDocumentModel.id == delivery.distributed_document_id,
               DistributedDocumentModel.batch_id == delivery.document_batch_id,
               DistributedDocumentModel.agency_id == delivery.agency_id,
               DistributedDocumentModel.group_id == delivery.group_id)
        .with_for_update().execution_options(populate_existing=True))).one_or_none()
    if (row is None or not approved_document_source(plan, row[0], row[1])
            or row[0].storage_key != document.storage_key):
        return True, None, BLOCKED
    try:
        async with asyncio.timeout(35):
            media_id = await upload(client=client, settings=settings, file_name=delivery.document_filename,
                                    file_content=content, content_type=row[0].content_type)
    except WhatsAppCloudApiError as exc:
        return True, None, exc.persistence_message
    except Exception:  # noqa: BLE001 - no automatic provider retry for MCP.
        return True, None, "MCP_DOCUMENT_UPLOAD_FAILED: prepare and approve a fresh delivery before another attempt"
    return True, media_id, None
