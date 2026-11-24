"""Current matching plus durable manual replacement/rejection tracking rows."""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.contact_normalization import (
    normalize_whatsapp_phone,
)
from app.application.use_cases.whatsapp.group_submission_matching import (
    RecipientFieldSet,
    SubmissionMatchRow,
    compare_group_submissions,
)
from app.domain.entities.entities import ClientGroup, PassportSubmission
from app.infrastructure.database.models import (
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportRosterResolutionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.repositories.passport_whatsapp_matching_repository import (
    matching_field_keys_from_storage,
    recipient_comparison_from_model,
    submission_comparison_from_model,
)


def _stored_resolution_uuid_list(values: list[str] | None) -> list[uuid.UUID]:
    parsed: list[uuid.UUID] = []
    for value in values or []:
        try:
            parsed.append(uuid.UUID(str(value)))
        except (TypeError, ValueError, AttributeError):
            continue
    return parsed


async def _whatsapp_tracking_export_rows(
    session: AsyncSession,
    *,
    group: ClientGroup,
    submissions: list[PassportSubmission],
) -> tuple[dict[uuid.UUID, str], list[SubmissionMatchRow]]:
    """Build the same complete roster view used by WhatsApp tracking."""

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
        )
    )
    linked_rows = linked_result.all()
    linked_broadcasts = {
        broadcast_id: broadcast_name
        for broadcast_id, broadcast_name, _matching_fields in linked_rows
    }
    matching_fields_by_broadcast = {
        broadcast_id: matching_field_keys_from_storage(matching_fields)
        for broadcast_id, _broadcast_name, matching_fields in linked_rows
    }

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
        for recipient_id in _stored_resolution_uuid_list(resolution.suppressed_recipient_ids)
    }
    excluded_submission_ids = {
        submission_id
        for resolution in active_resolutions
        for submission_id in (
            [resolution.submission_id]
            + _stored_resolution_uuid_list(resolution.excluded_submission_ids)
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
    comparison_recipients = [
        recipient_comparison_from_model(
            recipient,
            linked_broadcasts,
            matching_fields_by_broadcast,
        )
        for recipient in recipient_models
        if recipient.removed_at is None and recipient.id not in suppressed_recipient_ids
    ]
    submissions_by_id = {submission.id: submission for submission in submissions}
    comparison_submissions = [
        submission_comparison_from_model(submission)
        for submission in submissions
        if submission.id not in excluded_submission_ids
    ]
    rows, _counts = compare_group_submissions(
        comparison_recipients,
        comparison_submissions,
    )

    for resolution in active_resolutions:
        submission = submissions_by_id.get(resolution.submission_id)
        if submission is None:
            continue
        if resolution.resolution_type == "replacement":
            suppressed = [
                recipients_by_id[recipient_id]
                for recipient_id in _stored_resolution_uuid_list(
                    resolution.suppressed_recipient_ids
                )
                if recipient_id in recipients_by_id
            ]
            broadcast_pairs = list(
                dict.fromkeys(
                    (
                        recipient.broadcast_group_id,
                        linked_broadcasts.get(
                            recipient.broadcast_group_id,
                            "Linked broadcast",
                        ),
                    )
                    for recipient in suppressed
                )
            )
            selected_recipient_id = resolution.broadcast_recipient_id
            selected_recipient = (
                recipients_by_id.get(selected_recipient_id)
                if selected_recipient_id is not None
                else None
            )
            rows.append(
                SubmissionMatchRow(
                    status="replacement",
                    match_basis="manual_replacement",
                    normalized_phone=(
                        selected_recipient.normalized_phone_number if selected_recipient else None
                    ),
                    recipient_ids=tuple(recipient.id for recipient in suppressed),
                    submission_ids=(submission.id,),
                    broadcast_ids=tuple(item[0] for item in broadcast_pairs),
                    broadcast_names=tuple(item[1] for item in broadcast_pairs),
                    recipient_names=tuple(
                        recipient.name or "Unnamed recipient" for recipient in suppressed
                    ),
                    submission_names=(submission.client_name,),
                    updated_at=max(submission.updated_at, resolution.created_at),
                    confidence="high",
                    recipient_fields=tuple(
                        RecipientFieldSet(
                            recipient_id=recipient.id,
                            fields=dict(recipient.imported_fields or {}),
                        )
                        for recipient in suppressed
                    ),
                    resolution_id=resolution.id,
                )
            )
        else:
            rows.append(
                SubmissionMatchRow(
                    status="rejected_upload",
                    match_basis="manual_rejection",
                    normalized_phone=normalize_whatsapp_phone(submission.client_phone or ""),
                    recipient_ids=(),
                    submission_ids=(submission.id,),
                    broadcast_ids=(),
                    broadcast_names=(),
                    recipient_names=(),
                    submission_names=(submission.client_name,),
                    updated_at=max(submission.updated_at, resolution.created_at),
                    confidence="high",
                    resolution_id=resolution.id,
                )
            )
    return linked_broadcasts, rows


def _select_whatsapp_tracking_export_payload(
    submissions: list[PassportSubmission],
    rows: list[SubmissionMatchRow],
    *,
    tracking_status: str,
    broadcast_id: uuid.UUID | None,
) -> tuple[list[PassportSubmission], list[SubmissionMatchRow]]:
    selected_rows = [
        row
        for row in rows
        if (
            (tracking_status == "all" or row.status == tracking_status)
            and (broadcast_id is None or broadcast_id in row.broadcast_ids)
        )
    ]
    selected_submission_ids = {
        submission_id
        for row in selected_rows
        for submission_id in (
            row.candidate_submission_ids if row.status == "needs_review" else row.submission_ids
        )
    }
    return (
        [submission for submission in submissions if submission.id in selected_submission_ids],
        selected_rows,
    )
