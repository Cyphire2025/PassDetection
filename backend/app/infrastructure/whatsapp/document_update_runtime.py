"""Resumable text-only document updates; never sends or retries a PDF."""

from __future__ import annotations

import copy
import logging
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
    send_whatsapp_document_update_template,
)
from app.infrastructure.whatsapp.document_delivery_runtime import (
    DOCUMENT_DELIVERY_SLICE_SECONDS,
    DOCUMENT_DELIVERY_SLICE_SIZE,
    DOCUMENT_DELIVERY_STALE_AFTER,
)
from app.infrastructure.whatsapp.document_update_provider_wave import (
    UPDATE_SEND_CONCURRENCY,
    UpdateProviderOutcome,
    UpdateProviderRequest,
    send_update_wave,
)
from app.infrastructure.whatsapp.group_update_dispatch import (
    GroupUpdateDispatchCache,
    group_update_source_decision,
)
from app.infrastructure.whatsapp.receipt_bindings import bind_source_provider_message
from app.infrastructure.whatsapp.traveller_destinations import load_traveller_destinations

logger = logging.getLogger(__name__)


async def _source_decision(
    session: AsyncSession, log: WhatsAppMessageLogModel,
    *, cache: GroupUpdateDispatchCache | None = None,
) -> tuple[str, str | None]:
    """Lock authoritative sources before the message row/provider window."""
    context = log.document_update_context
    if isinstance(context, dict) and "audience_version" in context:
        return await group_update_source_decision(session, log, cache=cache)
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


def _frozen_snapshot(log: WhatsAppMessageLogModel) -> tuple[object, ...]:
    return copy.deepcopy((
        log.document_update_context, log.normalized_phone_number, log.recipient_id,
        log.broadcast_group_id, log.template_name, log.template_language,
        log.header_parameter_values, log.template_parameter_values,
    ))


def _prepare_request(
    log: WhatsAppMessageLogModel, decision: str, reason: str | None, deadline: float,
) -> UpdateProviderRequest | UpdateProviderOutcome:
    if decision != "processing":
        return UpdateProviderOutcome(log.id, decision, reason)
    parameters = log.template_parameter_values
    if (not log.template_name or not log.template_language or not log.normalized_phone_number
            or log.header_parameter_values != [] or not isinstance(parameters, list)
            or len(parameters) != 1 or not isinstance(parameters[0], str)
            or not parameters[0].strip()):
        return UpdateProviderOutcome(log.id, "failed", "UPDATE_TEMPLATE_INVALID: Saved text template is incomplete.")
    if time.monotonic() >= deadline:
        return UpdateProviderOutcome(log.id, "queued")
    return UpdateProviderRequest(
        log.id, log.normalized_phone_number, log.template_name, log.template_language, parameters[0],
    )


async def _claim_update_wave(
    session: AsyncSession, batch_id: uuid.UUID, identifiers: list[uuid.UUID],
) -> list[uuid.UUID]:
    now = datetime.now(UTC)
    claimed = list((await session.scalars(
        update(WhatsAppMessageLogModel).where(
            WhatsAppMessageLogModel.id.in_(identifiers),
            WhatsAppMessageLogModel.batch_id == batch_id,
            WhatsAppMessageLogModel.message_type == "document_update",
            WhatsAppMessageLogModel.status == "queued",
        ).values(status="processing", status_updated_at=now)
        .returning(WhatsAppMessageLogModel.id)
        .execution_options(synchronize_session=False)
    )).all())
    await session.execute(update(WhatsAppMessageLogModel).where(
        WhatsAppMessageLogModel.id.in_(identifiers),
        WhatsAppMessageLogModel.batch_id == batch_id,
        WhatsAppMessageLogModel.message_type == "document_update",
        WhatsAppMessageLogModel.status == "processing",
        WhatsAppMessageLogModel.status_updated_at < now - DOCUMENT_DELIVERY_STALE_AFTER,
    ).values(status="delivery_unknown", status_updated_at=now,
             error_message="Interrupted update request; automatic resend is suppressed.")
      .execution_options(synchronize_session=False))
    await session.commit()
    return claimed


