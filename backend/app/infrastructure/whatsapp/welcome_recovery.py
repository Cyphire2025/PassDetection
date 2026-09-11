"""Conservative recovery for stranded welcome intent; never sends a message."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    WhatsAppMessageLogModel,
    WhatsAppPhoneWelcomeAttemptModel,
    WhatsAppPhoneWelcomeModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.whatsapp.phone_welcome import sync_phone_welcome

STALE_WELCOME_AGE = timedelta(minutes=30)


async def recover_stale_welcomes(session: AsyncSession, *, now: datetime | None = None) -> int:
    now = now or datetime.now(tz=UTC)
    recovered = 0
    for model in (WhatsAppPhoneWelcomeAttemptModel, WhatsAppMessageLogModel):
        predicates = [
            model.status.in_({"queued", "processing"}),
            model.status_updated_at < now - STALE_WELCOME_AGE,
        ]
        if model is WhatsAppMessageLogModel:
            predicates.append(WhatsAppMessageLogModel.message_type == "welcome")
        row_ids = list((await session.execute(select(model.id).where(*predicates)
            .order_by(model.id).limit(500))).scalars().all())
        await session.commit()
        for row_id in row_ids:
            raw_row = (await session.execute(select(model).where(*predicates, model.id == row_id)
                .with_for_update(skip_locked=True).execution_options(populate_existing=True))).scalar_one_or_none()
            if raw_row is None:
                await session.commit()
                continue
            row = cast(WhatsAppPhoneWelcomeAttemptModel | WhatsAppMessageLogModel, raw_row)
            row.status = "delivery_unknown" if row.status == "processing" else "failed"
            row.error_message = (
                "Welcome provider outcome is unknown after worker interruption; automatic resend is suppressed."
                if row.status == "delivery_unknown"
                else "Welcome queue expired before provider submission."
            )
            row.status_updated_at = now
            if row.normalized_phone_number:
                await sync_phone_welcome(
                    session,
                    agency_id=row.agency_id,
                    phone=row.normalized_phone_number,
                    attempt_id=row.id,
                    status=row.status,
                )
            if isinstance(row, WhatsAppMessageLogModel) and not row.is_explicit_resend:
                await session.execute(
                    update(WhatsAppRecipientMessageStateModel)
                    .where(
                        WhatsAppRecipientMessageStateModel.recipient_id == row.recipient_id,
                        WhatsAppRecipientMessageStateModel.message_type == "welcome",
                        WhatsAppRecipientMessageStateModel.batch_id == row.batch_id,
                        WhatsAppRecipientMessageStateModel.status.in_({"queued", "processing"}),
                    )
                    .values(status=row.status, status_updated_at=now, updated_at=now)
                )
            recovered += 1
            # Release each outbox/phone pair before taking another phone. This
            # matches live workers and avoids a cross-batch lock-order cycle.
            await session.commit()
    return recovered + await _recover_orphaned_claims(session, now=now)


async def _recover_orphaned_claims(session: AsyncSession, *, now: datetime) -> int:
    # Confirmed welcome history survives list/group removal. A removed queued
    # outbox is definitively unsent; a removed processing outbox stays uncertain.
    rows = (
        (
            await session.execute(
                select(WhatsAppPhoneWelcomeModel)
                .where(
                    WhatsAppPhoneWelcomeModel.status.in_({"queued", "processing"}),
                    WhatsAppPhoneWelcomeModel.status_updated_at < now - STALE_WELCOME_AGE,
                    ~exists().where(
                        WhatsAppMessageLogModel.id == WhatsAppPhoneWelcomeModel.attempt_id
                    ),
                    ~exists().where(
                        WhatsAppPhoneWelcomeAttemptModel.id == WhatsAppPhoneWelcomeModel.attempt_id
                    ),
                )
                .order_by(WhatsAppPhoneWelcomeModel.id)
                .limit(500)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        row.status = "failed" if row.status == "queued" else "delivery_unknown"
        row.status_updated_at = row.updated_at = now
    return len(rows)


async def run_stale_welcome_recovery() -> None:
    async with AsyncSessionFactory() as session:
        await recover_stale_welcomes(session)
        await session.commit()
