"""SQL projections retain immutable send destinations and separate uncertain outcomes."""

from datetime import datetime
from typing import Any

from sqlalchemy import and_, case, func, select

from app.domain.whatsapp_delivery_status import WHATSAPP_ACCEPTED_STATUSES
from app.infrastructure.database.models import WhatsAppMessageLogModel

Log = WhatsAppMessageLogModel
ACTIVE = frozenset({"queued", "processing", "not_sent"})
UNCONFIRMED = frozenset({"delivery_unknown", "stalled"})


def history_status(stale_cutoff: datetime) -> Any:
    return case(
        (
            and_(Log.status.in_({"queued", "processing"}), Log.status_updated_at < stale_cutoff),
            "stalled",
        ),
        else_=Log.status,
    )


def history_predicates(stale_cutoff: datetime) -> dict[str, Any]:
    status = history_status(stale_cutoff)
    return {
        "sent": status.in_(WHATSAPP_ACCEPTED_STATUSES),
        "not_sent": status.in_(ACTIVE),
        "delivery_left": status.in_({"submitted", "sent"}),
        # Unknown outcomes are visible in Failed with an explicit Unconfirmed
        # label and cannot be retried. Never convert their stored status to failed.
        "failed": ~status.in_(WHATSAPP_ACCEPTED_STATUSES | ACTIVE),
    }


def history_aggregates(stale_cutoff: datetime) -> tuple[Any, ...]:
    return (
        func.count().label("all"),
        *(
            func.count().filter(predicate).label(name)
            for name, predicate in history_predicates(stale_cutoff).items()
        ),
    )


def message_history_statement(group_id: Any, stale_cutoff: datetime) -> Any:
    identity = func.coalesce(Log.batch_id, Log.id)
    return (
        select(
            identity.label("id"),
            Log.message_type,
            func.max(Log.rendered_message).label("message_preview"),
            func.min(Log.created_at).label("created_at"),
            func.max(Log.status_updated_at).label("updated_at"),
            *history_aggregates(stale_cutoff),
        )
        .where(Log.broadcast_group_id == group_id)
        .group_by(identity, Log.message_type)
    )


def escaped_history_search(value: str) -> str:
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
