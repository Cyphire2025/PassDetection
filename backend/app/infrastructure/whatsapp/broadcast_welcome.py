"""Welcome history and reservations scoped to one broadcast and destination."""

from __future__ import annotations

import uuid
from collections.abc import Collection

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    WhatsAppBroadcastRecipientModel as Recipient,
)
from app.infrastructure.database.models import (
    WhatsAppMessageLogModel as Log,
)
from app.infrastructure.database.models import (
    WhatsAppPhoneWelcomeAttemptModel as Attempt,
)
from app.infrastructure.database.models import (
    WhatsAppRecipientMessageStateModel as State,
)

_RANK = {value: rank for rank, value in enumerate(
    ("failed", "queued", "processing", "delivery_unknown", "submitted", "sent", "delivered", "read")
)}
_STATUS = {rank: value for value, rank in _RANK.items()}


async def broadcast_welcome_states(
    session: AsyncSession, *, agency_id: uuid.UUID, broadcast_group_id: uuid.UUID,
    phones: Collection[str], exclude_attempt_id: uuid.UUID | None = None,
    exclude_batch_id: uuid.UUID | None = None,
    active_only: bool = False,
) -> dict[str, str]:
    """Preserve all history; another broadcast never suppresses this welcome.

    Claims are serialized by the broadcast row lock until their durable logs
    commit. Workers exclude only their own attempt and baseline reservation.
    """
    if not phones:
        return {}
    log_phone = func.coalesce(Log.normalized_phone_number, Recipient.normalized_phone_number)
    logs = select(log_phone.label("phone"), case(_RANK, value=Log.status, else_=-1).label("rank")).outerjoin(
        Recipient, Recipient.id == Log.recipient_id,
    ).where(Log.agency_id == agency_id, Log.broadcast_group_id == broadcast_group_id,
            Log.message_type == "welcome", log_phone.in_(phones))
    attempts = select(Attempt.normalized_phone_number, case(_RANK, value=Attempt.status, else_=-1)).where(
        Attempt.agency_id == agency_id, Attempt.broadcast_group_id == broadcast_group_id,
        Attempt.normalized_phone_number.in_(phones),
    )
    states = select(Recipient.normalized_phone_number, case(_RANK, value=State.status, else_=-1)).join(
        Recipient, Recipient.id == State.recipient_id,
    ).where(State.agency_id == agency_id, State.broadcast_group_id == broadcast_group_id,
            State.message_type == "welcome", Recipient.normalized_phone_number.in_(phones))
    if exclude_attempt_id is not None:
        logs = logs.where(Log.id != exclude_attempt_id)
        attempts = attempts.where(Attempt.id != exclude_attempt_id)
    if active_only:
        active = {"queued", "processing", "delivery_unknown"}
        logs = logs.where(Log.status.in_(active))
        attempts = attempts.where(Attempt.status.in_(active))
        states = states.where(State.status.in_(active))
    if exclude_batch_id is not None:
        states = states.where(or_(State.batch_id.is_(None), State.batch_id != exclude_batch_id,
                                  State.status.not_in({"queued", "processing"})))
    history = logs.union_all(attempts, states).subquery()
    rows = await session.execute(select(history.c.phone, func.max(history.c.rank)).group_by(history.c.phone))
    return {phone: _STATUS.get(rank, "delivery_unknown") for phone, rank in rows.all()}
