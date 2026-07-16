"""Document distribution routes."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import PassportSubmission, User, UserRole
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.models import (
    ClientGroupModel,
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    PassportSubmissionModel,
)
from app.infrastructure.database.session import get_db_session
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
    DocumentGroupResponse,
    DocumentPassengerReviewRow,
    RejectedDocumentResponse,
    SaveDocumentBatchResponse,
    VerifiedDocumentResponse,
    VerifyDocumentBatchResponse,
)
from app.presentation.dependencies.auth import get_current_active_user

router = APIRouter()


def _owner_scope_for(user: User) -> uuid.UUID | None:
    return user.id if user.role == UserRole.AGENCY_STAFF else None


def _submitted_statuses() -> tuple[str, str]:
    return ("client_submitted", "confirmed")


def _passport_number(passenger: PassportSubmission) -> str | None:
    fields = passenger.confirmed_fields or passenger.extracted_fields or {}
    value = fields.get("passport_number")
    return str(value).strip() if value else None


def _safe_filename(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())[:120]
    return name or "document.pdf"


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

    matcher = DocumentMatcher()
    file_payloads: list[tuple[UploadFile, bytes]] = []
    rejected: list[RejectedDocumentResponse] = []
    classified = []
    for file in files:
        content = await file.read()
        filename = file.filename or "document.pdf"
        classification = matcher.classify(filename=filename, content=content, expected_type=document_type)
        if not classification.accepted:
            rejected.append(
                RejectedDocumentResponse(filename=filename, detected_type=classification.detected_type, reason=classification.reason)
            )
            continue
        file_payloads.append((file, content))
        classified.append(classification)

    now = datetime.now(tz=UTC)
    batch = DocumentDistributionBatchModel(
        id=uuid.uuid4(),
        agency_id=group.agency_id,
        group_id=group.id,
        document_type=document_type,
        status="draft",
        uploaded_count=0,
        rejected_count=len(rejected),
        matched_count=0,
        created_by_user_id=current_user.id,
        created_at=now,
        updated_at=now,
    )
    session.add(batch)
    await session.flush()

    document_matches = [matcher.match_all(document, passengers) for document in classified]
    flat_matches = [match for matches in document_matches for match in matches]
    deduped_flat_matches = matcher.mark_duplicates(flat_matches)
    deduped_document_matches: list[list] = []
    cursor = 0
    for matches in document_matches:
        deduped_document_matches.append(deduped_flat_matches[cursor: cursor + len(matches)])
        cursor += len(matches)

    storage = MinioStorageRepository()
    documents: list[DistributedDocumentModel] = []
    for (file, content), document, matches in zip(file_payloads, classified, deduped_document_matches):
        storage_document_id = uuid.uuid4()
        key = f"document-distribution/{group.id}/{batch.id}/{storage_document_id}-{_safe_filename(file.filename or 'document.pdf')}"
        await storage.upload_file(content, key, file.content_type or "application/pdf")
        for match in matches:
            model = DistributedDocumentModel(
                id=uuid.uuid4(),
                batch_id=batch.id,
                agency_id=group.agency_id,
                group_id=group.id,
                passenger_id=match.passenger_id,
                document_type=document_type,
                original_filename=file.filename or "document.pdf",
                storage_key=key,
                content_type=file.content_type or "application/pdf",
                detected_type=document.detected_type,
                match_status=match.status,
                match_confidence=match.confidence,
                match_reason=(
                    f"Shared PDF matched {len(matches)} passenger{'' if len(matches) == 1 else 's'}"
                    if len(matches) > 1 and match.status == "matched"
                    else match.reason
                ),
                extracted_name=document.extracted_name,
                extracted_passport_number=document.extracted_passport_number,
                extracted_reference=document.extracted_reference,
                created_at=now,
                updated_at=now,
            )
            documents.append(model)
            session.add(model)

    batch.uploaded_count = len(documents)
    batch.matched_count = sum(1 for document in documents if document.match_status == "matched")
    await AuditLogRepository(session).record(
        action="document_distribution_uploaded",
        entity_type="client_group",
        entity_id=str(group_id),
        agency_id=group.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "document_type": document_type,
            "uploaded_count": batch.uploaded_count,
            "rejected_count": batch.rejected_count,
            "matched_count": batch.matched_count,
        },
    )
    await session.commit()
    return await _batch_response(
        group_id=group_id,
        document_type=document_type,
        passengers=passengers,
        batch=batch,
        documents=documents,
        rejected_documents=rejected,
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
