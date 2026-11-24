"""Pure persisted manual resolution rows for the current group roster."""


from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence

from app.application.use_cases.whatsapp.contact_normalization import normalize_whatsapp_phone
from app.application.use_cases.whatsapp.group_submission_matching import (
    RecipientFieldSet,
    SubmissionMatchRow,
)
from app.infrastructure.database.models import (
    PassportRosterResolutionModel,
    PassportSubmissionModel,
    WhatsAppBroadcastRecipientModel,
)


def stored_uuid_list(values: object) -> list[uuid.UUID]:
    """Return unique valid UUIDs from a persisted JSON list."""

    if not isinstance(values, list):
        return []
    parsed: list[uuid.UUID] = []
    for value in values:
        try:
            parsed.append(uuid.UUID(str(value)))
        except (TypeError, ValueError, AttributeError):
            continue
    return list(dict.fromkeys(parsed))


def include_active_resolution_rows(
    rows: list[SubmissionMatchRow],
    *,
    active_resolutions: Sequence[PassportRosterResolutionModel],
    submissions_by_id: Mapping[uuid.UUID, PassportSubmissionModel],
    recipients_by_id: Mapping[uuid.UUID, WhatsAppBroadcastRecipientModel],
    linked_broadcasts: Mapping[uuid.UUID, str],
) -> list[SubmissionMatchRow]:
    """Append deterministic manual replacement/rejection rows to matcher output."""

    for resolution in active_resolutions:
        submission = submissions_by_id.get(resolution.submission_id)
        if submission is None:
            continue
        if resolution.resolution_type == "replacement":
            suppressed = [
                recipients_by_id[recipient_id]
                for recipient_id in stored_uuid_list(resolution.suppressed_recipient_ids)
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
            selected_recipient = (
                recipients_by_id.get(resolution.broadcast_recipient_id)
                if resolution.broadcast_recipient_id is not None
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
    return rows


# Preserve the established public import and pickle namespace.
stored_uuid_list.__module__ = 'app.presentation.api.v1.routes.client_group_whatsapp_match_support'
include_active_resolution_rows.__module__ = 'app.presentation.api.v1.routes.client_group_whatsapp_match_support'
