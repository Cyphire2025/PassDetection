"""Durable publication of the same approved document batch, never provider retry."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPAuthorizationService, MCPPrincipal
from app.application.mcp.credentials import MCPAuthError, utc
from app.application.mcp.document_delivery import authorized_document_plan
from app.application.mcp.operations import MCPDatabaseContext
from app.core.config.settings import get_settings
from app.infrastructure.database.mcp_document_delivery_models import (
    MCPDocumentDeliveryOutboxModel,
    MCPDocumentDeliveryPlanModel,
)
from app.infrastructure.database.models import DocumentWhatsAppDeliveryModel
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.whatsapp.mcp_document_dispatch import BLOCKED
from app.infrastructure.whatsapp.mcp_document_progress import (
    document_dispatch_counts,
    refresh_document_dispatch_progress,
)
from app.infrastructure.whatsapp.publication import publish_whatsapp_task

RESERVATION = timedelta(minutes=5)
MAX_PUBLICATIONS = 12


async def _block(session: AsyncSession, outbox: MCPDocumentDeliveryOutboxModel,
                 plan: MCPDocumentDeliveryPlanModel | None, reason: str) -> None:
    now = datetime.now(UTC)
    outbox.status, outbox.last_error_code, outbox.updated_at = "blocked", reason, now
    if plan is not None:
        plan.status = "blocked"
    await session.execute(update(DocumentWhatsAppDeliveryModel).where(
        DocumentWhatsAppDeliveryModel.send_batch_id == outbox.send_batch_id,
        DocumentWhatsAppDeliveryModel.status == "queued",
    ).values(status="failed", error_message=BLOCKED, updated_at=now, status_updated_at=now))
    await refresh_document_dispatch_progress(session, outbox.send_batch_id)
    await session.commit()


async def reserve_document_publication(identifier: uuid.UUID) -> dict[str, object] | None:
    settings = get_settings()
    if settings.mcp.read_only_mode:
        return None
    async with AsyncSessionFactory() as session:
        initial = await session.get(MCPDocumentDeliveryOutboxModel, identifier)
        if initial is None:
            return None
        identity = await session.get(MCPDocumentDeliveryPlanModel, initial.plan_id) if initial.plan_id else None
        plan, authorized = None, False
        if identity is not None:
            try:
                grant = await MCPAuthorizationService(session, settings).require_grant(identity.original_grant_id, lock=True)
                principal = MCPPrincipal(grant.id, grant.user_id, grant.client_id,
                                         tuple(grant.capabilities), grant.expires_at, grant.resource)
                plan = await authorized_document_plan(MCPDatabaseContext(session, principal, identity.operation_id),
                                                       identity.id, settings)
                authorized = plan.status == "queued" and plan.send_batch_id == initial.send_batch_id
            except MCPAuthError:
                pass
        if identity is not None and plan is None:
            plan = await session.scalar(select(MCPDocumentDeliveryPlanModel).where(
                MCPDocumentDeliveryPlanModel.id == identity.id,
            ).with_for_update().execution_options(populate_existing=True))
        outbox = await session.scalar(select(MCPDocumentDeliveryOutboxModel).where(
            MCPDocumentDeliveryOutboxModel.id == identifier,
        ).with_for_update().execution_options(populate_existing=True))
        now = datetime.now(UTC)
        if outbox is None or outbox.status not in {"pending", "published"} or utc(outbox.next_attempt_at) > now:
            return None
        if not authorized:
            await _block(session, outbox, plan, "authority_unavailable")
            return None
        assert plan is not None
        counts = await document_dispatch_counts(session, outbox.send_batch_id)
        await refresh_document_dispatch_progress(session, outbox.send_batch_id)
        if not counts.get("queued", 0) and not counts.get("processing", 0):
            outbox.status, outbox.updated_at, plan.status = "completed", now, "completed"
            await session.commit()
            return None
        if outbox.publication_attempts >= MAX_PUBLICATIONS:
            await _block(session, outbox, plan, "publication_attempt_limit")
            return None
        outbox.publication_attempts += 1
        outbox.next_attempt_at, outbox.updated_at = now + RESERVATION, now
        payload: dict[str, object] = {"send_batch_id": str(outbox.send_batch_id)}
        await session.commit()
        return payload


async def run_mcp_document_publication(*, limit: int = 20) -> int:
    if not 1 <= limit <= 100:
        raise ValueError("Publication limit must be 1 to 100")
    async with AsyncSessionFactory() as session:
        ids = list((await session.scalars(select(MCPDocumentDeliveryOutboxModel.id).where(
            MCPDocumentDeliveryOutboxModel.status.in_(["pending", "published"]),
            MCPDocumentDeliveryOutboxModel.next_attempt_at <= datetime.now(UTC),
        ).order_by(MCPDocumentDeliveryOutboxModel.next_attempt_at, MCPDocumentDeliveryOutboxModel.id)
            .limit(limit))).all())
    from app.infrastructure.whatsapp.tasks import process_document_whatsapp_broadcast

    published = 0
    for identifier in ids:
        payload = await reserve_document_publication(identifier)
        if payload is None:
            continue
        failure = False
        try:
            await publish_whatsapp_task(process_document_whatsapp_broadcast, payload=payload)
        except Exception:  # Broker acceptance may be uncertain; preserve the exact batch.
            failure = True
        async with AsyncSessionFactory() as session:
            outbox = await session.scalar(select(MCPDocumentDeliveryOutboxModel).where(
                MCPDocumentDeliveryOutboxModel.id == identifier,
            ).with_for_update().execution_options(populate_existing=True))
            if outbox is not None and outbox.status in {"pending", "published"}:
                outbox.status = "pending" if failure else "published"
                outbox.last_error_code = "broker_unavailable_or_uncertain" if failure else None
                outbox.updated_at = datetime.now(UTC)
                await session.commit()
        published += not failure
    return published
