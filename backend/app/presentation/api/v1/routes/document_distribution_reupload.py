"""Document distribution: reupload."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.domain.value_objects.travel_document_taxonomy import DOCUMENT_TYPES
from app.infrastructure.database.session import get_db_session
from app.infrastructure.documents.distribution_capacity import DocumentDistributionCapacityError
from app.infrastructure.documents.distribution_ingestion import (
    TravelDocumentFile,
    TravelDocumentIngestionService,
)
from app.infrastructure.documents.document_matcher import (
    DocumentMatcher,
    DocumentParserUnavailableError,
    classify_documents_bounded,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.security.upload_security import UploadSecurityContext
from app.presentation.api.v1.document_chunk_uploads import (
    acquire_document_upload_scope_advisory_lock,
)
from app.presentation.api.v1.document_uploads import read_bounded_document_uploads
from app.presentation.api.v1.routes.document_distribution_matching import (
    _read_linked_document_match_source,
)
from app.presentation.api.v1.routes.document_distribution_queries import (
    _all_group_documents,
    _enforce_group_document_assignment_capacity,
)
from app.presentation.api.v1.routes.document_distribution_responses import _batch_response
from app.presentation.api.v1.routes.document_distribution_scope import (
    _get_authorized_group,
    _group_passengers,
    _lock_and_validate_document_match_scope,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    _document_match_roster_snapshot,
    logger,
)
from app.presentation.api.v1.routes.document_distribution_storage import (
    _cleanup_distribution_storage_keys,
)
from app.presentation.api.v1.schemas.document_distribution_schemas import DocumentBatchResponse
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


@router.post(
    "/groups/{group_id}/{document_type}/passengers/{passenger_id}/reupload",
    response_model=DocumentBatchResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_cookie_csrf)],
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
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported document type"
        )
    authorized_group = await _get_authorized_group(
        group_id,
        current_user=current_user,
        session=session,
    )
    initial_passengers = await _group_passengers(
        group_id,
        current_user=current_user,
        session=session,
    )
    if all(item.id != passenger_id for item in initial_passengers):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Passenger was not found in this group"
        )
    await session.rollback()
    upload = (
        await read_bounded_document_uploads(
            [file],
            security_context=UploadSecurityContext(
                ingestion_flow="document_distribution_reupload",
                agency_id=authorized_group.agency_id,
                user_id=current_user.id,
            ),
        )
    )[0]
    content = upload.content
    filename = upload.filename
    matcher = DocumentMatcher()
    try:
        classification = (
            await asyncio.to_thread(
                classify_documents_bounded,
                matcher,
                [(filename, content, document_type)],
                isolate_pdf_parsing=True,
            )
        )[0]
    except DocumentParserUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
            headers={"Retry-After": "1"},
        ) from exc
    if not classification.accepted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{filename}: {classification.reason}",
        )
    group = await _get_authorized_group(group_id, current_user=current_user, session=session)
    passengers = await _group_passengers(group_id, current_user=current_user, session=session)
    if all(item.id != passenger_id for item in passengers):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The selected passenger changed while the PDF was being prepared",
        )
    agency_id = group.agency_id
    roster_snapshot = _document_match_roster_snapshot(passengers)
    linked_source = await _read_linked_document_match_source(
        session,
        group=group,
        lock=False,
    )
    await session.rollback()

    async def reauthorize_before_persistence() -> tuple[uuid.UUID | None, str | None]:
        actor, _ = await _lock_and_validate_document_match_scope(
            session,
            current_user=current_user,
            group_id=group_id,
            agency_id=agency_id,
            matcher=matcher,
            expected_roster_snapshot=roster_snapshot,
            expected_source_snapshot=linked_source.snapshot,
            expected_supplemental_identifiers=None,
            required_passenger_id=passenger_id,
        )
        await acquire_document_upload_scope_advisory_lock(
            session,
            agency_id=agency_id,
            group_id=group_id,
            document_type=document_type,
        )
        return actor.id, actor.email

    async def enforce_capacity_before_persistence(incoming_rows: int) -> None:
        await _enforce_group_document_assignment_capacity(
            session,
            group_id=group_id,
            agency_id=agency_id,
            document_type=document_type,
            incoming_rows=incoming_rows,
        )

    ingestion = None
    try:
        ingestion = await TravelDocumentIngestionService(session).ingest(
            agency_id=agency_id,
            group_id=group_id,
            document_type=document_type,
            passengers=passengers,
            files=[
                TravelDocumentFile(
                    filename=filename,
                    content=content,
                    content_type=upload.content_type,
                )
            ],
            created_by_user_id=current_user.id,
            actor_email=current_user.email,
            forced_passenger_id=passenger_id,
            audit_source="dashboard_passenger_add",
            isolate_pdf_parsing=True,
            before_persistence=reauthorize_before_persistence,
            before_persistence_capacity=enforce_capacity_before_persistence,
        )
        await AuditLogRepository(session).record(
            action="document_distribution_passenger_document_added",
            entity_type="document_distribution_batch",
            entity_id=str(ingestion.batch.id),
            agency_id=agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            metadata={
                "group_id": str(group_id),
                "passenger_id": str(passenger_id),
                "document_type": document_type,
                "filename": filename,
            },
        )
    except DocumentDistributionCapacityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=413,
            detail=str(exc),
        ) from exc
    except Exception:
        await session.rollback()
        if ingestion is not None:
            await _cleanup_distribution_storage_keys(
                list(ingestion.created_storage_keys),
                agency_id=agency_id,
                group_id=group_id,
                document_type=document_type,
            )
        raise
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        logger.warning(
            "document_distribution_commit_outcome_ambiguous",
            group_id=str(group_id),
            document_type=document_type,
            object_count=len(ingestion.created_storage_keys),
        )
        raise
    documents = await _all_group_documents(
        session,
        group_id=group_id,
        agency_id=agency_id,
        document_type=document_type,
    )
    return await _batch_response(
        session=session,
        group_id=group_id,
        agency_id=agency_id,
        document_type=document_type,
        passengers=passengers,
        batch=ingestion.batch,
        documents=documents,
    )
