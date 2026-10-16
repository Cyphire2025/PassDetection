"""Type coverage counts people once; versions always use send identity, never text."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, case, func, select

from app.domain.whatsapp_delivery_status import WHATSAPP_ACCEPTED_STATUSES
from app.infrastructure.database.models import (
    WhatsAppBroadcastRecipientModel as Recipient,
)
from app.infrastructure.database.models import (
    WhatsAppMessageLogModel as Log,
)
from app.presentation.api.v1.routes.whatsapp_history_queries import (
    history_aggregates,
    history_status,
)

HISTORY_TYPES = ("welcome", "passport_link", "reminder", "group_invite", "document_update")


def canonical_history_type() -> Any:
    return case((Log.message_type == "update", "document_update"), else_=Log.message_type)


def preferred_type_attempts(group_id: uuid.UUID, agency_id: uuid.UUID, cutoff: datetime) -> Any:
    """Prefer any confirmed success, then the latest unresolved/failed attempt.

    A later failed repeat must not erase evidence that this person was reached.
    Delivery/read receipts take precedence over provider acceptance alone.
    """
    status = history_status(cutoff)
    priority = case(
        (status == "read", 4),
        (status == "delivered", 3),
        (status.in_(WHATSAPP_ACCEPTED_STATUSES), 2),
        else_=0,
    )
    ranked = (
        select(
            Log.recipient_id,
            canonical_history_type().label("message_type"),
            Log.id.label("message_log_id"),
            func.coalesce(Log.batch_id, Log.id).label("message_id"),
            status.label("status"),
            Log.status_updated_at,
            Log.error_message,
            func.row_number()
            .over(
                partition_by=(canonical_history_type(), Log.recipient_id),
                order_by=(priority.desc(), Log.created_at.desc(), Log.id.desc()),
            )
            .label("position"),
        )
        .where(Log.broadcast_group_id == group_id, Log.agency_id == agency_id)
        .subquery()
    )
    return select(ranked).where(ranked.c.position == 1).subquery()


def type_recipient_scope(
    group_id: uuid.UUID, agency_id: uuid.UUID, message_type: str, cutoff: datetime
) -> Any:
    preferred = preferred_type_attempts(group_id, agency_id, cutoff)
    return (
        select(
            Recipient.id.label("recipient_id"),
            Recipient.name,
            Recipient.normalized_phone_number.label("phone_number"),
            func.coalesce(preferred.c.status, "not_sent").label("status"),
            preferred.c.message_id,
            preferred.c.message_log_id,
            preferred.c.status_updated_at.label("updated_at"),
            preferred.c.error_message,
        )
        .outerjoin(
            preferred,
            and_(
                preferred.c.recipient_id == Recipient.id, preferred.c.message_type == message_type
            ),
        )
        .where(
            Recipient.broadcast_group_id == group_id,
            Recipient.agency_id == agency_id,
            Recipient.removed_at.is_(None),
        )
        .subquery()
    )


def type_send_statistics(group_id: uuid.UUID, agency_id: uuid.UUID) -> Any:
    return (
        select(
            canonical_history_type().label("message_type"),
            func.count(func.distinct(func.coalesce(Log.batch_id, Log.id))).label("send_count"),
            func.count(func.distinct(Log.batch_id)).label("version_count"),
            func.count().filter(Log.batch_id.is_(None)).label("legacy_record_count"),
            func.count().label("total_attempts"),
            func.count()
            .filter(Log.status.in_(WHATSAPP_ACCEPTED_STATUSES))
            .label("accepted_attempts"),
            func.max(Log.created_at).label("last_sent_at"),
        )
        .where(Log.broadcast_group_id == group_id, Log.agency_id == agency_id)
        .group_by(canonical_history_type())
    )


def type_coverage_statistics(group_id: uuid.UUID, agency_id: uuid.UUID, cutoff: datetime) -> Any:
    preferred = preferred_type_attempts(group_id, agency_id, cutoff)
    return (
        select(preferred.c.message_type, *history_aggregates(cutoff, preferred.c.status))
        .join(
            Recipient,
            Recipient.id == preferred.c.recipient_id,
        )
        .where(
            Recipient.broadcast_group_id == group_id,
            Recipient.agency_id == agency_id,
            Recipient.removed_at.is_(None),
        )
        .group_by(preferred.c.message_type)
    )


def numbered_type_versions(
    group_id: uuid.UUID, agency_id: uuid.UUID, message_type: str, cutoff: datetime
) -> Any:
    identity = func.coalesce(Log.batch_id, Log.id)
    grouped = (
        select(
            identity.label("id"),
            canonical_history_type().label("message_type"),
            func.max(Log.rendered_message).label("message_preview"),
            func.min(Log.created_at).label("created_at"),
            func.max(Log.status_updated_at).label("updated_at"),
            func.count().filter(Log.batch_id.is_not(None)).label("has_batch"),
            *history_aggregates(cutoff),
        )
        .where(
            Log.broadcast_group_id == group_id,
            Log.agency_id == agency_id,
            canonical_history_type() == message_type,
        )
        .group_by(identity, canonical_history_type())
        .subquery()
    )
    # Legacy records without a batch cannot establish a historical send boundary.
    # Keep them visible without inventing version numbers or merging by wording.
    ordinal = func.sum(case((grouped.c.has_batch > 0, 1), else_=0)).over(
        order_by=(grouped.c.created_at.asc(), grouped.c.id.asc()), rows=(None, 0)
    )
    return select(
        grouped, case((grouped.c.has_batch > 0, ordinal), else_=None).label("version_number")
    ).subquery()
