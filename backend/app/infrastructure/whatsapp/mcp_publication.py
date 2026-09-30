"""Bounded durable broker publication; never directly retries provider requests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.credentials import MCPAuthError
from app.core.config.settings import get_settings
from app.infrastructure.database.mcp_communication_models import (
    MCPWhatsAppOutboxModel,
    MCPWhatsAppPlanModel,
)
from app.infrastructure.database.models import WhatsAppMessageLogModel
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.whatsapp.mcp_progress import refresh_mcp_dispatch_progress
from app.infrastructure.whatsapp.publication import (
    fail_unclaimed_broadcast_rows,
    publish_whatsapp_task,
)

MAX_PUBLICATIONS = 12
PUBLICATION_RESERVATION = timedelta(minutes=5)


async def _block_orphaned_publication(session: AsyncSession, outbox_id: uuid.UUID) -> None:
    outbox = await session.scalar(
        select(MCPWhatsAppOutboxModel)
        .where(MCPWhatsAppOutboxModel.id == outbox_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if outbox is not None and outbox.status in {"pending", "published"}:
        outbox.status, outbox.last_error_code = "blocked", "origin_plan_missing"
        outbox.updated_at = datetime.now(UTC)
        await fail_unclaimed_broadcast_rows(
            session,
            batch_id=outbox.batch_id,
            error_message="MCP_DISPATCH_BLOCKED: retained origin plan is unavailable",
        )
        await refresh_mcp_dispatch_progress(session, batch_id=outbox.batch_id)
        await session.commit()


async def _reserve_publication(outbox_id: uuid.UUID) -> dict[str, Any] | None:
    settings = get_settings()
    if settings.mcp.read_only_mode:
        # Preserve queued MCP plans without publication or workflow-progress writes.
        return None
    async with AsyncSessionFactory() as session:
        # Resolve without locking, then use the same authority -> plan -> outbox
        # order as the worker and cancellation path. Missing authority blocks.
        initial = await session.get(MCPWhatsAppOutboxModel, outbox_id)
        if initial is None:
            return None
        if initial.plan_id is None:
            await _block_orphaned_publication(session, outbox_id)
            return None
        plan = await session.get(MCPWhatsAppPlanModel, initial.plan_id)
        if plan is None:
            await _block_orphaned_publication(session, outbox_id)
            return None
        authorized = False
        if plan.original_grant_id is not None and plan.user_id is not None:
            try:
                authority = MCPAuthorizationService(session, settings)
                grant = await authority.require_grant(
                    plan.original_grant_id, lock=True
                )
                authority.require_capability(grant, "mcp:communicate")
                authorized = (
                    grant.user_id == plan.user_id and "mcp:communicate" in grant.capabilities
                )
            except MCPAuthError:
                pass
        plan = await session.scalar(
            select(MCPWhatsAppPlanModel)
            .where(MCPWhatsAppPlanModel.id == plan.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        outbox = await session.scalar(
            select(MCPWhatsAppOutboxModel)
            .where(MCPWhatsAppOutboxModel.id == outbox_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        now = datetime.now(UTC)
        if (
            plan is None
            or outbox is None
            or outbox.status not in {"pending", "published"}
            or plan.status != "queued"
        ):
            return None
        due = outbox.next_attempt_at
        if due.tzinfo is None:
            due = due.replace(tzinfo=UTC)
        if due > now:
            return None
        if not authorized or outbox.publication_attempts >= MAX_PUBLICATIONS:
            outbox.status, outbox.last_error_code = (
                "blocked",
                "authority_unavailable" if not authorized else "publication_attempt_limit",
            )
            plan.status, plan.revision = "blocked", plan.revision + 1
            await fail_unclaimed_broadcast_rows(
                session,
                batch_id=outbox.batch_id,
                error_message="MCP_DISPATCH_BLOCKED: dispatch authority or publication attempts unavailable",
            )
            await refresh_mcp_dispatch_progress(session, batch_id=outbox.batch_id)
            await session.commit()
            return None
        states = {
            state: int(count)
            for state, count in (
                await session.execute(
                    select(WhatsAppMessageLogModel.status, func.count())
                    .where(WhatsAppMessageLogModel.batch_id == outbox.batch_id)
                    .group_by(WhatsAppMessageLogModel.status)
                )
            ).all()
        }
        if not states.get("queued", 0) and not states.get("processing", 0):
            outbox.status, plan.status = "completed", "completed"
            plan.revision += 1
            outbox.next_attempt_at, outbox.updated_at = now + PUBLICATION_RESERVATION, now
            await refresh_mcp_dispatch_progress(session, batch_id=outbox.batch_id)
            await session.commit()
            return None
        outbox.publication_attempts += 1
        outbox.next_attempt_at, outbox.updated_at = now + PUBLICATION_RESERVATION, now
        payload = {**plan.snapshot["worker_payload"], "batch_id": str(outbox.batch_id)}
        await refresh_mcp_dispatch_progress(session, batch_id=outbox.batch_id)
        await session.commit()
        return payload


async def run_mcp_whatsapp_publication(*, limit: int = 20) -> int:
    if not 1 <= limit <= 100:
        raise ValueError("Publication limit must be 1 to 100")
    async with AsyncSessionFactory() as session:
        ids = list(
            (
                await session.scalars(
                    select(MCPWhatsAppOutboxModel.id)
                    .where(
                        MCPWhatsAppOutboxModel.status.in_(["pending", "published"]),
                        MCPWhatsAppOutboxModel.next_attempt_at <= datetime.now(UTC),
                    )
                    .order_by(MCPWhatsAppOutboxModel.next_attempt_at, MCPWhatsAppOutboxModel.id)
                    .limit(limit)
                )
            ).all()
        )
    published = 0
    from app.infrastructure.whatsapp.tasks import process_whatsapp_broadcast

    for outbox_id in ids:
        payload = await _reserve_publication(outbox_id)
        if payload is None:
            continue
        failure = False
        try:
            await publish_whatsapp_task(process_whatsapp_broadcast, payload=payload)
        except Exception:
            # Broker acknowledgement can be lost after acceptance. Keep the
            # same log batch, reserve before retry, and never reset sent/unknown.
            failure = True
        async with AsyncSessionFactory() as session:
            outbox = await session.scalar(
                select(MCPWhatsAppOutboxModel)
                .where(MCPWhatsAppOutboxModel.id == outbox_id)
                .with_for_update()
            )
            if outbox is not None and outbox.status in {"pending", "published"}:
                outbox.status = "pending" if failure else "published"
                outbox.last_error_code = "broker_unavailable_or_uncertain" if failure else None
                outbox.updated_at = datetime.now(UTC)
                await session.commit()
        if not failure:
            published += 1
    return published
