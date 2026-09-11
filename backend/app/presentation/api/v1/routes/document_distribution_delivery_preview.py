"""Document distribution: delivery preview."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.document_templates import (
    default_document_message_content,
    render_document_message,
)
from app.core.config.settings import get_settings
from app.domain.entities.entities import PassportSubmission
from app.infrastructure.database.models import (
    ClientGroupModel,
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    DocumentWhatsAppDeliveryModel,
)
from app.infrastructure.whatsapp.phone_welcome import (
    welcome_required_reason,
    welcome_states_for_phones,
)
from app.infrastructure.whatsapp.traveller_destinations import load_traveller_destinations
from app.presentation.api.v1.routes.document_distribution_shared import (
    DOCUMENT_DELIVERY_IN_PROGRESS_STATUSES,
    DocumentDeliveryDecision,
    _document_delivery_decision,
    _passport_number,
    _preferred_document_message_content,
)
from app.presentation.api.v1.routes.traveller_welcome_preview import linked_welcome_sources
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
    sources = await linked_welcome_sources(session, group=group)
    source = sources[0] if sources else None
    destinations = {row.passenger_id: row for row in await load_traveller_destinations(
        session, agency_id=group.agency_id, group_id=group.id,
    )}
    phones = {row.phone_number for row in destinations.values() if row.phone_number}
    welcome_states = await welcome_states_for_phones(session, agency_id=group.agency_id, phones=phones)

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
        destination = destinations.get(passenger.id)
        phone = destination.phone_number if destination else None
        welcome_status = welcome_states.get(phone, "required") if phone else "blocked"
        welcome_reason = welcome_required_reason(welcome_status)
        passenger_documents = documents_by_passenger.get(passenger.id, [])
        candidate_documents: list[DistributedDocumentModel | None] = [*passenger_documents] or [None]
        for document in candidate_documents:
            history = deliveries_by_document.get(document.id, []) if document else []
            latest = history[0] if history else None
            blocker = None
            if document is None:
                blocker = "No saved document is matched to this passenger."
            elif not phone:
                blocker = destination.reason if destination else "The traveller is no longer on the approved roster."
            elif source is None:
                blocker = "Link an opted-in WhatsApp broadcast to this group first."
            elif welcome_reason:
                blocker = welcome_reason
            if blocker:
                decision = DocumentDeliveryDecision(status="blocked", eligible=False,
                    resend_allowed=False, reason=blocker)
            else:
                assert document is not None
                decision = _document_delivery_decision(
                    saved=document.id in saved_document_ids,
                    match_status=document.match_status,
                    recipient_available=True, delivery_history=history,
                )
            if welcome_reason and phone:
                summary.welcome_required += 1
            if decision.status in {"ready", "retryable", "already_sent"}:
                setattr(summary, decision.status, getattr(summary, decision.status) + 1)
            elif decision.status in DOCUMENT_DELIVERY_IN_PROGRESS_STATUSES:
                summary.in_progress += 1
            else:
                summary.blocked += 1
            preview_rows.append(DocumentDeliveryPreviewRecipient(
                passenger_id=passenger.id, passenger_name=passenger.client_name,
                passport_number=_passport_number(passenger),
                document_id=document.id if document else None,
                document_filename=document.original_filename if document else None,
                document_type=batch.document_type,
                recipient_id=None, broadcast_group_id=source.id if source else None,
                broadcast_name=source.name if source else None,
                phone_number=phone, phone_source="submission", welcome_status=welcome_status,
                welcome_required=welcome_reason is not None,
                delivery_id=latest.id if latest else None,
                delivery_status=decision.status, eligible=decision.eligible,
                resend_allowed=decision.resend_allowed, reason=decision.reason,
                error_message=decision.error_message,
                message_preview=render_document_message(
                    message_content_1=message_content_1, message_content_2=message_content_2,
                ) if phone else None,
            ))

    settings = get_settings()
    template_name = settings.whatsapp_document_template_name.strip()
    provider_configured = bool(
        template_name and settings.whatsapp_access_token and settings.whatsapp_phone_number_id
    )
    configuration_error: str | None = None
    if not sources:
        configuration_error = "Link at least one opted-in WhatsApp broadcast to this group first."
    elif not provider_configured:
        configuration_error = (
            "The WhatsApp document template or Cloud API credentials are not configured."
        )
    elif summary.ready + summary.retryable + summary.already_sent == 0:
        configuration_error = (
            "Send welcome to the remaining traveller numbers and wait for delivery confirmation first."
            if summary.welcome_required else "There are no saved documents available to send."
        )

    return DocumentDeliveryPreviewResponse(
        group_id=group.id,
        batch_id=batch.id,
        document_type=batch.document_type,
        template_name=template_name or None,
        template_configured=provider_configured,
        linked_broadcast_count=len(sources),
        can_send=configuration_error is None,
        configuration_error=configuration_error,
        message_content_1=message_content_1,
        message_content_2=message_content_2,
        summary=summary,
        recipients=preview_rows,
    )
