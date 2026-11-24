"""Acquire the current scoped roster and run its shared matcher."""


from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping
from typing import Protocol

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.group_submission_matching import (
    SubmissionMatchRow,
    compare_group_submissions,
)
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES
from app.infrastructure.database.models import (
    PassportRosterResolutionModel,
    PassportSubmissionModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.repositories.passport_whatsapp_matching_repository import (
    recipient_comparison_from_model,
    submission_comparison_from_model,
)
from app.presentation.api.v1.routes.client_group_whatsapp_match_resolutions import (
    include_active_resolution_rows,
    stored_uuid_list,
)


class _ClientGroupScope(Protocol):
    id: uuid.UUID
    agency_id: uuid.UUID


async def load_current_whatsapp_match_rows(
    session: AsyncSession,
    *,
    group: _ClientGroupScope,
    linked_broadcasts: Mapping[uuid.UUID, str],
    matching_fields_by_broadcast: Mapping[uuid.UUID, tuple[str, ...] | None],
) -> tuple[list[SubmissionMatchRow], dict[uuid.UUID, PassportSubmissionModel]]:
    """Load one group's current roster and apply its durable manual decisions."""

    resolution_result = await session.execute(
        select(PassportRosterResolutionModel).where(
            PassportRosterResolutionModel.client_group_id == group.id,
            PassportRosterResolutionModel.agency_id == group.agency_id,
            PassportRosterResolutionModel.status == "active",
        )
    )
    active_resolutions = list(resolution_result.scalars().all())
    suppressed_recipient_ids = {
        recipient_id
        for resolution in active_resolutions
        for recipient_id in stored_uuid_list(resolution.suppressed_recipient_ids)
    }
    excluded_submission_ids = {
        submission_id
        for resolution in active_resolutions
        for submission_id in (
            resolution.submission_id,
            *stored_uuid_list(resolution.excluded_submission_ids),
        )
    }

    recipient_models: list[WhatsAppBroadcastRecipientModel] = []
    if linked_broadcasts:
        recipient_visibility = (
            or_(
                WhatsAppBroadcastRecipientModel.removed_at.is_(None),
                WhatsAppBroadcastRecipientModel.id.in_(suppressed_recipient_ids),
            )
            if suppressed_recipient_ids
            else WhatsAppBroadcastRecipientModel.removed_at.is_(None)
        )
        recipient_result = await session.execute(
            select(WhatsAppBroadcastRecipientModel).where(
                WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
                WhatsAppBroadcastRecipientModel.broadcast_group_id.in_(list(linked_broadcasts)),
                recipient_visibility,
            )
        )
        recipient_models = list(recipient_result.scalars().all())
    recipients_by_id = {recipient.id: recipient for recipient in recipient_models}
    linked_broadcast_map = dict(linked_broadcasts)
    matching_field_map = dict(matching_fields_by_broadcast)
    comparison_recipients = [
        recipient_comparison_from_model(
            recipient,
            linked_broadcast_map,
            matching_field_map,
        )
        for recipient in recipient_models
        if recipient.removed_at is None and recipient.id not in suppressed_recipient_ids
    ]

    submission_result = await session.execute(
        select(PassportSubmissionModel).where(
            PassportSubmissionModel.group_id == group.id,
            PassportSubmissionModel.agency_id == group.agency_id,
            PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
        )
    )
    submission_models = list(submission_result.scalars().all())
    submissions_by_id = {submission.id: submission for submission in submission_models}
    comparison_submissions = [
        submission_comparison_from_model(submission)
        for submission in submission_models
        if submission.id not in excluded_submission_ids
    ]
    rows, _ = await asyncio.to_thread(
        compare_group_submissions, comparison_recipients, comparison_submissions
    )
    return (
        include_active_resolution_rows(
            rows,
            active_resolutions=active_resolutions,
            submissions_by_id=submissions_by_id,
            recipients_by_id=recipients_by_id,
            linked_broadcasts=linked_broadcasts,
        ),
        submissions_by_id,
    )


# Preserve the established public import and pickle namespace.
_ClientGroupScope.__module__ = 'app.presentation.api.v1.routes.client_group_whatsapp_match_support'
load_current_whatsapp_match_rows.__module__ = 'app.presentation.api.v1.routes.client_group_whatsapp_match_support'
