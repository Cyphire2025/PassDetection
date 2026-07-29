"""Document distribution routes."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
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
from app.domain.entities.entities import (
    OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES,
    PassportSubmission,
    User,
    UserRole,
)
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    DocumentWhatsAppDeliveryModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.documents.distribution_ingestion import (
    TravelDocumentFile,
    TravelDocumentIngestionService,
)
from app.infrastructure.documents.document_matcher import DOCUMENT_TYPES, DocumentMatcher
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.schemas.document_distribution_schemas import (
    DeleteDistributionDocumentsRequest,
    DistributedDocumentResponse,
    DocumentBatchResponse,
    DocumentDeliveryPreviewRecipient,
    DocumentDeliveryPreviewResponse,
    DocumentDeliveryPreviewSummary,
    DocumentDeliveryTrackingCounts,
    DocumentDeliveryTrackingResponse,
    DocumentDeliveryTrackingRow,
    DocumentGroupResponse,
    DocumentPassengerReviewRow,
    RejectedDocumentResponse,
    SaveDocumentBatchResponse,
    SendDocumentBroadcastRequest,
    SendDocumentBroadcastResponse,
    VerifiedDocumentResponse,
    VerifyDocumentBatchResponse,
)
from app.presentation.dependencies.auth import get_current_active_user

router = APIRouter()


def _owner_scope_for(user: User) -> uuid.UUID | None:
    return user.id if user.role == UserRole.AGENCY_STAFF else None


def _submitted_statuses() -> tuple[str, ...]:
    return OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES


def _passport_number(passenger: PassportSubmission) -> str | None:
    fields = passenger.confirmed_fields or passenger.extracted_fields or {}
    value = fields.get("passport_number")
    return str(value).strip() if value else None


def _safe_filename(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())[:120]
    return name or "document.pdf"


DOCUMENT_DELIVERY_ACCEPTED_STATUSES = frozenset(
    {"submitted", "sent", "delivered", "read"}
)
DOCUMENT_DELIVERY_IN_PROGRESS_STATUSES = frozenset(
    {"queued", "processing", "delivery_unknown"}
)
DOCUMENT_DELIVERY_STORAGE_REQUIRED_STATUSES = frozenset({"queued", "processing"})


async def _latest_document_batch(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    document_type: str,
) -> DocumentDistributionBatchModel | None:
    result = await session.execute(
        select(DocumentDistributionBatchModel)
        .where(
            DocumentDistributionBatchModel.group_id == group_id,
            DocumentDistributionBatchModel.document_type == document_type,
        )
        .order_by(DocumentDistributionBatchModel.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _linked_whatsapp_recipients(
    session: AsyncSession,
    *,
    group: ClientGroupModel,
) -> tuple[dict[uuid.UUID, str], list[WhatsAppBroadcastRecipientModel]]:
    linked_result = await session.execute(
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
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group.id,
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == group.agency_id,
            WhatsAppBroadcastGroupModel.agency_id == group.agency_id,
            WhatsAppBroadcastGroupModel.recipient_opt_in_confirmed_at.is_not(None),
        )
    )
    linked_broadcasts = {
        broadcast_id: broadcast_name
        for broadcast_id, broadcast_name in linked_result.all()
    }
    if not linked_broadcasts:
        return {}, []
    recipient_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel).where(
            WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
            WhatsAppBroadcastRecipientModel.broadcast_group_id.in_(
                list(linked_broadcasts)
            ),
            WhatsAppBroadcastRecipientModel.removed_at.is_(None),
        )
    )
    return linked_broadcasts, list(recipient_result.scalars().all())


async def _build_document_delivery_preview(
    session: AsyncSession,
    *,
    group: ClientGroupModel,
    batch: DocumentDistributionBatchModel,
    passengers: list[PassportSubmission],
) -> DocumentDeliveryPreviewResponse:
    message_content_1, message_content_2 = default_document_message_content(
        batch.document_type
    )
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
    match_rows, _ = compare_group_submissions(
        recipients_for_comparison,
        submissions_for_comparison,
    )
    recipients_by_id = {recipient.id: recipient for recipient in recipient_models}
    recipient_by_submission: dict[
        uuid.UUID,
        tuple[WhatsAppBroadcastRecipientModel, str],
    ] = {}
    for row in match_rows:
        if row.status not in {"submitted", "multiple_submissions"}:
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
        select(DistributedDocumentModel)
        .where(DistributedDocumentModel.batch_id == batch.id)
        .order_by(
            DistributedDocumentModel.match_confidence.desc(),
            DistributedDocumentModel.created_at.asc(),
        )
    )
    documents = list(documents_result.scalars().all())
    documents_by_passenger: dict[uuid.UUID, DistributedDocumentModel] = {}
    for document in documents:
        if document.passenger_id and document.match_status != "duplicate_document":
            documents_by_passenger.setdefault(document.passenger_id, document)

    document_ids = [document.id for document in documents]
    deliveries_by_document: dict[uuid.UUID, DocumentWhatsAppDeliveryModel] = {}
    if document_ids:
        delivery_result = await session.execute(
            select(DocumentWhatsAppDeliveryModel).where(
                DocumentWhatsAppDeliveryModel.distributed_document_id.in_(document_ids)
            )
        )
        deliveries_by_document = {
            delivery.distributed_document_id: delivery
            for delivery in delivery_result.scalars().all()
            if delivery.distributed_document_id
        }

    preview_rows: list[DocumentDeliveryPreviewRecipient] = []
    summary = DocumentDeliveryPreviewSummary(total_passengers=len(passengers))
    for passenger in passengers:
        document = documents_by_passenger.get(passenger.id)
        matched_recipient = recipient_by_submission.get(passenger.id)
        existing_delivery = (
            deliveries_by_document.get(document.id) if document else None
        )
        delivery_status = "blocked"
        eligible = False
        reason = "No saved document is matched to this passenger."
        if document and document.match_status != "matched":
            reason = "The document still needs manual matching review."
        elif document and not matched_recipient:
            reason = (
                "No confirmed WhatsApp recipient could be matched to this passenger "
                "from the linked broadcasts."
            )
        elif document and matched_recipient:
            if existing_delivery and existing_delivery.status in DOCUMENT_DELIVERY_ACCEPTED_STATUSES:
                delivery_status = "already_sent"
                reason = "This document was already accepted by WhatsApp."
                summary.already_sent += 1
            elif existing_delivery and existing_delivery.status in DOCUMENT_DELIVERY_IN_PROGRESS_STATUSES:
                delivery_status = existing_delivery.status
                reason = (
                    "Delivery is already in progress."
                    if existing_delivery.status != "delivery_unknown"
                    else "The previous delivery outcome is uncertain; automatic resend is suppressed."
                )
                summary.in_progress += 1
            elif existing_delivery and existing_delivery.status == "failed":
                delivery_status = "retryable"
                reason = "The previous attempt failed and can be retried safely."
                eligible = True
                summary.retryable += 1
            else:
                delivery_status = "ready"
                reason = "Ready to send."
                eligible = True
                summary.ready += 1
        if not eligible and delivery_status == "blocked":
            summary.blocked += 1

        recipient_model = matched_recipient[0] if matched_recipient else None
        broadcast_name = matched_recipient[1] if matched_recipient else None
        preview_rows.append(
            DocumentDeliveryPreviewRecipient(
                passenger_id=passenger.id,
                passenger_name=passenger.client_name,
                passport_number=_passport_number(passenger),
                document_id=document.id if document else None,
                document_filename=document.original_filename if document else None,
                document_type=batch.document_type,
                recipient_id=recipient_model.id if recipient_model else None,
                broadcast_group_id=(
                    recipient_model.broadcast_group_id if recipient_model else None
                ),
                broadcast_name=broadcast_name,
                phone_number=(
                    recipient_model.normalized_phone_number
                    if recipient_model
                    else None
                ),
                delivery_id=existing_delivery.id if existing_delivery else None,
                delivery_status=delivery_status,
                eligible=eligible,
                reason=reason,
                error_message=(
                    existing_delivery.error_message
                    if existing_delivery and existing_delivery.status == "failed"
                    else None
                ),
                message_preview=(
                    render_document_message(
                        message_content_1=message_content_1,
                        message_content_2=message_content_2,
                    )
                    if document and matched_recipient
                    else None
                ),
            )
        )

    settings = get_settings()
    template_name = settings.whatsapp_document_template_name.strip()
    provider_configured = bool(
        template_name
        and settings.whatsapp_access_token
        and settings.whatsapp_phone_number_id
    )
    configuration_error: str | None = None
    if batch.status != "saved":
        configuration_error = "Save this reviewed document list before sending."
    elif not linked_broadcasts:
        configuration_error = (
            "Link at least one opted-in WhatsApp broadcast to this group first."
        )
    elif not provider_configured:
        configuration_error = (
            "The WhatsApp document template or Cloud API credentials are not configured."
        )
    elif summary.ready + summary.retryable == 0:
        configuration_error = "There are no new or safely retryable documents to send."

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


async def _get_authorized_group(
    group_id: uuid.UUID,
    *,
    current_user: User,
    session: AsyncSession,
) -> ClientGroupModel:
    if not current_user.agency_id or current_user.role == UserRole.AGENCY_COORDINATOR:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    group_repo = ClientGroupRepository(session)
    group = await group_repo.get_by_id(group_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client group was not found")
    try:
        await AuthorizationPolicy(session).require_export_data(current_user, group)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message)

    result = await session.execute(select(ClientGroupModel).where(ClientGroupModel.id == group_id))
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client group was not found")
    return model


async def _group_passengers(
    group_id: uuid.UUID,
    *,
    current_user: User,
    session: AsyncSession,
) -> list[PassportSubmission]:
    if not current_user.agency_id:
        return []
    return await PassportSubmissionRepository(session).list_by_group(
        current_user.agency_id,
        group_id,
        limit=5000,
        exclude_archived_groups=True,
        created_by_user_id=_owner_scope_for(current_user),
        visible_to_user=current_user,
    )


async def _document_response(document: DistributedDocumentModel, storage: MinioStorageRepository) -> DistributedDocumentResponse:
    return DistributedDocumentResponse(
        id=document.id,
        original_filename=document.original_filename,
        document_type=document.document_type,
        detected_type=document.detected_type,
        match_status=document.match_status,
        match_confidence=document.match_confidence,
        match_reason=document.match_reason,
        extracted_name=document.extracted_name,
        extracted_passport_number=document.extracted_passport_number,
        extracted_reference=document.extracted_reference,
        url=await storage.get_presigned_url(document.storage_key),
    )


async def _batch_response(
    *,
    group_id: uuid.UUID,
    document_type: str,
    passengers: list[PassportSubmission],
    batch: DocumentDistributionBatchModel | None,
    documents: list[DistributedDocumentModel],
    rejected_documents: list[RejectedDocumentResponse] | None = None,
) -> DocumentBatchResponse:
    storage = MinioStorageRepository()
    docs_by_passenger: dict[uuid.UUID, DistributedDocumentModel] = {}
    unmatched: list[DistributedDocumentResponse] = []
    for document in documents:
        if document.passenger_id and document.match_status in {"matched", "needs_review"} and document.passenger_id not in docs_by_passenger:
            docs_by_passenger[document.passenger_id] = document
        elif document.match_status == "needs_review" or (not document.passenger_id and document.match_status != "duplicate_document"):
            unmatched.append(await _document_response(document, storage))

    rows = [
        DocumentPassengerReviewRow(
            passenger_id=passenger.id,
            passenger_name=passenger.client_name,
            passport_number=_passport_number(passenger),
            departure_city=passenger.departure_city,
            document=await _document_response(document, storage) if (document := docs_by_passenger.get(passenger.id)) else None,
        )
        for passenger in passengers
    ]

    return DocumentBatchResponse(
        batch_id=batch.id if batch else None,
        group_id=group_id,
        document_type=document_type,
        status=batch.status if batch else "draft",
        uploaded_count=batch.uploaded_count if batch else 0,
        rejected_count=batch.rejected_count if batch else 0,
        matched_count=batch.matched_count if batch else 0,
        saved_at=batch.saved_at if batch else None,
        created_at=batch.created_at if batch else None,
        review_rows=rows,
        unmatched_documents=unmatched,
        rejected_documents=rejected_documents or [],
    )


@router.get("/groups", response_model=list[DocumentGroupResponse])
async def list_document_groups(
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[DocumentGroupResponse]:
    if not current_user.agency_id or current_user.role == UserRole.AGENCY_COORDINATOR:
        return []

    stmt = select(ClientGroupModel).where(ClientGroupModel.agency_id == current_user.agency_id)
    stmt = stmt.where(ClientGroupModel.status.notin_(["archived", "deleted"]))
    stmt = AuthorizationPolicy.apply_group_visibility_scope(stmt, current_user)
    stmt = stmt.order_by(ClientGroupModel.created_at.desc())
    result = await session.execute(stmt)
    groups = result.scalars().all()

    responses: list[DocumentGroupResponse] = []
    for group in groups:
        count_result = await session.execute(
            select(func.count())
            .select_from(PassportSubmissionModel)
            .where(
                PassportSubmissionModel.group_id == group.id,
                PassportSubmissionModel.status.in_(_submitted_statuses()),
            )
        )
        group_count = int(count_result.scalar_one() or 0)
        responses.append(
            DocumentGroupResponse(
                group_id=group.id,
                group_name=group.name,
                group_status=group.status,
                destination=group.destination,
                travel_date=group.travel_date.isoformat() if group.travel_date else None,
                total_passengers=group_count,
            )
        )
    return responses


@router.get("/groups/{group_id}/{document_type}", response_model=DocumentBatchResponse)
async def get_document_review(
    group_id: uuid.UUID,
    document_type: str,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> DocumentBatchResponse:
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported document type")
    await _get_authorized_group(group_id, current_user=current_user, session=session)
    passengers = await _group_passengers(group_id, current_user=current_user, session=session)
    result = await session.execute(
        select(DocumentDistributionBatchModel)
        .where(
            DocumentDistributionBatchModel.group_id == group_id,
            DocumentDistributionBatchModel.document_type == document_type,
        )
        .order_by(DocumentDistributionBatchModel.created_at.desc())
        .limit(1)
    )
    batch = result.scalar_one_or_none()
    documents: list[DistributedDocumentModel] = []
    if batch:
        docs_result = await session.execute(
            select(DistributedDocumentModel)
            .where(DistributedDocumentModel.batch_id == batch.id)
            .order_by(DistributedDocumentModel.match_confidence.desc(), DistributedDocumentModel.created_at.asc())
        )
        documents = list(docs_result.scalars().all())
    return await _batch_response(group_id=group_id, document_type=document_type, passengers=passengers, batch=batch, documents=documents)


@router.post("/groups/{group_id}/{document_type}/verify", response_model=VerifyDocumentBatchResponse)
async def verify_documents(
    group_id: uuid.UUID,
    document_type: str,
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> VerifyDocumentBatchResponse:
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported document type")
    await _get_authorized_group(group_id, current_user=current_user, session=session)
    passengers = await _group_passengers(group_id, current_user=current_user, session=session)
    if not passengers:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This group has no passengers to match documents against")

    matcher = DocumentMatcher()
    verified: list[VerifiedDocumentResponse] = []
    for file in files:
        content = await file.read()
        filename = file.filename or "document.pdf"
        classification = matcher.classify(filename=filename, content=content, expected_type=document_type)
        matches = matcher.match_all(classification, passengers) if classification.accepted else []
        matched_passengers = [
            passenger
            for passenger in passengers
            if any(match.passenger_id == passenger.id for match in matches if match.passenger_id)
        ]
        primary_match = matches[0] if matches else None
        primary_passenger = matched_passengers[0] if matched_passengers else None
        verified.append(
            VerifiedDocumentResponse(
                filename=filename,
                detected_type=classification.detected_type,
                accepted=classification.accepted,
                reason=classification.reason,
                matched_passenger_id=primary_match.passenger_id if primary_match else None,
                matched_passenger_name=primary_passenger.client_name if primary_passenger else None,
                matched_passenger_ids=[match.passenger_id for match in matches if match.passenger_id],
                matched_passenger_names=[passenger.client_name for passenger in matched_passengers],
                match_confidence=primary_match.confidence if primary_match else 0.0,
                match_status=primary_match.status if primary_match else None,
                match_reason=(
                    f"Matched {len(matched_passengers)} passengers in one PDF"
                    if len(matched_passengers) > 1
                    else primary_match.reason if primary_match else None
                ),
            )
        )

    accepted_count = sum(1 for item in verified if item.accepted)
    return VerifyDocumentBatchResponse(
        group_id=group_id,
        document_type=document_type,
        total_count=len(verified),
        accepted_count=accepted_count,
        rejected_count=len(verified) - accepted_count,
        files=verified,
    )


@router.post("/groups/{group_id}/{document_type}/upload", response_model=DocumentBatchResponse, status_code=status.HTTP_201_CREATED)
async def upload_documents(
    group_id: uuid.UUID,
    document_type: str,
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> DocumentBatchResponse:
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported document type")
    group = await _get_authorized_group(group_id, current_user=current_user, session=session)
    passengers = await _group_passengers(group_id, current_user=current_user, session=session)
    if not passengers:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This group has no passengers to match documents against")

    file_payloads = [
        TravelDocumentFile(
            filename=file.filename or "document.pdf",
            content=await file.read(),
            content_type=file.content_type or "application/pdf",
        )
        for file in files
    ]
    ingestion = await TravelDocumentIngestionService(session).ingest(
        agency_id=group.agency_id,
        group_id=group.id,
        document_type=document_type,
        passengers=passengers,
        files=file_payloads,
        created_by_user_id=current_user.id,
        actor_email=current_user.email,
    )
    await session.commit()
    return await _batch_response(
        group_id=group_id,
        document_type=document_type,
        passengers=passengers,
        batch=ingestion.batch,
        documents=ingestion.documents,
        rejected_documents=[
            RejectedDocumentResponse(
                filename=item.filename,
                detected_type=item.detected_type,
                reason=item.reason,
            )
            for item in ingestion.rejected
        ],
    )


@router.post(
    "/groups/{group_id}/{document_type}/passengers/{passenger_id}/reupload",
    response_model=DocumentBatchResponse,
    status_code=status.HTTP_201_CREATED,
)
async def reupload_passenger_document(
    group_id: uuid.UUID,
    document_type: str,
    passenger_id: uuid.UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> DocumentBatchResponse:
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported document type")
    group = await _get_authorized_group(group_id, current_user=current_user, session=session)
    passengers = await _group_passengers(group_id, current_user=current_user, session=session)
    passenger = next((item for item in passengers if item.id == passenger_id), None)
    if not passenger:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Passenger was not found in this group")

    content = await file.read()
    filename = file.filename or "document.pdf"
    matcher = DocumentMatcher()
    classification = matcher.classify(filename=filename, content=content, expected_type=document_type)
    if not classification.accepted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{filename}: {classification.reason}",
        )

    result = await session.execute(
        select(DocumentDistributionBatchModel)
        .where(
            DocumentDistributionBatchModel.group_id == group_id,
            DocumentDistributionBatchModel.document_type == document_type,
        )
        .order_by(DocumentDistributionBatchModel.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    batch = result.scalar_one_or_none()
    now = datetime.now(tz=UTC)
    if not batch:
        batch = DocumentDistributionBatchModel(
            id=uuid.uuid4(),
            agency_id=group.agency_id,
            group_id=group.id,
            document_type=document_type,
            status="draft",
            uploaded_count=0,
            rejected_count=0,
            matched_count=0,
            created_by_user_id=current_user.id,
            created_at=now,
            updated_at=now,
        )
        session.add(batch)
        await session.flush()

    old_docs_result = await session.execute(
        select(DistributedDocumentModel).where(
            DistributedDocumentModel.batch_id == batch.id,
            DistributedDocumentModel.passenger_id == passenger_id,
            DistributedDocumentModel.document_type == document_type,
        )
    )
    for old_document in old_docs_result.scalars().all():
        old_document.passenger_id = None
        old_document.match_status = "duplicate_document"
        old_document.match_reason = "Replaced by a reuploaded document"
        old_document.updated_at = now

    match = matcher.match(classification, [passenger])
    document_id = uuid.uuid4()
    key = f"document-distribution/{group.id}/{batch.id}/{document_id}-{_safe_filename(filename)}"
    await MinioStorageRepository().upload_file(content, key, file.content_type or "application/pdf")
    model = DistributedDocumentModel(
        id=document_id,
        batch_id=batch.id,
        agency_id=group.agency_id,
        group_id=group.id,
        passenger_id=passenger_id,
        document_type=document_type,
        original_filename=filename,
        storage_key=key,
        content_type=file.content_type or "application/pdf",
        detected_type=classification.detected_type,
        match_status="matched" if match.passenger_id == passenger_id and match.confidence >= 0.82 else "needs_review",
        match_confidence=match.confidence if match.passenger_id == passenger_id else 0.5,
        match_reason=match.reason if match.passenger_id == passenger_id else "Manually reuploaded for this passenger; verify details",
        extracted_name=classification.extracted_name,
        extracted_passport_number=classification.extracted_passport_number,
        extracted_reference=classification.extracted_reference,
        created_at=now,
        updated_at=now,
    )
    session.add(model)

    docs_result = await session.execute(select(DistributedDocumentModel).where(DistributedDocumentModel.batch_id == batch.id))
    documents = list(docs_result.scalars().all())
    batch.status = "draft"
    batch.saved_at = None
    batch.uploaded_count = len(documents)
    batch.matched_count = sum(1 for document in documents if document.match_status == "matched")
    batch.updated_at = now
    await AuditLogRepository(session).record(
        action="document_distribution_reuploaded",
        entity_type="document_distribution_batch",
        entity_id=str(batch.id),
        agency_id=group.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "group_id": str(group_id),
            "passenger_id": str(passenger_id),
            "document_type": document_type,
            "filename": filename,
        },
    )
    await session.commit()
    return await _batch_response(group_id=group_id, document_type=document_type, passengers=passengers, batch=batch, documents=documents)


@router.post("/groups/{group_id}/{document_type}/documents/delete", response_model=DocumentBatchResponse)
async def delete_distribution_documents(
    group_id: uuid.UUID,
    document_type: str,
    payload: DeleteDistributionDocumentsRequest,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> DocumentBatchResponse:
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported document type")
    group = await _get_authorized_group(group_id, current_user=current_user, session=session)
    passengers = await _group_passengers(group_id, current_user=current_user, session=session)
    document_ids = list(dict.fromkeys(payload.document_ids))
    if not document_ids:
        return await _batch_response(group_id=group_id, document_type=document_type, passengers=passengers, batch=None, documents=[])

    result = await session.execute(
        select(DocumentDistributionBatchModel)
        .where(
            DocumentDistributionBatchModel.group_id == group_id,
            DocumentDistributionBatchModel.document_type == document_type,
        )
        .order_by(DocumentDistributionBatchModel.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document batch was not found")

    docs_result = await session.execute(
        select(DistributedDocumentModel).where(
            DistributedDocumentModel.id.in_(document_ids),
            DistributedDocumentModel.batch_id == batch.id,
            DistributedDocumentModel.group_id == group_id,
            DistributedDocumentModel.agency_id == group.agency_id,
            DistributedDocumentModel.document_type == document_type,
        )
    )
    documents_to_delete = list(docs_result.scalars().all())
    if not documents_to_delete:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No matching documents were found")

    active_delivery_result = await session.execute(
        select(DocumentWhatsAppDeliveryModel.id)
        .where(
            DocumentWhatsAppDeliveryModel.distributed_document_id.in_(
                [document.id for document in documents_to_delete]
            ),
            DocumentWhatsAppDeliveryModel.status.in_(
                DOCUMENT_DELIVERY_STORAGE_REQUIRED_STATUSES
            ),
        )
        .with_for_update()
        .limit(1)
    )
    if active_delivery_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A selected document is currently being sent through WhatsApp. "
                "Wait for delivery processing to finish before deleting it."
            ),
        )

    candidate_storage_keys = list({document.storage_key for document in documents_to_delete})
    remaining_key_result = await session.execute(
        select(DistributedDocumentModel.storage_key).where(
            DistributedDocumentModel.storage_key.in_(candidate_storage_keys),
            DistributedDocumentModel.id.notin_([document.id for document in documents_to_delete]),
        )
    )
    still_used_storage_keys = set(remaining_key_result.scalars().all())
    delete_storage_keys = [key for key in candidate_storage_keys if key not in still_used_storage_keys]
    await MinioStorageRepository().delete_files(delete_storage_keys)
    for document in documents_to_delete:
        await session.delete(document)
    await session.flush()

    remaining_result = await session.execute(
        select(DistributedDocumentModel)
        .where(DistributedDocumentModel.batch_id == batch.id)
        .order_by(DistributedDocumentModel.match_confidence.desc(), DistributedDocumentModel.created_at.asc())
    )
    remaining_documents = list(remaining_result.scalars().all())
    now = datetime.now(tz=UTC)
    batch.status = "draft"
    batch.saved_at = None
    batch.uploaded_count = len(remaining_documents)
    batch.matched_count = sum(1 for document in remaining_documents if document.match_status == "matched")
    batch.updated_at = now
    await AuditLogRepository(session).record(
        action="document_distribution_deleted",
        entity_type="document_distribution_batch",
        entity_id=str(batch.id),
        agency_id=group.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "group_id": str(group_id),
            "document_type": document_type,
            "deleted_count": len(documents_to_delete),
            "deleted_storage_objects": len(delete_storage_keys),
        },
    )
    await session.commit()
    return await _batch_response(
        group_id=group_id,
        document_type=document_type,
        passengers=passengers,
        batch=batch,
        documents=remaining_documents,
    )


@router.post("/batches/{batch_id}/save", response_model=SaveDocumentBatchResponse)
async def save_batch(
    batch_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> SaveDocumentBatchResponse:
    result = await session.execute(select(DocumentDistributionBatchModel).where(DocumentDistributionBatchModel.id == batch_id))
    batch = result.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document batch was not found")
    await _get_authorized_group(batch.group_id, current_user=current_user, session=session)
    now = datetime.now(tz=UTC)
    batch.status = "saved"
    batch.saved_at = now
    batch.updated_at = now
    await AuditLogRepository(session).record(
        action="document_distribution_saved",
        entity_type="document_distribution_batch",
        entity_id=str(batch.id),
        agency_id=batch.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={"group_id": str(batch.group_id), "document_type": batch.document_type},
    )
    await session.commit()
    return SaveDocumentBatchResponse(batch_id=batch.id, status=batch.status, saved_at=now)


@router.get(
    "/groups/{group_id}/{document_type}/whatsapp-preview",
    response_model=DocumentDeliveryPreviewResponse,
)
async def preview_document_whatsapp_broadcast(
    group_id: uuid.UUID,
    document_type: str,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> DocumentDeliveryPreviewResponse:
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported document type",
        )
    group = await _get_authorized_group(
        group_id,
        current_user=current_user,
        session=session,
    )
    batch = await _latest_document_batch(
        session,
        group_id=group_id,
        document_type=document_type,
    )
    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document batch was not found",
        )
    passengers = await _group_passengers(
        group_id,
        current_user=current_user,
        session=session,
    )
    return await _build_document_delivery_preview(
        session,
        group=group,
        batch=batch,
        passengers=passengers,
    )


@router.post(
    "/batches/{batch_id}/whatsapp-send",
    response_model=SendDocumentBroadcastResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def send_document_whatsapp_broadcast(
    batch_id: uuid.UUID,
    payload: SendDocumentBroadcastRequest,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> SendDocumentBroadcastResponse:
    message_content_1 = payload.message_content_1.strip()
    message_content_2 = payload.message_content_2.strip()
    if not message_content_1 or not message_content_2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Both editable document message sections are required",
        )
    batch_result = await session.execute(
        select(DocumentDistributionBatchModel)
        .where(DocumentDistributionBatchModel.id == batch_id)
        .with_for_update()
    )
    batch = batch_result.scalar_one_or_none()
    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document batch was not found",
        )
    group = await _get_authorized_group(
        batch.group_id,
        current_user=current_user,
        session=session,
    )
    passengers = await _group_passengers(
        batch.group_id,
        current_user=current_user,
        session=session,
    )
    preview = await _build_document_delivery_preview(
        session,
        group=group,
        batch=batch,
        passengers=passengers,
    )
    if not preview.can_send:
        error_status = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if not preview.template_configured
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(
            status_code=error_status,
            detail=preview.configuration_error or "Documents are not ready to send",
        )

    requested_ids = (
        set(payload.document_ids)
        if payload.document_ids is not None
        else {
            row.document_id
            for row in preview.recipients
            if row.document_id and row.eligible
        }
    )
    eligible_rows = [
        row
        for row in preview.recipients
        if row.document_id in requested_ids and row.eligible
    ]
    if not eligible_rows:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Select at least one new or safely retryable document",
        )

    send_batch_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    template_name = preview.template_name or ""
    queued_count = 0
    for row in eligible_rows:
        if not (
            row.document_id
            and row.recipient_id
            and row.broadcast_group_id
            and row.phone_number
            and row.document_filename
        ):
            continue
        delivery: DocumentWhatsAppDeliveryModel | None = None
        if row.delivery_id:
            delivery_result = await session.execute(
                select(DocumentWhatsAppDeliveryModel)
                .where(DocumentWhatsAppDeliveryModel.id == row.delivery_id)
                .with_for_update()
            )
            delivery = delivery_result.scalar_one_or_none()
        if delivery:
            if delivery.status != "failed":
                continue
            delivery.send_batch_id = send_batch_id
            delivery.broadcast_group_id = row.broadcast_group_id
            delivery.recipient_id = row.recipient_id
            delivery.phone_number = row.phone_number
            delivery.normalized_phone_number = row.phone_number
            delivery.template_name = template_name
            delivery.template_parameter_values = [
                message_content_1,
                message_content_2,
            ]
            delivery.status = "queued"
            delivery.status_updated_at = now
            delivery.provider_status_at = None
            delivery.provider_message_id = None
            delivery.provider_media_id = None
            delivery.error_message = None
            delivery.updated_at = now
        else:
            delivery = DocumentWhatsAppDeliveryModel(
                id=uuid.uuid4(),
                agency_id=batch.agency_id,
                group_id=batch.group_id,
                document_batch_id=batch.id,
                distributed_document_id=row.document_id,
                passenger_id=row.passenger_id,
                broadcast_group_id=row.broadcast_group_id,
                recipient_id=row.recipient_id,
                send_batch_id=send_batch_id,
                document_type=batch.document_type,
                document_filename=row.document_filename,
                passenger_name=row.passenger_name,
                passport_number=row.passport_number,
                phone_number=row.phone_number,
                normalized_phone_number=row.phone_number,
                template_name=template_name,
                template_parameter_values=[
                    message_content_1,
                    message_content_2,
                ],
                status="queued",
                attempt_count=0,
                status_updated_at=now,
                created_by_user_id=current_user.id,
                created_at=now,
                updated_at=now,
            )
            session.add(delivery)
        queued_count += 1

    if not queued_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The selected documents were already claimed by another send",
        )
    await AuditLogRepository(session).record(
        action="document_whatsapp_broadcast_queued",
        entity_type="document_distribution_batch",
        entity_id=str(batch.id),
        agency_id=batch.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "group_id": str(batch.group_id),
            "document_type": batch.document_type,
            "send_batch_id": str(send_batch_id),
            "queued_count": queued_count,
            "message_content_lengths": [
                len(message_content_1),
                len(message_content_2),
            ],
        },
    )
    await session.commit()

    from app.infrastructure.whatsapp.tasks import (
        process_document_whatsapp_broadcast,
    )

    try:
        process_document_whatsapp_broadcast.apply_async(
            kwargs={"send_batch_id": str(send_batch_id)},
            queue="whatsapp",
        )
    except Exception as exc:
        failed_result = await session.execute(
            select(DocumentWhatsAppDeliveryModel).where(
                DocumentWhatsAppDeliveryModel.send_batch_id == send_batch_id,
                DocumentWhatsAppDeliveryModel.status == "queued",
            )
        )
        failure_time = datetime.now(tz=UTC)
        for delivery in failed_result.scalars().all():
            delivery.status = "failed"
            delivery.status_updated_at = failure_time
            delivery.updated_at = failure_time
            delivery.error_message = "The WhatsApp worker queue is temporarily unavailable"
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The WhatsApp worker queue is temporarily unavailable",
        ) from exc

    attempted_count = len(requested_ids) if payload.document_ids is not None else len(preview.recipients)
    return SendDocumentBroadcastResponse(
        send_batch_id=send_batch_id,
        queued_count=queued_count,
        skipped_count=max(0, attempted_count - queued_count),
        message=(
            f"Queued {queued_count} document{'' if queued_count == 1 else 's'} "
            "for individual WhatsApp delivery."
        ),
    )


@router.get(
    "/groups/{group_id}/whatsapp-deliveries/tracking",
    response_model=DocumentDeliveryTrackingResponse,
)
async def get_document_delivery_tracking(
    group_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> DocumentDeliveryTrackingResponse:
    group = await _get_authorized_group(
        group_id,
        current_user=current_user,
        session=session,
    )
    count_result = await session.execute(
        select(
            DocumentWhatsAppDeliveryModel.status,
            func.count(DocumentWhatsAppDeliveryModel.id),
        )
        .where(
            DocumentWhatsAppDeliveryModel.group_id == group.id,
            DocumentWhatsAppDeliveryModel.agency_id == group.agency_id,
        )
        .group_by(DocumentWhatsAppDeliveryModel.status)
    )
    status_counts = {
        delivery_status: int(count)
        for delivery_status, count in count_result.all()
    }
    result = await session.execute(
        select(DocumentWhatsAppDeliveryModel)
        .where(
            DocumentWhatsAppDeliveryModel.group_id == group.id,
            DocumentWhatsAppDeliveryModel.agency_id == group.agency_id,
        )
        .order_by(DocumentWhatsAppDeliveryModel.status_updated_at.desc())
        .limit(100)
    )
    deliveries = list(result.scalars().all())
    counts = DocumentDeliveryTrackingCounts(
        total=sum(status_counts.values()),
        queued=status_counts.get("queued", 0) + status_counts.get("processing", 0),
        sent=status_counts.get("submitted", 0) + status_counts.get("sent", 0),
        delivered=status_counts.get("delivered", 0),
        read=status_counts.get("read", 0),
        failed=status_counts.get("failed", 0),
        delivery_unknown=status_counts.get("delivery_unknown", 0),
    )
    return DocumentDeliveryTrackingResponse(
        group_id=group.id,
        counts=counts,
        deliveries=[
            DocumentDeliveryTrackingRow(
                delivery_id=delivery.id,
                passenger_id=delivery.passenger_id,
                passenger_name=delivery.passenger_name,
                passport_number=delivery.passport_number,
                document_type=delivery.document_type,
                document_filename=delivery.document_filename,
                phone_number=delivery.phone_number,
                status=delivery.status,
                error_message=delivery.error_message,
                status_updated_at=delivery.status_updated_at,
            )
            for delivery in deliveries
        ],
    )
