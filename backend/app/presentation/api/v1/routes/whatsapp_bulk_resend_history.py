"""Fresh selected-recipient history and conservative stale-claim handling."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.whatsapp.group_invite_policy import (
    group_invite_blocking_statuses,
    message_phone_blocking_statuses,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_ACCEPTED_STATUSES,
    WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES,
    WHATSAPP_STALE_CLAIM_AGE,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppBulkResendDraft,
    WhatsAppBulkResendRequest,
)


async def expire_stale_explicit_claims(
    session: AsyncSession, *, group_id: uuid.UUID, body: WhatsAppBulkResendRequest
) -> None:
    now = datetime.now(tz=UTC)
    for previous_status, next_status, message in (
        ("queued", "failed", "Explicit resend claim expired before provider submission"),
        (
            "processing",
            "delivery_unknown",
            "Explicit resend outcome is unknown after worker interruption; another resend is blocked",
        ),
    ):
        if body.message_type == "group_invite" and previous_status == "queued":
            continue
        await session.execute(
            update(WhatsAppMessageLogModel)
            .where(
                WhatsAppMessageLogModel.broadcast_group_id == group_id,
                WhatsAppMessageLogModel.recipient_id.in_(body.recipient_ids),
                WhatsAppMessageLogModel.message_type == body.message_type,
                WhatsAppMessageLogModel.is_explicit_resend.is_(True),
                WhatsAppMessageLogModel.status == previous_status,
                WhatsAppMessageLogModel.status_updated_at < now - WHATSAPP_STALE_CLAIM_AGE,
            )
            .values(status=next_status, status_updated_at=now, error_message=message)
            .execution_options(synchronize_session=False)
        )


async def selection_delivery_maps(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    body: WhatsAppBulkResendDraft,
    lock_states: bool = True,
) -> tuple[
    dict[uuid.UUID, WhatsAppRecipientMessageStateModel],
    dict[uuid.UUID, set[str]],
    dict[uuid.UUID, WhatsAppMessageLogModel],
]:
    state_statement = select(WhatsAppRecipientMessageStateModel).where(
        WhatsAppRecipientMessageStateModel.broadcast_group_id == group_id,
        WhatsAppRecipientMessageStateModel.recipient_id.in_(body.recipient_ids),
        WhatsAppRecipientMessageStateModel.message_type == body.message_type,
    )
    if lock_states:
        state_statement = state_statement.with_for_update()
    states = list((await session.execute(state_statement)).scalars().all())
    active = list(
        (
            await session.execute(
                select(WhatsAppMessageLogModel).where(
                    WhatsAppMessageLogModel.broadcast_group_id == group_id,
                    WhatsAppMessageLogModel.recipient_id.in_(body.recipient_ids),
                    WhatsAppMessageLogModel.message_type == body.message_type,
                    WhatsAppMessageLogModel.status.in_(WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES),
                )
            )
        )
        .scalars()
        .all()
    )
    # PostgreSQL DISTINCT ON bounds history to one saved source per selected person.
    # An already accepted baseline never falls back to an unrelated failed message.
    retry_ids = [state.recipient_id for state in states if state.status == "failed"]
    sources = list(
        (
            await session.execute(
                select(WhatsAppMessageLogModel)
                .where(
                    WhatsAppMessageLogModel.broadcast_group_id == group_id,
                    WhatsAppMessageLogModel.recipient_id.in_(body.recipient_ids),
                    WhatsAppMessageLogModel.message_type == body.message_type,
                    (
                        WhatsAppMessageLogModel.status.in_(WHATSAPP_ACCEPTED_STATUSES)
                        | (
                            (WhatsAppMessageLogModel.status == "failed")
                            & WhatsAppMessageLogModel.recipient_id.in_(retry_ids)
                        )
                    ),
                )
                .distinct(WhatsAppMessageLogModel.recipient_id)
                .order_by(
                    WhatsAppMessageLogModel.recipient_id,
                    WhatsAppMessageLogModel.created_at.desc(),
                    WhatsAppMessageLogModel.status_updated_at.desc(),
                    WhatsAppMessageLogModel.id.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    active_by_recipient: dict[uuid.UUID, set[str]] = {}
    stale_cutoff = datetime.now(tz=UTC) - WHATSAPP_STALE_CLAIM_AGE
    for log in active:
        log_status = log.status
        if (
            body.message_type != "group_invite"
            and not lock_states
            and log.is_explicit_resend
            and log.status_updated_at < stale_cutoff
        ):
            # Preview mirrors send's stale recovery without changing any row.
            if log_status == "queued":
                continue
            if log_status == "processing":
                log_status = "delivery_unknown"
        active_by_recipient.setdefault(log.recipient_id, set()).add(log_status)
    if body.message_type in {"group_invite", "passport_link"}:
        recipients_result = await session.execute(
            select(WhatsAppBroadcastRecipientModel).where(
                WhatsAppBroadcastRecipientModel.broadcast_group_id == group_id,
                WhatsAppBroadcastRecipientModel.id.in_(body.recipient_ids),
            )
        )
        recipients = list(recipients_result.scalars().all())
        if body.message_type == "group_invite":
            invite_blocks = await group_invite_blocking_statuses(session, recipients)
        else:
            # An intentional resend may repeat a successful message. A failed
            # retry cannot bypass accepted delivery through an older recipient.
            invite_blocks = await message_phone_blocking_statuses(
                session,
                recipients,
                message_type="passport_link",
                include_accepted=False,
                stale_explicit_queued_cutoff=stale_cutoff if not lock_states else None,
            )
            retry_recipients = [item for item in recipients if item.id in retry_ids]
            invite_blocks.update(
                await message_phone_blocking_statuses(
                    session,
                    retry_recipients,
                    message_type="passport_link",
                    stale_explicit_queued_cutoff=stale_cutoff if not lock_states else None,
                )
            )
        for recipient_id, invite_status in invite_blocks.items():
            active_by_recipient.setdefault(recipient_id, set()).add(invite_status)
    return (
        {state.recipient_id: state for state in states},
        active_by_recipient,
        {source.recipient_id: source for source in sources},
    )


# Preserve existing public imports and pickle identities.
expire_stale_explicit_claims.__module__ = (
    "app.presentation.api.v1.routes.whatsapp_bulk_resend_support"
)
selection_delivery_maps.__module__ = "app.presentation.api.v1.routes.whatsapp_bulk_resend_support"
