"""Scoped, FK-ordered administrative deletion queries."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.infrastructure.database.models import (
    ClientGroupModel,
    NotificationModel,
    PassportProcessingJobModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastRejectedContactModel,
    WhatsAppBroadcastSupportContactModel,
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)


@dataclass(frozen=True, slots=True)
class _WhatsAppPurgeCounts:
    broadcast_groups: int
    recipients: int
    rejected_contacts: int
    support_contacts: int
    message_logs: int
    delivery_states: int


async def _delete_by_ids(
    session: AsyncSession,
    model: (
        type[PassportProcessingJobModel] | type[PassportSubmissionModel] | type[ClientGroupModel]
    ),
    column: InstrumentedAttribute[uuid.UUID],
    ids: list[uuid.UUID],
) -> int:
    if not ids:
        return 0
    result = await session.execute(delete(model).where(column.in_(ids)))
    return int(result.rowcount or 0)


async def _delete_whatsapp_broadcast_data(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID | None,
) -> _WhatsAppPurgeCounts:
    """Delete WhatsApp data in FK-safe order within the caller's transaction."""

    async def delete_model(
        model: (
            type[WhatsAppMessageLogModel]
            | type[WhatsAppRecipientMessageStateModel]
            | type[WhatsAppBroadcastSupportContactModel]
            | type[WhatsAppBroadcastRejectedContactModel]
            | type[WhatsAppBroadcastRecipientModel]
            | type[WhatsAppBroadcastGroupModel]
        ),
    ) -> int:
        stmt = delete(model)
        if agency_id is not None:
            stmt = stmt.where(model.agency_id == agency_id)
        result = await session.execute(stmt)
        return int(result.rowcount or 0)

    # Message logs and delivery states reference both groups and recipients,
    # while support contacts, rejected contacts, and recipients reference groups. Keep this
    # explicit instead of relying on database cascades so counts stay accurate
    # and the order is portable.
    message_logs = await delete_model(WhatsAppMessageLogModel)
    delivery_states = await delete_model(WhatsAppRecipientMessageStateModel)
    support_contacts = await delete_model(WhatsAppBroadcastSupportContactModel)
    rejected_contacts = await delete_model(WhatsAppBroadcastRejectedContactModel)
    recipients = await delete_model(WhatsAppBroadcastRecipientModel)
    broadcast_groups = await delete_model(WhatsAppBroadcastGroupModel)
    return _WhatsAppPurgeCounts(
        broadcast_groups=broadcast_groups,
        recipients=recipients,
        rejected_contacts=rejected_contacts,
        support_contacts=support_contacts,
        message_logs=message_logs,
        delivery_states=delivery_states,
    )


async def _delete_entity_rows(
    session: AsyncSession,
    model: type[NotificationModel],
    *,
    agency_id: uuid.UUID | None,
    group_entity_ids: list[str],
    submission_entity_ids: list[str],
) -> int:
    conditions: list[ColumnElement[bool]] = []
    if group_entity_ids:
        conditions.append(
            (model.entity_type == "client_group") & (model.entity_id.in_(group_entity_ids))
        )
    if submission_entity_ids:
        conditions.append(
            (model.entity_type == "passport_submission")
            & (model.entity_id.in_(submission_entity_ids))
        )
    if not conditions:
        return 0

    stmt = delete(model).where(or_(*conditions))
    if agency_id is not None:
        stmt = stmt.where(model.agency_id == agency_id)
    result = await session.execute(stmt)
    return int(result.rowcount or 0)
