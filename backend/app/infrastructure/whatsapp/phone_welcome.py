"""Tenant/phone-scoped welcome claims and confirmed-delivery prerequisite."""

from __future__ import annotations

import uuid
from collections.abc import Collection
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.contact_normalization import normalize_whatsapp_phone
from app.infrastructure.database.models import (
    WhatsAppMessageLogModel,
    WhatsAppPhoneWelcomeAttemptModel,
    WhatsAppPhoneWelcomeModel,
)

WELCOME_DELIVERED_STATUSES = frozenset({"delivered", "read"})
WELCOME_BLOCKING_STATUSES = frozenset(
    {"queued", "processing", "submitted", "sent", "delivered", "read", "delivery_unknown"}
)
WELCOME_REQUIRED = "Welcome must be delivered to this WhatsApp number before any further messages."
_RANK = {"queued": 0, "processing": 1, "submitted": 2, "sent": 3, "delivered": 4, "read": 5}


def welcome_required_reason(status: str | None) -> str | None:
    if status in WELCOME_DELIVERED_STATUSES:
        return None
    if status in {"queued", "processing"}:
        return (
            "Welcome is in progress. Wait for delivery confirmation before sending other messages."
        )
    if status in {"submitted", "sent"}:
        return "Waiting for WhatsApp to confirm welcome delivery before sending other messages."
    if status == "delivery_unknown":
        return "Welcome delivery is unknown. Review the outcome before sending any other messages."
    return WELCOME_REQUIRED


async def welcome_states_for_phones(
    session: AsyncSession, *, agency_id: uuid.UUID, phones: Collection[str]
) -> dict[str, str]:
    canonical = sorted({phone for phone in phones if normalize_whatsapp_phone(phone) == phone})
    if not canonical:
        return {}
    result = await session.execute(
        select(
            WhatsAppPhoneWelcomeModel.normalized_phone_number, WhatsAppPhoneWelcomeModel.status
        ).where(
            WhatsAppPhoneWelcomeModel.agency_id == agency_id,
            WhatsAppPhoneWelcomeModel.normalized_phone_number.in_(canonical),
        )
    )
    return {phone: status for phone, status in result.all()}


async def require_welcome_delivered(
    session: AsyncSession, *, agency_id: uuid.UUID, phone: str
) -> bool:
    states = await welcome_states_for_phones(session, agency_id=agency_id, phones=[phone])
    return states.get(phone) in WELCOME_DELIVERED_STATUSES


async def claim_phone_welcome(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    phone: str,
    attempt_id: uuid.UUID,
    attempt_kind: Literal["broadcast", "traveller"],
) -> str:
    """Return claimed, or the existing blocking status; caller commits the intent.

    A database unique constraint serializes all broadcast lists and traveller
    outboxes. Unknown outcomes and provider acceptance never become retryable
    merely because enough time elapsed.
    """
    if normalize_whatsapp_phone(phone) != phone:
        raise ValueError("A canonical WhatsApp destination is required")
    now = datetime.now(tz=UTC)
    insert = sqlite_insert if session.get_bind().dialect.name == "sqlite" else pg_insert
    statement = insert(WhatsAppPhoneWelcomeModel).values(
        id=uuid.uuid4(),
        agency_id=agency_id,
        normalized_phone_number=phone,
        status="queued",
        attempt_id=attempt_id,
        attempt_kind=attempt_kind,
        status_updated_at=now,
        created_at=now,
        updated_at=now,
    )
    claim_statement = statement.on_conflict_do_update(
        index_elements=["agency_id", "normalized_phone_number"],
        set_={
            "status": "queued",
            "attempt_id": attempt_id,
            "attempt_kind": attempt_kind,
            "provider_status_at": None,
            "status_updated_at": now,
            "updated_at": now,
        },
        where=WhatsAppPhoneWelcomeModel.status == "failed",
    ).returning(WhatsAppPhoneWelcomeModel.id)
    result = await session.execute(claim_statement.execution_options(synchronize_session=False))
    if result.scalar_one_or_none() is not None:
        return "claimed"
    states = await welcome_states_for_phones(session, agency_id=agency_id, phones=[phone])
    return states.get(phone, "delivery_unknown")


async def assert_phone_welcome_claim(
    session: AsyncSession, *, agency_id: uuid.UUID, phone: str, attempt_id: uuid.UUID
) -> bool:
    result = await session.execute(
        select(WhatsAppPhoneWelcomeModel.id).where(
            WhatsAppPhoneWelcomeModel.agency_id == agency_id,
            WhatsAppPhoneWelcomeModel.normalized_phone_number == phone,
            WhatsAppPhoneWelcomeModel.attempt_id == attempt_id,
            WhatsAppPhoneWelcomeModel.status.in_({"queued", "processing"}),
        )
    )
    return result.scalar_one_or_none() is not None


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


