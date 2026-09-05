"""Document distribution: delivery preview."""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.document_templates import (
    default_document_message_content,
    render_document_message,
)
from app.application.use_cases.whatsapp.group_submission_matching import (
    RecipientForComparison,
    SubmissionForComparison,
    compare_group_submissions,
)
from app.core.config.settings import get_settings
from app.domain.entities.entities import PassportSubmission
from app.infrastructure.database.models import (
    ClientGroupModel,
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    DocumentWhatsAppDeliveryModel,
    PassportSubmissionModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.repositories.operational_roster import operational_roster_member
from app.presentation.api.v1.routes.document_distribution_matching import (
    _linked_whatsapp_recipients,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    DOCUMENT_DELIVERY_IN_PROGRESS_STATUSES,
    SHARED_WHATSAPP_DESTINATION_REASON,
    DocumentDeliveryDecision,
    _document_delivery_decision,
    _passport_number,
    _preferred_document_message_content,
)
from app.presentation.api.v1.schemas.document_distribution_schemas import (
    DocumentDeliveryPreviewRecipient,
    DocumentDeliveryPreviewResponse,
    DocumentDeliveryPreviewSummary,
)


async def _build_document_delivery_preview(
    session: AsyncSession,
    *,
    group: ClientGroupModel,
    batch: DocumentDistributionBatchModel,
    passengers: list[PassportSubmission],
) -> DocumentDeliveryPreviewResponse:
    message_content_1, message_content_2 = default_document_message_content(batch.document_type)
    linked_broadcasts, recipient_models = await _linked_whatsapp_recipients(
        session,
        group=group,
    )
    recipients_for_comparison = [
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
    passenger_ids = [passenger.id for passenger in passengers]
    submission_models: list[PassportSubmissionModel] = []
    if passenger_ids:
        submission_result = await session.execute(
            select(PassportSubmissionModel).where(
                PassportSubmissionModel.id.in_(passenger_ids),
                operational_roster_member(),
                PassportSubmissionModel.group_id == group.id,
                PassportSubmissionModel.agency_id == group.agency_id,
            )
        )
        submission_models = list(submission_result.scalars().all())
    submissions_for_comparison = [
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
    ]
    match_rows, _ = await asyncio.to_thread(
        compare_group_submissions,
        recipients_for_comparison,
        submissions_for_comparison,
    )
    recipients_by_id = {recipient.id: recipient for recipient in recipient_models}
    recipient_by_submission: dict[
        uuid.UUID,
        tuple[WhatsAppBroadcastRecipientModel, str],
    ] = {}
    ambiguous_submission_ids: set[uuid.UUID] = set()
    for row in match_rows:
        if row.status == "multiple_submissions":
            ambiguous_submission_ids.update(row.submission_ids)
            continue
        if row.status != "submitted":
            continue
        candidates = sorted(
            (
                recipients_by_id[recipient_id]
                for recipient_id in row.recipient_ids
                if recipient_id in recipients_by_id
            ),
            key=lambda recipient: (
                linked_broadcasts.get(recipient.broadcast_group_id, "").casefold(),
                str(recipient.id),
            ),
        )
        if not candidates:
            continue
        selected_recipient = candidates[0]
        for submission_id in row.submission_ids:
            recipient_by_submission[submission_id] = (
                selected_recipient,
                linked_broadcasts[selected_recipient.broadcast_group_id],
            )

    documents_result = await session.execute(
        select(DistributedDocumentModel, DocumentDistributionBatchModel.status)
        .join(
            DocumentDistributionBatchModel,
            DocumentDistributionBatchModel.id == DistributedDocumentModel.batch_id,
        )
        .where(
            DistributedDocumentModel.group_id == group.id,
            DistributedDocumentModel.agency_id == group.agency_id,
            DistributedDocumentModel.document_type == batch.document_type,
            DistributedDocumentModel.match_status != "duplicate_document",
            DocumentDistributionBatchModel.group_id == group.id,
            DocumentDistributionBatchModel.agency_id == group.agency_id,
            DocumentDistributionBatchModel.document_type == batch.document_type,
        )
        .order_by(
            DistributedDocumentModel.created_at.desc(),
            DistributedDocumentModel.id.desc(),
        )
    )
    document_rows = list(documents_result.all())
    documents = [row[0] for row in document_rows]
    saved_document_ids = {
        document.id for document, batch_status in document_rows if batch_status == "saved"
    }
    documents_by_passenger: dict[uuid.UUID, list[DistributedDocumentModel]] = {}
    for document in documents:
        if document.passenger_id:
            documents_by_passenger.setdefault(document.passenger_id, []).append(document)

    document_ids = [document.id for document in documents]
    deliveries_by_document: dict[
        uuid.UUID,
        list[DocumentWhatsAppDeliveryModel],
    ] = {}
    if document_ids:
        delivery_result = await session.execute(
            select(DocumentWhatsAppDeliveryModel)
            .where(
                DocumentWhatsAppDeliveryModel.distributed_document_id.in_(document_ids),
                DocumentWhatsAppDeliveryModel.agency_id == group.agency_id,
                DocumentWhatsAppDeliveryModel.group_id == group.id,
            )
            .order_by(
                DocumentWhatsAppDeliveryModel.created_at.desc(),
                DocumentWhatsAppDeliveryModel.status_updated_at.desc(),
            )
        )
        delivery_models = list(delivery_result.scalars().all())
        message_content_1, message_content_2 = _preferred_document_message_content(
            delivery_models,
            fallback_content_1=message_content_1,
            fallback_content_2=message_content_2,
        )
        for delivery in delivery_models:
            if delivery.distributed_document_id:
                deliveries_by_document.setdefault(
                    delivery.distributed_document_id,
                    [],
                ).append(delivery)

    preview_rows: list[DocumentDeliveryPreviewRecipient] = []
    summary = DocumentDeliveryPreviewSummary(total_passengers=len(passengers))
    for passenger in passengers:
        passenger_documents = documents_by_passenger.get(passenger.id, [])
        matched_recipient = recipient_by_submission.get(passenger.id)
        recipient_model = matched_recipient[0] if matched_recipient else None
        broadcast_name = matched_recipient[1] if matched_recipient else None
        if not passenger_documents:
            summary.blocked += 1
            preview_rows.append(
                DocumentDeliveryPreviewRecipient(
                    passenger_id=passenger.id,
                    passenger_name=passenger.client_name,
                    passport_number=_passport_number(passenger),
                    document_type=batch.document_type,
                    recipient_id=recipient_model.id if recipient_model else None,
                    broadcast_group_id=(
                        recipient_model.broadcast_group_id if recipient_model else None
                    ),
                    broadcast_name=broadcast_name,
                    phone_number=(
                        recipient_model.normalized_phone_number if recipient_model else None
                    ),
                    delivery_status="blocked",
                    reason="No saved document is matched to this passenger.",
                )
            )
            continue

        for document in passenger_documents:
            delivery_history = deliveries_by_document.get(document.id, [])
            latest_delivery = delivery_history[0] if delivery_history else None
            if passenger.id in ambiguous_submission_ids:
                decision = DocumentDeliveryDecision(
                    status="blocked",
                    eligible=False,
                    resend_allowed=False,
                    reason=SHARED_WHATSAPP_DESTINATION_REASON,
                )
            else:
                decision = _document_delivery_decision(
                    saved=document.id in saved_document_ids,
                    match_status=document.match_status,
                    recipient_available=matched_recipient is not None,
                    delivery_history=delivery_history,
                )
            if decision.status == "ready":
                summary.ready += 1
            elif decision.status == "retryable":
                summary.retryable += 1
            elif decision.status == "already_sent":
                summary.already_sent += 1
            elif decision.status in DOCUMENT_DELIVERY_IN_PROGRESS_STATUSES:
                summary.in_progress += 1
            else:
                summary.blocked += 1

            preview_rows.append(
                DocumentDeliveryPreviewRecipient(
                    passenger_id=passenger.id,
                    passenger_name=passenger.client_name,
                    passport_number=_passport_number(passenger),
                    document_id=document.id,
                    document_filename=document.original_filename,
                    document_type=document.document_type,
                    recipient_id=recipient_model.id if recipient_model else None,
                    broadcast_group_id=(
                        recipient_model.broadcast_group_id if recipient_model else None
                    ),
                    broadcast_name=broadcast_name,
                    phone_number=(
                        recipient_model.normalized_phone_number if recipient_model else None
                    ),
                    delivery_id=latest_delivery.id if latest_delivery else None,
                    delivery_status=decision.status,
                    eligible=decision.eligible,
                    resend_allowed=decision.resend_allowed,
                    reason=decision.reason,
                    error_message=decision.error_message,
                    message_preview=(
                        render_document_message(
                            message_content_1=message_content_1,
                            message_content_2=message_content_2,
                        )
                        if matched_recipient
                        else None
                    ),
                )
            )

    settings = get_settings()
    template_name = settings.whatsapp_document_template_name.strip()
    provider_configured = bool(
        template_name and settings.whatsapp_access_token and settings.whatsapp_phone_number_id
    )
    configuration_error: str | None = None
    if not linked_broadcasts:
        configuration_error = "Link at least one opted-in WhatsApp broadcast to this group first."
    elif not provider_configured:
        configuration_error = (
            "The WhatsApp document template or Cloud API credentials are not configured."
        )
    elif summary.ready + summary.retryable + summary.already_sent == 0:
        configuration_error = "There are no saved documents available to send."

    return DocumentDeliveryPreviewResponse(
        group_id=group.id,
        batch_id=batch.id,
        document_type=batch.document_type,
        template_name=template_name or None,
        template_configured=provider_configured,
        linked_broadcast_count=len(linked_broadcasts),
        can_send=configuration_error is None,
        configuration_error=configuration_error,
        message_content_1=message_content_1,
        message_content_2=message_content_2,
        summary=summary,
        recipients=preview_rows,
    )
