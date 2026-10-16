"""Resumable text-only document updates; never sends or retries a PDF."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict
from datetime import UTC, datetime

import httpx
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.document_updates import ACCEPTED, needs_document_update
from app.core.config.settings import get_settings
from app.domain.value_objects.travel_document_taxonomy import MOBILE_PERSONAL_DOCUMENT_TYPES
from app.infrastructure.database.models import (
    DistributedDocumentModel,
    DocumentWhatsAppDeliveryModel,
    WhatsAppMessageLogModel,
)
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.whatsapp.cloud_api_provider import (
    WhatsAppCloudApiError,
    send_whatsapp_document_update_template,
)
from app.infrastructure.whatsapp.document_delivery_runtime import (
    DOCUMENT_DELIVERY_SLICE_SECONDS,
    DOCUMENT_DELIVERY_SLICE_SIZE,
    DOCUMENT_DELIVERY_STALE_AFTER,
    PROVIDER_ATTEMPT_DEADLINE_SECONDS,
)
from app.infrastructure.whatsapp.receipt_bindings import bind_source_provider_message
from app.infrastructure.whatsapp.traveller_destinations import load_traveller_destinations


async def _source_decision(
    session: AsyncSession, log: WhatsAppMessageLogModel
) -> tuple[str, str | None]:
    """Lock authoritative sources before the message row/provider window."""
    context = log.document_update_context
    if isinstance(context, dict) and "audience_version" in context:
        from app.infrastructure.whatsapp.group_update_dispatch import group_update_source_decision
        return await group_update_source_decision(session, log)
    try:
        if (
            not isinstance(context, dict)
            or context.get("document_type") not in MOBILE_PERSONAL_DOCUMENT_TYPES
        ):
            raise ValueError("invalid document context")
        group_id = uuid.UUID(context["group_id"])
        raw_ids = context["passenger_ids"]
        if not isinstance(raw_ids, list) or not 1 <= len(raw_ids) <= 1500:
            raise ValueError("invalid passenger context")
        passenger_ids = {uuid.UUID(value) for value in raw_ids}
    except (KeyError, TypeError, ValueError, AttributeError):
        return "failed", "UPDATE_CONTEXT_INVALID: Review the update audience before sending."
    destinations = await load_traveller_destinations(
        session,
        agency_id=log.agency_id,
        group_id=group_id,
        lock=True,
    )
    selected = [row for row in destinations if row.passenger_id in passenger_ids]
    if (
        len(selected) != len(passenger_ids)
        or any(row.reason for row in selected)
        or any(row.phone_number != log.normalized_phone_number for row in selected)
        or not any(
            row.recipient_id == log.recipient_id
            and row.broadcast_group_id == log.broadcast_group_id
            for row in selected
        )
    ):
        return (
            "failed",
            "UPDATE_AUDIENCE_CHANGED: Traveller contact, consent or linked broadcast changed.",
        )
    documents = list(
        (
            await session.scalars(
                select(DistributedDocumentModel)
                .where(
                    DistributedDocumentModel.agency_id == log.agency_id,
                    DistributedDocumentModel.group_id == group_id,
                    DistributedDocumentModel.passenger_id.in_(passenger_ids),
                    DistributedDocumentModel.document_type == context["document_type"],
                    DistributedDocumentModel.match_status.not_in(
                        ("duplicate_document", "superseded")
                    ),
                )
                .with_for_update()
            )
        ).all()
    )
    document_ids = {row.id for row in documents}
    confirmed = (
        {
            value
            for value in (
                await session.scalars(
                    select(DocumentWhatsAppDeliveryModel.distributed_document_id).where(
                        DocumentWhatsAppDeliveryModel.agency_id == log.agency_id,
                        DocumentWhatsAppDeliveryModel.group_id == group_id,
                        DocumentWhatsAppDeliveryModel.document_type == context["document_type"],
                        DocumentWhatsAppDeliveryModel.distributed_document_id.in_(document_ids),
                        DocumentWhatsAppDeliveryModel.status.in_(ACCEPTED),
                    )
                )
            ).all()
            if value is not None
        }
        if document_ids
        else set()
    )
    by_passenger: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for document in documents:
        if document.passenger_id is not None:
            by_passenger[document.passenger_id].add(document.id)
    if not any(
        needs_document_update(by_passenger[identifier], confirmed) for identifier in passenger_ids
    ):
        return (
            "skipped",
            "UPDATE_NO_LONGER_NEEDED: All selected travellers now have confirmed document sends.",
        )
    return "processing", None


async def _save_provider_result(
    session: AsyncSession, log: WhatsAppMessageLogModel, account: str | None
) -> None:
    """Recover a known provider acceptance by saving it, never sending again."""
    identifier, batch_id, provider_id = log.id, log.batch_id, log.provider_message_id
    try:
        await bind_source_provider_message(session, log, provider_phone_number_id=account)
        await session.commit()
    except Exception:
        await session.rollback()
        if not provider_id:
            raise
        saved = await session.scalar(
            select(WhatsAppMessageLogModel)
            .where(
                WhatsAppMessageLogModel.id == identifier,
                WhatsAppMessageLogModel.batch_id == batch_id,
            )
            .with_for_update()
        )
        if saved is None or saved.provider_message_id not in {None, provider_id}:
            raise RuntimeError("Document update provider result conflicts with the saved attempt")
        if saved.provider_message_id is None:
            saved.status, saved.error_message = "submitted", None
            saved.status_updated_at = datetime.now(UTC)
        saved.provider_message_id = provider_id
        await bind_source_provider_message(session, saved, provider_phone_number_id=account)
        await session.commit()


async def run_document_update_broadcast(*, batch_id: str) -> int:
    """Return the continuation delay (zero when complete) for one 25-row slice."""
    identifier = uuid.UUID(batch_id)
    settings = get_settings()
    deadline = time.monotonic() + DOCUMENT_DELIVERY_SLICE_SECONDS
    async with AsyncSessionFactory() as session:
        identifiers = list(
            (
                await session.scalars(
                    select(WhatsAppMessageLogModel.id)
                    .where(
                        WhatsAppMessageLogModel.batch_id == identifier,
                        WhatsAppMessageLogModel.message_type == "document_update",
                        WhatsAppMessageLogModel.status.in_(("queued", "processing")),
                    )
                    .order_by(
                        (WhatsAppMessageLogModel.status == "queued").desc(),
                        WhatsAppMessageLogModel.created_at,
                        WhatsAppMessageLogModel.id,
                    )
                    .limit(DOCUMENT_DELIVERY_SLICE_SIZE)
                )
            ).all()
        )
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
        for log_id in identifiers:
            if time.monotonic() >= deadline:
                break
            async with AsyncSessionFactory() as session:
                now = datetime.now(UTC)
                claimed = await session.scalar(
                    update(WhatsAppMessageLogModel)
                    .where(
                        WhatsAppMessageLogModel.id == log_id,
                        WhatsAppMessageLogModel.batch_id == identifier,
                        WhatsAppMessageLogModel.message_type == "document_update",
                        WhatsAppMessageLogModel.status == "queued",
                    )
                    .values(status="processing", status_updated_at=now)
                    .returning(WhatsAppMessageLogModel.id)
                )
                if claimed is None:
                    await session.execute(
                        update(WhatsAppMessageLogModel)
                        .where(
                            WhatsAppMessageLogModel.id == log_id,
                            WhatsAppMessageLogModel.batch_id == identifier,
                            WhatsAppMessageLogModel.status == "processing",
                            WhatsAppMessageLogModel.status_updated_at
                            < now - DOCUMENT_DELIVERY_STALE_AFTER,
                        )
                        .values(
                            status="delivery_unknown",
                            status_updated_at=now,
                            error_message="Interrupted update request; automatic resend is suppressed.",
                        )
                    )
                    await session.commit()
                    continue
                await session.commit()
                if session.get_bind().dialect.name == "postgresql":
                    # Keep source locks through the bounded provider window;
                    # the database's default idle transaction cap is shorter.
                    await session.execute(
                        text("SET LOCAL idle_in_transaction_session_timeout = '60s'")
                    )
                snapshot = await session.get(WhatsAppMessageLogModel, log_id)
                if snapshot is None:
                    continue
                frozen = (
                    snapshot.document_update_context,
                    snapshot.normalized_phone_number,
                    snapshot.recipient_id,
                    snapshot.broadcast_group_id,
                    snapshot.template_name,
                    snapshot.template_language,
                    snapshot.template_parameter_values,
                )
                decision, reason = await _source_decision(session, snapshot)
                log = await session.scalar(
                    select(WhatsAppMessageLogModel)
                    .where(
                        WhatsAppMessageLogModel.id == log_id,
                        WhatsAppMessageLogModel.batch_id == identifier,
                        WhatsAppMessageLogModel.status == "processing",
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if log is None:
                    continue
                if frozen != (
                    log.document_update_context,
                    log.normalized_phone_number,
                    log.recipient_id,
                    log.broadcast_group_id,
                    log.template_name,
                    log.template_language,
                    log.template_parameter_values,
                ):
                    decision, reason = (
                        "failed",
                        "UPDATE_SNAPSHOT_CHANGED: Review the update before sending.",
                    )
                if decision != "processing":
                    log.status, log.error_message, log.status_updated_at = (
                        decision,
                        reason,
                        datetime.now(UTC),
                    )
                    await session.commit()
                    continue
                parameters = log.template_parameter_values
                if (
                    not log.template_name
                    or not log.template_language
                    or not log.normalized_phone_number
                    or log.header_parameter_values != []
                    or not isinstance(parameters, list)
                    or len(parameters) != 1
                    or not isinstance(parameters[0], str)
                    or not parameters[0].strip()
                ):
                    log.status, log.error_message = (
                        "failed",
                        "UPDATE_TEMPLATE_INVALID: Saved text template is incomplete.",
                    )
                elif time.monotonic() >= deadline:
                    log.status = "queued"
                else:
                    try:
                        async with asyncio.timeout(PROVIDER_ATTEMPT_DEADLINE_SECONDS):
                            log.provider_message_id = await send_whatsapp_document_update_template(
                                client=client,
                                settings=settings,
                                to_number=log.normalized_phone_number,
                                template_name=log.template_name,
                                language_code=log.template_language,
                                message_content=parameters[0],
                            )
                        log.status, log.error_message = "submitted", None
                    except WhatsAppCloudApiError as exc:
                        log.status = "delivery_unknown" if exc.delivery_unknown else "failed"
                        log.error_message = exc.persistence_message[:2000]
                    except Exception:
                        log.status, log.error_message = (
                            "delivery_unknown",
                            "Update outcome is unknown; automatic resend is suppressed.",
                        )
                log.status_updated_at = datetime.now(UTC)
                await _save_provider_result(session, log, settings.whatsapp_phone_number_id)
    async with AsyncSessionFactory() as session:
        for status, delay in (("queued", 1), ("processing", 30)):
            if await session.scalar(
                select(
                    select(WhatsAppMessageLogModel.id)
                    .where(
                        WhatsAppMessageLogModel.batch_id == identifier,
                        WhatsAppMessageLogModel.message_type == "document_update",
                        WhatsAppMessageLogModel.status == status,
                    )
                    .exists()
                )
            ):
                return delay
    return 0
