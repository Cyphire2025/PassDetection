"""Shared, tenant-scoped data loading for passport/WhatsApp matching."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.group_submission_matching import (
    RecipientForComparison,
    SubmissionForComparison,
    SubmissionMatchRow,
    compare_group_submissions,
)
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES
from app.infrastructure.database.models import (
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportRosterResolutionModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)


def _stored_uuid_list(values: object) -> list[uuid.UUID]:
    if not isinstance(values, list):
        return []
    parsed: list[uuid.UUID] = []
    for value in values:
        try:
            parsed.append(uuid.UUID(str(value)))
        except (TypeError, ValueError, AttributeError):
            continue
    return parsed


async def load_unresolved_passport_whatsapp_match_context(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
    broadcast_group_ids: list[uuid.UUID] | tuple[uuid.UUID, ...] | None = None,
) -> tuple[
    dict[uuid.UUID, str],
    list[WhatsAppBroadcastRecipientModel],
    list[PassportSubmissionModel],
    list[SubmissionMatchRow],
]:
    """Load and compare the unresolved roster for one passport group.

    Resolved replacement/rejection submissions and suppressed recipients are
    excluded so every caller uses the same current matching rules. Callers may
    scope the comparison to particular linked broadcasts; this keeps a global
    broadcast's Unidentified tab accurate when one passport group is linked to
    more than one broadcast.
    """

    linked_statement = (
        select(
            ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id,
            WhatsAppBroadcastGroupModel.name,
        )
        .join(
            WhatsAppBroadcastGroupModel,
            WhatsAppBroadcastGroupModel.id
            == ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id,
        )
        .where(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group_id,
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == agency_id,
            WhatsAppBroadcastGroupModel.agency_id == agency_id,
        )
    )
    if broadcast_group_ids is not None:
        linked_statement = linked_statement.where(
            ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id.in_(
                sorted(set(broadcast_group_ids), key=str)
            )
        )
    linked_result = await session.execute(linked_statement)
    linked_broadcasts = {
        broadcast_id: broadcast_name
        for broadcast_id, broadcast_name in linked_result.all()
    }

    resolution_result = await session.execute(
        select(PassportRosterResolutionModel).where(
            PassportRosterResolutionModel.client_group_id == group_id,
            PassportRosterResolutionModel.agency_id == agency_id,
            PassportRosterResolutionModel.status == "active",
        )
    )
    active_resolutions = list(resolution_result.scalars().all())
    excluded_submission_ids = {
        submission_id
        for resolution in active_resolutions
        for submission_id in (
            [resolution.submission_id]
            + _stored_uuid_list(resolution.excluded_submission_ids)
        )
    }

    recipient_models: list[WhatsAppBroadcastRecipientModel] = []
    if linked_broadcasts:
        recipient_result = await session.execute(
            select(WhatsAppBroadcastRecipientModel).where(
                WhatsAppBroadcastRecipientModel.agency_id == agency_id,
                WhatsAppBroadcastRecipientModel.broadcast_group_id.in_(
                    list(linked_broadcasts)
                ),
                WhatsAppBroadcastRecipientModel.removed_at.is_(None),
                WhatsAppBroadcastRecipientModel.suppressed_by_roster_resolution_id.is_(
                    None
                ),
            )
        )
        recipient_models = list(recipient_result.scalars().all())

    submission_result = await session.execute(
        select(PassportSubmissionModel).where(
            PassportSubmissionModel.group_id == group_id,
            PassportSubmissionModel.agency_id == agency_id,
            PassportSubmissionModel.status.in_(
                OFFICE_VISIBLE_PASSPORT_STATUS_VALUES
            ),
        )
    )
    submission_models = list(submission_result.scalars().all())

    recipient_values = [
        RecipientForComparison(
            id=recipient.id,
            broadcast_id=recipient.broadcast_group_id,
            broadcast_name=linked_broadcasts[recipient.broadcast_group_id],
            name=recipient.name,
            phone=recipient.normalized_phone_number,
            updated_at=recipient.created_at,
            imported_fields=dict(recipient.imported_fields or {}),
        )
        for recipient in recipient_models
    ]
    submission_values = [
        SubmissionForComparison(
            id=submission.id,
            name=submission.client_name,
            client_phone=submission.client_phone,
            family_head_phone=submission.family_head_phone,
            updated_at=submission.updated_at,
            client_email=submission.client_email,
            family_head_email=submission.family_head_email,
            confirmed_fields=dict(submission.confirmed_fields or {}),
            extracted_fields=dict(submission.extracted_fields or {}),
            staff_metadata=dict(submission.staff_metadata or {}),
        )
        for submission in submission_models
        if submission.id not in excluded_submission_ids
    ]
    rows, _counts = compare_group_submissions(
        recipient_values,
        submission_values,
    )
    return linked_broadcasts, recipient_models, submission_models, rows
