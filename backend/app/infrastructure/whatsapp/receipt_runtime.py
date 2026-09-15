"""Retry receipt reconciliation from the database. This module never sends messages."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import case, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.passenger_change_propagation import propagate_mobile_passenger_change
from app.infrastructure.database.gc_mobile_models import MobileOTPChallengeModel
from app.infrastructure.database.models import (
    DocumentWhatsAppDeliveryModel,
    PassengerQrWhatsAppDeliveryModel,
    WhatsAppMessageLogModel,
    WhatsAppPhoneWelcomeAttemptModel,
    WhatsAppProviderMessageBindingModel,
    WhatsAppProviderReceiptModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.observability.metrics import metrics
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.whatsapp.phone_welcome import sync_phone_welcome, sync_welcome_from_log
from app.infrastructure.whatsapp.receipt_bindings import (
    SOURCE_MODELS,
    ProviderBindingConflict,
    ReceiptSource,
    bind_provider_message,
    source_identity,
    source_provider_id,
)
from app.presentation.api.v1.routes.whatsapp_delivery_support import (
    _apply_provider_status_to_delivery_state,
    _apply_provider_status_to_message_log,
    _provider_status_state_predicates,
)

logger = logging.getLogger(__name__)
RECEIPT_RETENTION = timedelta(days=30)
RECEIPT_PAGE_SIZE = 200


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def receipt_retry_delay(attempt_count: int) -> timedelta:
    return timedelta(seconds=min(3600, 5 * 2 ** min(attempt_count, 10)))


async def _resolve_binding(
    session: AsyncSession,
    receipt: WhatsAppProviderReceiptModel,
) -> WhatsAppProviderMessageBindingModel | None:
    bindings = list(
        (
            await session.scalars(
                select(WhatsAppProviderMessageBindingModel).where(
                    WhatsAppProviderMessageBindingModel.provider_message_id
                    == receipt.provider_message_id,
                )
            )
        ).all()
    )
    compatible = [
        binding
        for binding in bindings
        if binding.provider_phone_number_id
        in {
            "",
            receipt.provider_phone_number_id,
        }
    ]
    if bindings:
        if len(compatible) != 1:
            raise ProviderBindingConflict("Provider account or source is ambiguous")
        return compatible[0]

    # Only historical rows lacking a binding reach this path. Exact stored IDs
    # are required; never infer a destination from today's roster or settings.
    sources: list[ReceiptSource] = []
    for model in SOURCE_MODELS.values():
        reference = getattr(
            model,
            "provider_reference" if model is MobileOTPChallengeModel else "provider_message_id",
        )
        sources.extend(
            cast(
                list[ReceiptSource],
                list(
                    (
                        await session.scalars(
                            select(model)
                            .where(reference == receipt.provider_message_id)
                            .limit(2)
                            .with_for_update()
                        )
                    ).all()
                ),
            )
        )
    if len(sources) > 1:
        raise ProviderBindingConflict("Historical provider ID matches multiple sources")
    if not sources:
        return None
    source = sources[0]
    kind, source_id, attempt_key = source_identity(source)
    return await bind_provider_message(
        session,
        source_kind=kind,
        source_id=source_id,
        source_attempt_key=attempt_key,
        provider_phone_number_id="",
        provider_message_id=receipt.provider_message_id,
        agency_id=source.agency_id,
    )


async def _apply_to_source(
    session: AsyncSession,
    receipt: WhatsAppProviderReceiptModel,
    binding: WhatsAppProviderMessageBindingModel,
    now: datetime,
) -> str:
    model = SOURCE_MODELS[binding.source_kind]
    source = cast(
        ReceiptSource | None,
        (
            await session.execute(
                select(model)
                .where(model.id == binding.source_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none(),
    )
    if source is None:
        return "source_missing"
    if (
        source_identity(source)[2] != binding.source_attempt_key
        or source_provider_id(source) != binding.provider_message_id
    ):
        return "superseded"
    status = receipt.provider_status
    timestamp = aware(receipt.provider_status_at) if receipt.provider_status_at else None
    # SQLite test storage drops timezone metadata; PostgreSQL returns aware
    # timestamps. Give every existing reducer the same UTC contract.
    if not isinstance(source, MobileOTPChallengeModel) and source.provider_status_at:
        source.provider_status_at = aware(source.provider_status_at)
    if isinstance(source, WhatsAppMessageLogModel):
        _apply_provider_status_to_message_log(
            source,
            provider_status=status,
            error_message=receipt.error_message,
            provider_status_at=timestamp,
            now=now,
        )
        if not source.is_explicit_resend:
            state = (
                await session.execute(
                    select(WhatsAppRecipientMessageStateModel)
                    .where(
                        *_provider_status_state_predicates(source, provider_status=status),
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if state is not None:
                if state.provider_status_at:
                    state.provider_status_at = aware(state.provider_status_at)
                _apply_provider_status_to_delivery_state(
                    state, provider_status=status, provider_status_at=timestamp, now=now
                )
        await sync_welcome_from_log(session, source)
    elif isinstance(source, WhatsAppPhoneWelcomeAttemptModel):
        from app.infrastructure.whatsapp.traveller_welcome_runtime import (
            apply_traveller_welcome_provider_status,
        )

        apply_traveller_welcome_provider_status(
            source,
            provider_status=status,
            error_message=receipt.error_message,
            provider_status_at=timestamp,
            now=now,
        )
        await sync_phone_welcome(
            session,
            agency_id=source.agency_id,
            phone=source.normalized_phone_number,
            attempt_id=source.id,
            status=source.status,
            provider_status_at=source.provider_status_at,
        )
    elif isinstance(source, DocumentWhatsAppDeliveryModel):
        from app.infrastructure.whatsapp.document_delivery_runtime import (
            ACCEPTED_STATUSES,
            apply_document_provider_status,
        )

        released = source.status in ACCEPTED_STATUSES
        apply_document_provider_status(
            source,
            provider_status=status,
            error_message=receipt.error_message,
            provider_status_at=timestamp,
            now=now,
        )
        if not released and source.status in ACCEPTED_STATUSES and source.passenger_id is not None:
            await propagate_mobile_passenger_change(
                session,
                agency_id=source.agency_id,
                group_id=source.group_id,
                passenger_submission_ids=[source.passenger_id],
                actor_user_id=None,
                change_kind="documents",
                reconcile_identities=False,
                propagation_key=f"document-delivery-receipt:{receipt.dedupe_key}",
            )
    elif isinstance(source, PassengerQrWhatsAppDeliveryModel):
        from app.infrastructure.whatsapp.qr_delivery_runtime import apply_qr_provider_status

        apply_qr_provider_status(
            source,
            provider_status=status,
            error_message=receipt.error_message,
            provider_status_at=timestamp,
            now=now,
        )
    elif isinstance(source, MobileOTPChallengeModel):
        if status == "failed" and source.status == "pending":
            source.status = "cancelled"
        source.updated_at = now
        await AuditLogRepository(session).record(
            action="mobile.otp_delivery_status",
            entity_type="mobile_otp_challenge",
            agency_id=source.agency_id,
            entity_id=str(source.id),
            metadata={
                "provider": source.provider,
                "delivery_status": status,
                "provider_error": receipt.error_message,
            },
        )
    return "applied"


async def reconcile_receipt(
    session: AsyncSession,
    receipt_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> str:
    """Apply one receipt and its audit/outbox changes in a single transaction."""
    observed = now or datetime.now(UTC)
    if session.get_bind().dialect.name == "postgresql":
        # A sender may still hold its source lock. Keep webhook latency bounded;
        # lock contention leaves durable pending work for a subsequent sweep.
        await session.execute(text("SET LOCAL lock_timeout = '500ms'"))
    receipt = (
        await session.execute(
            select(WhatsAppProviderReceiptModel)
            .where(
                WhatsAppProviderReceiptModel.id == receipt_id,
                WhatsAppProviderReceiptModel.state == "pending",
            )
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if receipt is None:
        await session.commit()
        return "skipped"
    receipt.attempt_count += 1
    if aware(receipt.received_at) <= observed - RECEIPT_RETENTION:
        outcome = "expired"
    else:
        try:
            binding = await _resolve_binding(session, receipt)
            if binding is None:
                outcome = "pending"
            else:
                receipt.binding_id = binding.id
                outcome = await _apply_to_source(session, receipt, binding, observed)
        except ProviderBindingConflict:
            outcome = "conflict"
            receipt.processing_error_code = "provider_binding_conflict"
    receipt.state = outcome
    if outcome == "pending":
        receipt.next_attempt_at = observed + receipt_retry_delay(receipt.attempt_count)
        receipt.processing_error_code = "provider_binding_not_yet_found"
    else:
        receipt.processed_at = observed
        if outcome != "conflict":
            receipt.processing_error_code = None
    await session.commit()
    metrics.increment(f"whatsapp.receipts.{outcome}")
    if outcome == "conflict":
        logger.warning("whatsapp_receipt_binding_conflict receipt_id=%s", receipt_id)
    return outcome


async def reconcile_pending_receipts(
    session: AsyncSession,
    *,
    receipt_ids: list[uuid.UUID] | None = None,
    limit: int = RECEIPT_PAGE_SIZE,
    now: datetime | None = None,
) -> dict[str, int]:
    observed = now or datetime.now(UTC)
    limit = max(1, min(limit, RECEIPT_PAGE_SIZE))
    if receipt_ids is None:
        receipt_ids = list(
            (
                await session.scalars(
                    select(WhatsAppProviderReceiptModel.id)
                    .where(
                        WhatsAppProviderReceiptModel.state == "pending",
                        WhatsAppProviderReceiptModel.next_attempt_at <= observed,
                    )
                    .order_by(
                        WhatsAppProviderReceiptModel.next_attempt_at,
                        WhatsAppProviderReceiptModel.received_at,
                        WhatsAppProviderReceiptModel.provider_phone_number_id,
                        WhatsAppProviderReceiptModel.provider_message_id,
                        WhatsAppProviderReceiptModel.provider_status_at.asc().nullsfirst(),
                        case(
                            {"sent": 0, "failed": 1, "delivered": 2, "read": 3},
                            value=WhatsAppProviderReceiptModel.provider_status,
                        ),
                        WhatsAppProviderReceiptModel.id,
                    )
                    .limit(limit)
                )
            ).all()
        )
        await session.commit()
    counts: dict[str, int] = {}
    for receipt_id in receipt_ids[:limit]:
        try:
            outcome = await reconcile_receipt(session, receipt_id, now=observed)
        except Exception as exc:
            await session.rollback()
            # Fence this retry update: another worker may have applied the row
            # after our rollback. Never move a terminal receipt back to pending.
            attempts = (
                await session.execute(
                    select(WhatsAppProviderReceiptModel.attempt_count)
                    .where(
                        WhatsAppProviderReceiptModel.id == receipt_id,
                        WhatsAppProviderReceiptModel.state == "pending",
                    )
                    .with_for_update(skip_locked=True)
                )
            ).scalar_one_or_none()
            if attempts is not None:
                await session.execute(
                    update(WhatsAppProviderReceiptModel)
                    .where(
                        WhatsAppProviderReceiptModel.id == receipt_id,
                        WhatsAppProviderReceiptModel.state == "pending",
                        WhatsAppProviderReceiptModel.attempt_count == attempts,
                    )
                    .values(
                        attempt_count=attempts + 1,
                        next_attempt_at=observed + receipt_retry_delay(attempts + 1),
                        processing_error_code="receipt_application_failed",
                    )
                )
            await session.commit()
            metrics.increment("whatsapp.receipts.retry_failures")
            logger.warning("whatsapp_receipt_retry error_type=%s", type(exc).__name__)
            outcome = "retry"
        counts[outcome] = counts.get(outcome, 0) + 1
    return counts


async def run_receipt_reconciliation() -> dict[str, int]:
    async with AsyncSessionFactory() as session:
        counts = await reconcile_pending_receipts(session)
        pending, oldest = (
            await session.execute(
                select(
                    func.count(WhatsAppProviderReceiptModel.id),
                    func.min(WhatsAppProviderReceiptModel.received_at),
                ).where(WhatsAppProviderReceiptModel.state == "pending")
            )
        ).one()
        now = datetime.now(UTC)
        age = max(0.0, (now - aware(oldest)).total_seconds()) if oldest else 0.0
        metrics.observe("whatsapp.receipts.pending", pending)
        metrics.observe("whatsapp.receipts.oldest_pending_seconds", age)
        metrics.observe("whatsapp.receipts.last_success_timestamp", now.timestamp())
        if age >= 86400:
            logger.warning(
                "whatsapp_receipts_need_attention pending=%s oldest_seconds=%s", pending, int(age)
            )
        logger.info("whatsapp_receipt_reconciliation pending=%s outcomes=%s", pending, counts)
        await session.commit()
        return counts
