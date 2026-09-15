"""Bounded expiry and cleanup of receipt evidence, without changing send eligibility."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    WhatsAppProviderMessageBindingModel,
    WhatsAppProviderReceiptModel,
)
from app.infrastructure.whatsapp.receipt_bindings import (
    SOURCE_MODELS,
)
from app.infrastructure.whatsapp.receipt_runtime import RECEIPT_PAGE_SIZE, RECEIPT_RETENTION


async def apply_receipt_retention(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    """Run in the caller's transaction; pending evidence gets a seven-day tombstone."""
    observed = now or datetime.now(UTC)
    expired_ids = (
        select(WhatsAppProviderReceiptModel.id)
        .where(
            WhatsAppProviderReceiptModel.state == "pending",
            WhatsAppProviderReceiptModel.received_at <= observed - RECEIPT_RETENTION,
        )
        .order_by(WhatsAppProviderReceiptModel.received_at, WhatsAppProviderReceiptModel.id)
        .limit(RECEIPT_PAGE_SIZE)
        .with_for_update(skip_locked=True)
    )
    expired = list(
        (
            await session.scalars(
                update(WhatsAppProviderReceiptModel)
                .where(
                    WhatsAppProviderReceiptModel.id.in_(expired_ids),
                )
                .values(state="expired", processed_at=observed)
                .returning(WhatsAppProviderReceiptModel.id)
            )
        ).all()
    )
    terminal_ids = (
        select(WhatsAppProviderReceiptModel.id)
        .where(
            or_(
                and_(
                    WhatsAppProviderReceiptModel.state == "expired",
                    WhatsAppProviderReceiptModel.processed_at <= observed - timedelta(days=7),
                ),
                and_(
                    WhatsAppProviderReceiptModel.state.not_in({"pending", "expired"}),
                    WhatsAppProviderReceiptModel.received_at <= observed - RECEIPT_RETENTION,
                ),
            )
        )
        .order_by(WhatsAppProviderReceiptModel.received_at, WhatsAppProviderReceiptModel.id)
        .limit(RECEIPT_PAGE_SIZE)
        .with_for_update(skip_locked=True)
    )
    deleted = list(
        (
            await session.scalars(
                delete(WhatsAppProviderReceiptModel)
                .where(
                    WhatsAppProviderReceiptModel.id.in_(terminal_ids),
                )
                .returning(WhatsAppProviderReceiptModel.id)
            )
        ).all()
    )
    current_sources = []
    for kind, model in SOURCE_MODELS.items():
        reference = getattr(model, "provider_reference" if kind == "otp" else "provider_message_id")
        attempt = getattr(model, "send_batch_id") if kind in {"document", "qr"} else model.id
        current_sources.append(
            and_(
                WhatsAppProviderMessageBindingModel.source_kind == kind,
                select(model.id)
                .where(
                    model.id == WhatsAppProviderMessageBindingModel.source_id,
                    attempt == WhatsAppProviderMessageBindingModel.source_attempt_key,
                    reference == WhatsAppProviderMessageBindingModel.provider_message_id,
                )
                .exists(),
            )
        )
    # Exclude current sources in SQL before LIMIT so a page of retained current
    # bindings cannot starve cleanup of older superseded attempts.
    stale_binding_ids = (
        select(WhatsAppProviderMessageBindingModel.id)
        .where(
            WhatsAppProviderMessageBindingModel.created_at <= observed - RECEIPT_RETENTION,
            ~or_(*current_sources),
            ~select(WhatsAppProviderReceiptModel.id)
            .where(
                WhatsAppProviderReceiptModel.provider_message_id
                == WhatsAppProviderMessageBindingModel.provider_message_id,
                WhatsAppProviderReceiptModel.state == "pending",
            )
            .exists(),
        )
        .order_by(
            WhatsAppProviderMessageBindingModel.created_at, WhatsAppProviderMessageBindingModel.id
        )
        .limit(RECEIPT_PAGE_SIZE)
        .with_for_update(skip_locked=True)
    )
    removed = list(
        (
            await session.scalars(
                delete(WhatsAppProviderMessageBindingModel)
                .where(
                    WhatsAppProviderMessageBindingModel.id.in_(stale_binding_ids),
                )
                .returning(WhatsAppProviderMessageBindingModel.id)
            )
        ).all()
    )
    return {
        "expired_whatsapp_receipts": len(expired),
        "deleted_whatsapp_receipts": len(deleted),
        "deleted_whatsapp_bindings": len(removed),
    }