async def _persist_update_wave(
    session: AsyncSession, batch_id: uuid.UUID, outcomes: list[UpdateProviderOutcome],
    account: str | None,
) -> None:
    failures: list[Exception] = []
    for outcome in outcomes:
        try:
            # A preceding binding rollback can expire every ORM instance. Reload
            # using immutable outcomes so other known acceptances are still saved.
            log = await session.scalar(select(WhatsAppMessageLogModel).where(
                WhatsAppMessageLogModel.id == outcome.log_id,
                WhatsAppMessageLogModel.batch_id == batch_id,
            ).with_for_update().execution_options(populate_existing=True))
            if log is None:
                raise RuntimeError("Update attempt disappeared before its result was saved")
            if log.provider_message_id and log.provider_message_id != outcome.provider_id:
                raise RuntimeError("Update provider acceptance conflicts with the saved attempt")
            if log.provider_message_id is None:
                log.status, log.error_message = outcome.status, outcome.error
                log.status_updated_at = outcome.updated_at or datetime.now(UTC)
            log.provider_message_id = outcome.provider_id
            await _save_provider_result(session, log, account)
        except Exception as exc:
            await session.rollback()
            failures.append(exc)
    if failures:
        raise failures[0]


async def _run_update_wave(
    *, batch_id: uuid.UUID, identifiers: list[uuid.UUID], deadline: float,
    client: httpx.AsyncClient, cache: GroupUpdateDispatchCache,
) -> None:
    settings = get_settings()
    cache.start_wave()
    async with AsyncSessionFactory() as session:
        claimed = await _claim_update_wave(session, batch_id, identifiers)
        if not claimed:
            return
        if session.get_bind().dialect.name == "postgresql":
            await session.execute(text("SET LOCAL idle_in_transaction_session_timeout = '60s'"))
        started = time.monotonic()
        snapshots = list((await session.scalars(select(WhatsAppMessageLogModel).where(
            WhatsAppMessageLogModel.id.in_(claimed),
        ).order_by(WhatsAppMessageLogModel.id))).all())
        decisions = {}
        frozen = {}
        # Only this coordinator uses the session. Shared source checks/locks are
        # acquired once per wave; exact-input matching is reused within the slice.
        for snapshot in snapshots:
            frozen[snapshot.id] = _frozen_snapshot(snapshot)
            decisions[snapshot.id] = await _source_decision(session, snapshot, cache=cache)
        logs = list((await session.scalars(select(WhatsAppMessageLogModel).where(
            WhatsAppMessageLogModel.id.in_(claimed),
            WhatsAppMessageLogModel.batch_id == batch_id,
            WhatsAppMessageLogModel.status == "processing",
        ).order_by(WhatsAppMessageLogModel.id).with_for_update()
          .execution_options(populate_existing=True))).all())
        requests: list[UpdateProviderRequest] = []
        outcomes: list[UpdateProviderOutcome] = []
        for log in logs:
            decision, reason = decisions[log.id]
            if frozen[log.id] != _frozen_snapshot(log):
                decision, reason = "failed", "UPDATE_SNAPSHOT_CHANGED: Review the update before sending."
            prepared = _prepare_request(log, decision, reason, deadline)
            if isinstance(prepared, UpdateProviderRequest):
                requests.append(prepared)
            else:
                outcomes.append(prepared)
        checked = time.monotonic()
        # No ORM access in these coroutines. Wait for ALL requests before the
        # first commit releases the authoritative source and destination locks.
        outcomes.extend(await send_update_wave(
            requests, client=client, settings=settings, send=send_whatsapp_document_update_template,
        ))
        sent = time.monotonic()
        await _persist_update_wave(session, batch_id, outcomes, settings.whatsapp_phone_number_id)
        logger.info(
            "document_update_wave_completed batch_id=%s candidates=%d sends=%d "
            "source_seconds=%.3f provider_seconds=%.3f save_seconds=%.3f",
            batch_id, len(claimed), len(requests), checked-started, sent-checked, time.monotonic()-sent,
        )


async def run_document_update_broadcast(*, batch_id: str) -> int:
    """Resume at most 25 rows, sending four requests per source-locked wave."""
    identifier = uuid.UUID(batch_id)
    deadline = time.monotonic() + DOCUMENT_DELIVERY_SLICE_SECONDS
    async with AsyncSessionFactory() as session:
        identifiers = list((await session.scalars(select(WhatsAppMessageLogModel.id).where(
            WhatsAppMessageLogModel.batch_id == identifier,
            WhatsAppMessageLogModel.message_type == "document_update",
            WhatsAppMessageLogModel.status.in_(("queued", "processing")),
        ).order_by(
            (WhatsAppMessageLogModel.status == "queued").desc(),
            WhatsAppMessageLogModel.created_at, WhatsAppMessageLogModel.id,
        ).limit(DOCUMENT_DELIVERY_SLICE_SIZE))).all())
    cache = GroupUpdateDispatchCache()
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
        for offset in range(0, len(identifiers), UPDATE_SEND_CONCURRENCY):
            if time.monotonic() >= deadline:
                break
            await _run_update_wave(
                batch_id=identifier, identifiers=identifiers[offset:offset+UPDATE_SEND_CONCURRENCY],
                deadline=deadline, client=client, cache=cache,
            )
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
