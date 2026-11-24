"""QR delivery authorized roster matching and imported-source reads."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.group_submission_matching import compare_group_submissions
from app.application.use_cases.whatsapp.private_delivery_identity import (
    is_private_delivery_match,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.repositories.passport_whatsapp_matching_repository import (
    matching_field_keys_from_storage,
    recipient_comparison_from_model,
    submission_comparison_from_model,
)


def _passport_number(submission: PassportSubmissionModel) -> str | None:
    fields = submission.confirmed_fields or submission.extracted_fields or {}
    value = fields.get("passport_number")
    return str(value).strip() if value else None


async def _linked_recipients(
    session: AsyncSession,
    *,
    group: ClientGroupModel,
) -> tuple[
    dict[uuid.UUID, str],
    dict[uuid.UUID, tuple[str, ...] | None],
    list[WhatsAppBroadcastRecipientModel],
]:
    linked_result = await session.execute(
        select(
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
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group.id,
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == group.agency_id,
            WhatsAppBroadcastGroupModel.agency_id == group.agency_id,
            WhatsAppBroadcastGroupModel.recipient_opt_in_confirmed_at.is_not(None),
            WhatsAppBroadcastGroupModel.archived_at.is_(None),
        )
    )
    linked_rows = linked_result.all()
    linked = {
        broadcast_id: broadcast_name
        for broadcast_id, broadcast_name, _matching_fields in linked_rows
    }
    matching_fields_by_broadcast = {
        broadcast_id: matching_field_keys_from_storage(matching_fields)
        for broadcast_id, _broadcast_name, matching_fields in linked_rows
    }
    if not linked:
        return {}, {}, []
    recipient_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel).where(
            WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
            WhatsAppBroadcastRecipientModel.broadcast_group_id.in_(list(linked)),
            WhatsAppBroadcastRecipientModel.removed_at.is_(None),
            WhatsAppBroadcastRecipientModel.suppressed_by_roster_resolution_id.is_(None),
        )
    )
    return linked, matching_fields_by_broadcast, list(recipient_result.scalars().all())


def _matched_recipients(
    *,
    submissions: list[PassportSubmissionModel],
    recipients: list[WhatsAppBroadcastRecipientModel],
    linked_broadcasts: dict[uuid.UUID, str],
    matching_fields_by_broadcast: dict[
        uuid.UUID,
        tuple[str, ...] | None,
    ]
    | None = None,
) -> tuple[
    dict[uuid.UUID, tuple[WhatsAppBroadcastRecipientModel, str]],
    set[uuid.UUID],
]:
    comparison_recipients = [
        recipient_comparison_from_model(
            recipient,
            linked_broadcasts,
            matching_fields_by_broadcast,
        )
        for recipient in recipients
    ]
    comparison_submissions = [
        submission_comparison_from_model(submission) for submission in submissions
    ]
    rows, _ = compare_group_submissions(
        comparison_recipients,
        comparison_submissions,
    )
    recipients_by_id = {recipient.id: recipient for recipient in recipients}
    matched: dict[
        uuid.UUID,
        tuple[WhatsAppBroadcastRecipientModel, str],
    ] = {}
    ambiguous_submission_ids: set[uuid.UUID] = set()
    for row in rows:
        if row.status == "multiple_submissions" or len(row.submission_ids) > 1:
            ambiguous_submission_ids.update(row.submission_ids)
            continue
        if not is_private_delivery_match(row):
            continue
        submission_id = row.submission_ids[0]
        candidates = sorted(
            (
                recipients_by_id[recipient_id]
                for recipient_id in row.recipient_ids
                if recipient_id in recipients_by_id
            ),
            key=lambda recipient: (
                linked_broadcasts.get(
                    recipient.broadcast_group_id,
                    "",
                ).casefold(),
                str(recipient.id),
            ),
        )
        if not candidates:
            continue
        selected = candidates[0]
        matched[submission_id] = (
            selected,
            linked_broadcasts[selected.broadcast_group_id],
        )
    return matched, ambiguous_submission_ids