async def sync_phone_welcome(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    phone: str,
    attempt_id: uuid.UUID,
    status: str,
    provider_status_at: datetime | None = None,
) -> None:
    """Receipt success is monotonic; failure belongs only to its current attempt."""
    result = await session.execute(
        select(WhatsAppPhoneWelcomeModel)
        .where(
            WhatsAppPhoneWelcomeModel.agency_id == agency_id,
            WhatsAppPhoneWelcomeModel.normalized_phone_number == phone,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return
    now = datetime.now(tz=UTC)
    if row.status in WELCOME_DELIVERED_STATUSES:
        if status == "read" and row.status == "delivered":
            row.status = "read"
            row.updated_at = row.status_updated_at = now
        return
    if status not in WELCOME_DELIVERED_STATUSES and row.attempt_id != attempt_id:
        return
    if (
        status not in WELCOME_DELIVERED_STATUSES
        and provider_status_at
        and row.provider_status_at
        and (_aware(provider_status_at) < _aware(row.provider_status_at))
    ):
        return
    if status in WELCOME_DELIVERED_STATUSES:
        row.delivered_at = row.delivered_at or provider_status_at or now
    elif status in _RANK and _RANK.get(row.status, -1) > _RANK[status]:
        return
    row.status = status
    row.provider_status_at = provider_status_at or row.provider_status_at
    row.updated_at = row.status_updated_at = now


async def sync_welcome_from_log(session: AsyncSession, log: WhatsAppMessageLogModel) -> None:
    phone = getattr(log, "normalized_phone_number", None)
    if log.message_type == "welcome" and phone:
        await sync_phone_welcome(
            session,
            agency_id=log.agency_id,
            phone=phone,
            attempt_id=log.id,
            status=log.status,
            provider_status_at=log.provider_status_at,
        )


async def sync_failed_broadcast_welcomes(
    session: AsyncSession,
    *,
    batch_id: uuid.UUID | None = None,
    broadcast_group_id: uuid.UUID | None = None,
) -> None:
    predicates = [
        WhatsAppMessageLogModel.message_type == "welcome",
        WhatsAppMessageLogModel.status.in_({"failed", "delivery_unknown"}),
    ]
    if batch_id is not None:
        predicates.append(WhatsAppMessageLogModel.batch_id == batch_id)
    if broadcast_group_id is not None:
        predicates.append(WhatsAppMessageLogModel.broadcast_group_id == broadcast_group_id)
    logs = await session.execute(
        select(WhatsAppMessageLogModel)
        .join(
            WhatsAppPhoneWelcomeModel,
            WhatsAppPhoneWelcomeModel.attempt_id == WhatsAppMessageLogModel.id,
        )
        .where(*predicates, WhatsAppPhoneWelcomeModel.status.in_({"queued", "processing"}))
        .order_by(
            WhatsAppMessageLogModel.agency_id,
            WhatsAppMessageLogModel.normalized_phone_number,
            WhatsAppMessageLogModel.id,
        )
        .execution_options(populate_existing=True)
    )
    for log in logs.scalars().all():
        await sync_welcome_from_log(session, log)


async def fail_unclaimed_traveller_welcomes(
    session: AsyncSession, *, batch_id: uuid.UUID, error_message: str
) -> None:
    result = await session.execute(
        update(WhatsAppPhoneWelcomeAttemptModel)
        .where(
            WhatsAppPhoneWelcomeAttemptModel.batch_id == batch_id,
            WhatsAppPhoneWelcomeAttemptModel.status == "queued",
        )
        .values(
            status="failed",
            error_message=error_message[:2000],
            status_updated_at=datetime.now(tz=UTC),
        )
        .returning(
            WhatsAppPhoneWelcomeAttemptModel.agency_id,
            WhatsAppPhoneWelcomeAttemptModel.normalized_phone_number,
            WhatsAppPhoneWelcomeAttemptModel.id,
        )
        .execution_options(synchronize_session=False)
    )
    for agency_id, phone, attempt_id in sorted(
        result.all(), key=lambda row: (str(row[0]), row[1], str(row[2]))
    ):
        await sync_phone_welcome(
            session, agency_id=agency_id, phone=phone, attempt_id=attempt_id, status="failed"
        )


async def order_welcome_receipts(
    session: AsyncSession,
    events: list[tuple[str, str, str | None, datetime | None]],
) -> None:
    """Keep receipts monotonic while acquiring multi-phone locks canonically."""
    provider_ids = {event[0] for event in events}
    destinations: dict[str, tuple[str, str]] = {}
    if len(provider_ids) > 1:
        for model in (WhatsAppMessageLogModel, WhatsAppPhoneWelcomeAttemptModel):
            rows = await session.execute(
                select(
                    model.provider_message_id, model.agency_id, model.normalized_phone_number
                ).where(model.provider_message_id.in_(provider_ids))
            )
            for provider_id, agency_id, phone in rows.all():
                destinations[provider_id] = (str(agency_id), phone or "")
    events.sort(
        key=lambda item: (
            destinations.get(item[0], ("", item[0])),
            item[3] or datetime.min.replace(tzinfo=UTC),
        )
    )
