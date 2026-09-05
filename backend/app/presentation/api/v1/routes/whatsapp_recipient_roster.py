"""Whatsapp: recipient roster."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportRosterResolutionModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastRejectedContactModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.passport_whatsapp_matching_repository import (
    load_unresolved_passport_whatsapp_match_context,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_ACCEPTED_STATUSES,
    WHATSAPP_ROLES,
    _agency_filter,
    _recipient_delivery_state_maps,
    _recipient_response,
    _rejected_contact_response,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppRecipientRosterCountsResponse,
    WhatsAppRecipientRosterItemResponse,
    WhatsAppRecipientRosterResponse,
    WhatsAppReplacedRecipientResponse,
    WhatsAppUnidentifiedUploadResponse,
)
from app.presentation.dependencies.auth import require_role

router = APIRouter()


def _unidentified_submission_details(
    submission: PassportSubmissionModel,
) -> dict[str, Any]:
    details: dict[str, Any] = {
        "family_head_name": submission.family_head_name,
        "family_head_phone": submission.family_head_phone,
        "family_head_email": submission.family_head_email,
        "family_relation": submission.family_relation,
        "family_gender": submission.family_gender,
        "departure_city": submission.departure_city,
        "nearest_domestic_airport": submission.nearest_domestic_airport,
    }
    for fields in (
        submission.staff_metadata,
        submission.extracted_fields,
        submission.confirmed_fields,
    ):
        details.update(dict(fields or {}))
    return {str(key): value for key, value in details.items() if value is not None and value != ""}


async def _unidentified_uploads_for_broadcast(
    session: AsyncSession,
    *,
    broadcast_group_id: uuid.UUID,
    agency_id: uuid.UUID,
) -> list[WhatsAppUnidentifiedUploadResponse]:
    linked_group_result = await session.execute(
        select(ClientGroupModel)
        .join(
            ClientGroupWhatsAppBroadcastLinkModel,
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == ClientGroupModel.id,
        )
        .where(
            ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id == broadcast_group_id,
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == agency_id,
            ClientGroupModel.agency_id == agency_id,
            ClientGroupModel.deleted_at.is_(None),
        )
        .order_by(ClientGroupModel.name.asc(), ClientGroupModel.id.asc())
    )
    linked_client_groups = list(linked_group_result.scalars().all())
    unidentified: list[WhatsAppUnidentifiedUploadResponse] = []
    seen_submission_ids: set[uuid.UUID] = set()

    for client_group in linked_client_groups:
        (
            _linked_broadcasts,
            _recipients,
            submissions,
            rows,
        ) = await load_unresolved_passport_whatsapp_match_context(
            session,
            group_id=client_group.id,
            agency_id=agency_id,
            broadcast_group_ids=[broadcast_group_id],
        )
        submission_by_id = {submission.id: submission for submission in submissions}
        unmatched_submission_ids = {
            submission_id
            for row in rows
            if row.status == "unmatched_submission"
            for submission_id in row.submission_ids
        }
        for submission_id in unmatched_submission_ids:
            if submission_id in seen_submission_ids:
                continue
            submission = submission_by_id.get(submission_id)
            if submission is None:
                continue
            seen_submission_ids.add(submission_id)
            unidentified.append(
                WhatsAppUnidentifiedUploadResponse(
                    submission_id=submission.id,
                    client_group_id=client_group.id,
                    client_group_name=client_group.name,
                    name=submission.client_name,
                    phone_number=(submission.client_phone or submission.family_head_phone),
                    email=submission.client_email or submission.family_head_email,
                    details=_unidentified_submission_details(submission),
                    updated_at=submission.updated_at,
                )
            )

    unidentified.sort(
        key=lambda upload: (
            upload.client_group_name.casefold(),
            upload.name.casefold(),
            upload.updated_at,
            str(upload.submission_id),
        )
    )
    return unidentified


@router.get(
    "/groups/{group_id}/recipient-roster",
    response_model=WhatsAppRecipientRosterResponse,
)
async def get_broadcast_recipient_roster(
    group_id: uuid.UUID,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppRecipientRosterResponse:
    group_result = await session.execute(
        select(WhatsAppBroadcastGroupModel).where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
    )
    group = group_result.scalar_one_or_none()
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp broadcast group not found",
        )

    recipients_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel)
        .where(
            WhatsAppBroadcastRecipientModel.broadcast_group_id == group_id,
            WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
            WhatsAppBroadcastRecipientModel.removed_at.is_(None),
        )
        .order_by(
            WhatsAppBroadcastRecipientModel.display_order.asc().nullslast(),
            WhatsAppBroadcastRecipientModel.created_at.asc(),
            WhatsAppBroadcastRecipientModel.id.asc(),
        )
    )
    recipients = list(recipients_result.scalars().all())
    rejected_result = await session.execute(
        select(WhatsAppBroadcastRejectedContactModel)
        .where(
            WhatsAppBroadcastRejectedContactModel.broadcast_group_id == group_id,
            WhatsAppBroadcastRejectedContactModel.agency_id == group.agency_id,
        )
        .order_by(
            WhatsAppBroadcastRejectedContactModel.display_order.asc().nullslast(),
            WhatsAppBroadcastRejectedContactModel.created_at.asc(),
            WhatsAppBroadcastRejectedContactModel.id.asc(),
        )
    )
    rejected_contacts = list(rejected_result.scalars().all())
    replaced_result = await session.execute(
        select(
            WhatsAppBroadcastRecipientModel,
            PassportRosterResolutionModel,
            ClientGroupModel,
            PassportSubmissionModel,
        )
        .join(
            PassportRosterResolutionModel,
            WhatsAppBroadcastRecipientModel.suppressed_by_roster_resolution_id
            == PassportRosterResolutionModel.id,
        )
        .join(
            ClientGroupModel,
            PassportRosterResolutionModel.client_group_id == ClientGroupModel.id,
        )
        .join(
            PassportSubmissionModel,
            PassportRosterResolutionModel.submission_id == PassportSubmissionModel.id,
        )
        .where(
            WhatsAppBroadcastRecipientModel.broadcast_group_id == group_id,
            WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
            WhatsAppBroadcastRecipientModel.removed_at.is_not(None),
            WhatsAppBroadcastRecipientModel.suppressed_by_roster_resolution_id.is_not(None),
            PassportRosterResolutionModel.agency_id == group.agency_id,
            PassportRosterResolutionModel.status == "active",
            PassportRosterResolutionModel.resolution_type == "replacement",
            ClientGroupModel.agency_id == group.agency_id,
            PassportSubmissionModel.agency_id == group.agency_id,
        )
        .order_by(
            WhatsAppBroadcastRecipientModel.display_order.asc().nullslast(),
            PassportRosterResolutionModel.created_at.asc(),
            WhatsAppBroadcastRecipientModel.id.asc(),
        )
    )
    replaced_rows = list(replaced_result.all())
    states_by_recipient, resend_statuses_by_recipient = await _recipient_delivery_state_maps(
        session, recipients
    )
    unidentified_uploads = await _unidentified_uploads_for_broadcast(
        session,
        broadcast_group_id=group_id,
        agency_id=group.agency_id,
    )

    roster_models: list[
        tuple[
            Literal["recipient", "rejected", "replaced"],
            WhatsAppBroadcastRecipientModel | WhatsAppBroadcastRejectedContactModel,
        ]
    ] = (
        [("recipient", recipient) for recipient in recipients]
        + [("rejected", rejected_contact) for rejected_contact in rejected_contacts]
        + [
            ("replaced", recipient)
            for recipient, _resolution, _client_group, _submission in replaced_rows
        ]
    )
    replaced_by_recipient_id = {
        recipient.id: (resolution, client_group, submission)
        for recipient, resolution, client_group, submission in replaced_rows
    }
    roster_models.sort(
        key=lambda item: (
            item[1].display_order is None,
            item[1].display_order or 0,
            item[1].created_at,
            item[0],
            str(item[1].id),
        )
    )
    next_fallback_order = (
        max(
            (model.display_order or 0 for _, model in roster_models),
            default=0,
        )
        + 1
    )
    items: list[WhatsAppRecipientRosterItemResponse] = []
    for kind, model in roster_models:
        display_order = model.display_order
        if display_order is None:
            display_order = next_fallback_order
            next_fallback_order += 1
        if kind == "recipient":
            recipient = model
            assert isinstance(recipient, WhatsAppBroadcastRecipientModel)
            items.append(
                WhatsAppRecipientRosterItemResponse(
                    kind="recipient",
                    display_order=display_order,
                    recipient=_recipient_response(
                        recipient,
                        states_by_recipient.get(recipient.id, []),
                        resend_statuses_by_recipient.get(recipient.id, {}),
                    ),
                )
            )
        elif kind == "rejected":
            rejected_contact = model
            assert isinstance(
                rejected_contact,
                WhatsAppBroadcastRejectedContactModel,
            )
            items.append(
                WhatsAppRecipientRosterItemResponse(
                    kind="rejected",
                    display_order=display_order,
                    rejected_contact=_rejected_contact_response(rejected_contact),
                )
            )
        else:
            recipient = model
            assert isinstance(recipient, WhatsAppBroadcastRecipientModel)
            resolution, client_group, submission = replaced_by_recipient_id[recipient.id]
            items.append(
                WhatsAppRecipientRosterItemResponse(
                    kind="replaced",
                    display_order=display_order,
                    replaced_recipient=WhatsAppReplacedRecipientResponse(
                        recipient_id=recipient.id,
                        resolution_id=resolution.id,
                        client_group_id=client_group.id,
                        client_group_name=client_group.name,
                        name=resolution.original_recipient_name,
                        phone_number=resolution.original_recipient_phone,
                        normalized_phone_number=(resolution.replaced_recipient_normalized_phone),
                        imported_fields=dict(resolution.original_recipient_imported_fields),
                        replacement_submission_id=submission.id,
                        replacement_name=submission.client_name,
                        replacement_phone=submission.client_phone,
                        replaced_at=resolution.created_at,
                    ),
                )
            )

    for upload in unidentified_uploads:
        items.append(
            WhatsAppRecipientRosterItemResponse(
                kind="unidentified",
                display_order=next_fallback_order,
                unidentified_upload=upload,
            )
        )
        next_fallback_order += 1

    sent_count = 0
    failed_count = 0
    for recipient in recipients:
        recipient_states = states_by_recipient.get(recipient.id, [])
        resend_statuses = resend_statuses_by_recipient.get(recipient.id, {})
        if any(state.status in WHATSAPP_ACCEPTED_STATUSES for state in recipient_states):
            sent_count += 1
        if (
            any(state.status == "failed" for state in recipient_states)
            or "failed" in resend_statuses.values()
        ):
            failed_count += 1

    return WhatsAppRecipientRosterResponse(
        items=items,
        counts=WhatsAppRecipientRosterCountsResponse(
            all=len(recipients) + len(rejected_contacts),
            sent=sent_count,
            failed=failed_count,
            rejected=len(rejected_contacts),
            replaced=len(replaced_rows),
            unidentified=len(unidentified_uploads),
        ),
    )
