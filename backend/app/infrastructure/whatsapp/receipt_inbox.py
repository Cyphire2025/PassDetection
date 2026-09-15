"""Normalize and durably enqueue verified Meta delivery receipts without raw PII."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.whatsapp_receipt_models import WhatsAppProviderReceiptModel
from app.presentation.api.v1.routes.whatsapp_delivery_support import (
    WHATSAPP_WEBHOOK_STATUSES,
    _iter_webhook_values,
    _parse_provider_status_at,
)


@dataclass(frozen=True, slots=True)
class VerifiedReceipt:
    provider_phone_number_id: str
    provider_message_id: str
    provider_status: str
    provider_status_at: datetime | None
    provider_error_code: str | None

    @property
    def dedupe_key(self) -> str:
        canonical = json.dumps(
            [
                1,
                self.provider_phone_number_id,
                self.provider_message_id,
                self.provider_status,
                self.provider_status_at.isoformat() if self.provider_status_at else None,
                self.provider_error_code,
            ],
            separators=(",", ":"),
            ensure_ascii=True,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_verified_receipts(payload: dict[str, Any]) -> tuple[list[VerifiedReceipt], int]:
    """Only call after signature verification. No raw error prose is retained."""
    events: list[VerifiedReceipt] = []
    received_messages = 0
    for value in _iter_webhook_values(payload):
        metadata = value.get("metadata")
        account = metadata.get("phone_number_id", "") if isinstance(metadata, dict) else ""
        if not isinstance(account, str) or len(account) > 255:
            continue
        statuses = value.get("statuses")
        for item in statuses if isinstance(statuses, list) else []:
            if not isinstance(item, dict):
                continue
            provider_id, status = item.get("id"), item.get("status")
            if not isinstance(provider_id, str) or not 0 < len(provider_id) <= 255:
                continue
            if not isinstance(status, str) or status not in WHATSAPP_WEBHOOK_STATUSES:
                continue
            errors = item.get("errors")
            first = errors[0] if isinstance(errors, list) and errors else None
            code = first.get("code") if isinstance(first, dict) else None
            safe_code = (
                str(code)[:64]
                if isinstance(code, (str, int))
                and not isinstance(code, bool)
                and str(code).isascii()
                and str(code).isdigit()
                else None
            )
            try:
                timestamp = _parse_provider_status_at(item.get("timestamp"))
            except OverflowError:
                timestamp = None
            events.append(
                VerifiedReceipt(
                    account,
                    provider_id,
                    status,
                    timestamp,
                    safe_code,
                )
            )
        messages = value.get("messages")
        if isinstance(messages, list):
            received_messages += len(messages)
    return events, received_messages


async def persist_verified_receipts(
    session: AsyncSession,
    events: list[VerifiedReceipt],
    *,
    now: datetime | None = None,
) -> list[uuid.UUID]:
    """Store normalized receipts atomically; caller must commit before ACK."""
    observed = now or datetime.now(UTC)
    insert = sqlite_insert if session.get_bind().dialect.name == "sqlite" else pg_insert
    ordered_ids: list[tuple[VerifiedReceipt, uuid.UUID]] = []
    # Canonical order also avoids duplicate webhook batches deadlocking on unique indexes.
    unique = {event.dedupe_key: event for event in events}
    for key, event in sorted(unique.items()):
        error = None
        if event.provider_status == "failed":
            suffix = f" ({event.provider_error_code})" if event.provider_error_code else ""
            error = f"WHATSAPP_PROVIDER_DELIVERY_FAILED: Meta reported that this message was not delivered{suffix}"
        result = await session.execute(
            insert(WhatsAppProviderReceiptModel)
            .values(
                id=uuid.uuid4(),
                dedupe_key=key,
                provider_phone_number_id=event.provider_phone_number_id,
                provider_message_id=event.provider_message_id,
                provider_status=event.provider_status,
                provider_status_at=event.provider_status_at,
                provider_error_code=event.provider_error_code,
                error_message=error,
                state="pending",
                received_at=observed,
                next_attempt_at=observed,
                attempt_count=0,
            )
            .on_conflict_do_nothing(index_elements=["dedupe_key"])
            .returning(WhatsAppProviderReceiptModel.id)
        )
        receipt_id = result.scalar_one_or_none()
        if receipt_id is None:
            receipt_id = await session.scalar(
                select(WhatsAppProviderReceiptModel.id).where(
                    WhatsAppProviderReceiptModel.dedupe_key == key,
                    WhatsAppProviderReceiptModel.state == "pending",
                )
            )
        if receipt_id is not None:
            ordered_ids.append((event, receipt_id))
    # Insert canonically for uniqueness locks, but apply a provider's events in
    # timestamp order, as the original webhook did. At equal timestamps a
    # delivered/read receipt wins over a failure, and failure wins over sent.
    rank = {"sent": 0, "failed": 1, "delivered": 2, "read": 3}
    ordered_ids.sort(
        key=lambda pair: (
            pair[0].provider_phone_number_id,
            pair[0].provider_message_id,
            pair[0].provider_status_at or datetime.min.replace(tzinfo=UTC),
            rank[pair[0].provider_status],
        )
    )
    return [receipt_id for _, receipt_id in ordered_ids]
