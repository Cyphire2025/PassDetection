"""Tenant-scoped recipient projections for exact group export matching."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.group_submission_matching import (
    SubmissionMatchRow,
    compare_group_submissions,
)
from app.domain.entities.entities import ClientGroup, PassportSubmission
from app.infrastructure.database.models import (
    ClientGroupWhatsAppBroadcastLinkModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.repositories.passport_whatsapp_matching_repository import (
    matching_field_keys_from_storage,
    recipient_comparison_from_model,
    submission_comparison_from_model,
)


async def _export_whatsapp_match_rows(
    session: AsyncSession,
    submissions: list[PassportSubmission],
    *,
    groups: list[ClientGroup] | None = None,
) -> dict[uuid.UUID, list[SubmissionMatchRow]]:
    """Build one production-grade recipient/submission comparison per group."""
    submissions_by_group: dict[uuid.UUID, list[PassportSubmission]] = {
        group.id: [] for group in (groups or [])
    }
    agency_ids: set[uuid.UUID] = set()
    for group in groups or []:
        if group.agency_id:
            agency_ids.add(group.agency_id)
    for submission in submissions:
        submissions_by_group.setdefault(submission.group_id, []).append(submission)
        if submission.agency_id:
            agency_ids.add(submission.agency_id)
    if not submissions_by_group or not agency_ids:
        return {}

    linked_result = await session.execute(
        select(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id,
            ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id,
            WhatsAppBroadcastGroupModel.name,
            ClientGroupWhatsAppBroadcastLinkModel.matching_field_keys,
        )
        .join(
            WhatsAppBroadcastGroupModel,
            WhatsAppBroadcastGroupModel.id
            == ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id,
        )
        .where(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id.in_(set(submissions_by_group)),
            ClientGroupWhatsAppBroadcastLinkModel.agency_id.in_(agency_ids),
            WhatsAppBroadcastGroupModel.agency_id.in_(agency_ids),
        )
    )
    linked_by_group: dict[uuid.UUID, dict[uuid.UUID, str]] = {}
    matching_fields_by_group: dict[
        uuid.UUID,
        dict[uuid.UUID, tuple[str, ...] | None],
    ] = {}
    for group_id, broadcast_id, broadcast_name, matching_fields in linked_result.all():
        linked_by_group.setdefault(group_id, {})[broadcast_id] = broadcast_name
        matching_fields_by_group.setdefault(group_id, {})[broadcast_id] = (
            matching_field_keys_from_storage(
                matching_fields,
            )
        )
    broadcast_ids = {
        broadcast_id for broadcasts in linked_by_group.values() for broadcast_id in broadcasts
    }
    if not broadcast_ids:
        return {}

    recipient_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel).where(
            WhatsAppBroadcastRecipientModel.broadcast_group_id.in_(broadcast_ids),
            WhatsAppBroadcastRecipientModel.agency_id.in_(agency_ids),
            WhatsAppBroadcastRecipientModel.removed_at.is_(None),
        )
    )
    recipients_by_broadcast: dict[
        uuid.UUID,
        list[WhatsAppBroadcastRecipientModel],
    ] = {}
    for recipient in recipient_result.scalars().all():
        recipients_by_broadcast.setdefault(
            recipient.broadcast_group_id,
            [],
        ).append(recipient)

    rows_by_group: dict[uuid.UUID, list[SubmissionMatchRow]] = {}
    for group_id, group_submissions in submissions_by_group.items():
        linked_broadcasts = linked_by_group.get(group_id, {})
        if not linked_broadcasts:
            continue
        matching_fields_by_broadcast = matching_fields_by_group.get(group_id, {})
        comparison_recipients = [
            recipient_comparison_from_model(
                recipient,
                linked_broadcasts,
                matching_fields_by_broadcast,
            )
            for broadcast_id in linked_broadcasts
            for recipient in recipients_by_broadcast.get(broadcast_id, [])
        ]
        comparison_submissions = [
            submission_comparison_from_model(submission) for submission in group_submissions
        ]
        rows, _ = compare_group_submissions(
            comparison_recipients,
            comparison_submissions,
        )
        rows_by_group[group_id] = rows
    return rows_by_group
