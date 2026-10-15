"""Explicit staff-selected passenger uploads without automatic document matching."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.passenger_change_propagation import propagate_mobile_passenger_change
from app.domain.entities.entities import User
from app.domain.value_objects.travel_document_taxonomy import DOCUMENT_TYPES
from app.infrastructure.database.models import (
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    UserModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.documents.distribution_capacity import DocumentDistributionCapacityError
from app.infrastructure.documents.distribution_ingestion import (
    TravelDocumentFile,
    TravelDocumentIngestionService,
)
from app.infrastructure.documents.document_approval_provenance import (
    MANUAL_DOCUMENT_TYPE_APPROVAL_PREFIX,
)
from app.infrastructure.documents.document_matcher import ClassifiedDocument
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.security.upload_security import UploadSecurityContext
from app.presentation.api.v1.document_chunk_uploads import (
    acquire_document_upload_scope_advisory_lock,
)
from app.presentation.api.v1.document_uploads import read_bounded_document_uploads
from app.presentation.api.v1.routes.document_distribution_manual_replacement import (
    supersede_passenger_documents,
)
from app.presentation.api.v1.routes.document_distribution_queries import (
    _all_group_documents,
    _enforce_group_document_assignment_capacity,
)
from app.presentation.api.v1.routes.document_distribution_replacements import (
    ReplacementDocumentVersion,
)
from app.presentation.api.v1.routes.document_distribution_responses import _batch_response
from app.presentation.api.v1.routes.document_distribution_scope import (
    _get_authorized_group,
    _group_passengers,
    _lock_active_document_scope,
    _lock_document_passenger_roster,
)
from app.presentation.api.v1.routes.document_distribution_shared import logger
from app.presentation.api.v1.routes.document_distribution_storage import (
    _cleanup_distribution_storage_keys,
)
from app.presentation.api.v1.schemas.document_distribution_schemas import DocumentBatchResponse
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


@router.post(
    "/groups/{group_id}/{document_type}/passengers/{passenger_id}/manual-upload",
    response_model=DocumentBatchResponse, status_code=201,
    dependencies=[Depends(require_cookie_csrf)],
)
async def manually_upload_passenger_document(
    group_id: uuid.UUID, document_type: str, passenger_id: uuid.UUID,
    file: UploadFile = File(...), mode: Literal["add", "replace"] = Form("add"),
    replacement_documents: str = Form("[]", max_length=10000),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> DocumentBatchResponse:
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported document type")
    try:
        versions = TypeAdapter(list[ReplacementDocumentVersion]).validate_json(replacement_documents)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail="Invalid replacement selection") from exc
    if (mode == "replace" and len(versions) != 1) or (mode == "add" and versions):
        raise HTTPException(status_code=400, detail="Select exactly one saved PDF to replace")
    group = await _get_authorized_group(group_id, current_user=current_user, session=session)
    agency_id = group.agency_id
    passengers = await _group_passengers(group_id, current_user=current_user, session=session)
    if not any(passenger.id == passenger_id for passenger in passengers):
        raise HTTPException(status_code=404, detail="Passenger was not found in this group")
    await session.rollback()
    # Bounded PDF validation and malware scanning remain mandatory. No OCR,
    # classification, extraction or name/passport matching is performed here.
    upload = (await read_bounded_document_uploads([file], security_context=UploadSecurityContext(
        ingestion_flow="document_distribution_manual_upload", agency_id=agency_id, user_id=current_user.id,
    )))[0]
    classification = ClassifiedDocument(
        original_filename=upload.filename, detected_type="unknown", accepted=True,
        reason=MANUAL_DOCUMENT_TYPE_APPROVAL_PREFIX + "Passenger explicitly selected by staff",
        text="", extracted_name=None, extracted_passport_number=None, extracted_reference=None,
    )
    actor: UserModel | User = current_user
    released_passenger_ids: tuple[uuid.UUID, ...] = ()

    async def reauthorize() -> tuple[uuid.UUID, str | None]:
        nonlocal actor, passengers
        actor, _ = await _lock_active_document_scope(
            session, current_user=current_user, group_id=group_id, agency_id=agency_id,
        )
        await _lock_document_passenger_roster(session, agency_id=agency_id, group_id=group_id)
        passengers = await _group_passengers(group_id, current_user=current_user, session=session)
        if not any(passenger.id == passenger_id for passenger in passengers):
            raise HTTPException(status_code=409, detail="The passenger is no longer available in this group")
        await acquire_document_upload_scope_advisory_lock(
            session, agency_id=agency_id, group_id=group_id, document_type=document_type,
        )
        batches = list((await session.scalars(select(DocumentDistributionBatchModel).where(
            DocumentDistributionBatchModel.agency_id == agency_id,
            DocumentDistributionBatchModel.group_id == group_id,
            DocumentDistributionBatchModel.document_type == document_type,
        ).order_by(DocumentDistributionBatchModel.id).with_for_update())).all())
        if any(batch.status == "processing" for batch in batches):
            raise HTTPException(status_code=409, detail="Finish or discard the current upload first")
        return actor.id, actor.email

    async def replace(new_documents: list[DistributedDocumentModel]) -> None:
        nonlocal released_passenger_ids
        if versions:
            released_passenger_ids = await supersede_passenger_documents(session, agency_id=agency_id, group_id=group_id,
                document_type=document_type, passenger_id=passenger_id, versions=versions,
                replacement_id=new_documents[0].id, actor=actor)

    async def capacity(incoming_rows: int) -> None:
        await _enforce_group_document_assignment_capacity(session, agency_id=agency_id,
            group_id=group_id, document_type=document_type, incoming_rows=incoming_rows)

    ingestion = None
    try:
        ingestion = await TravelDocumentIngestionService(session).ingest(
            agency_id=agency_id, group_id=group_id, document_type=document_type,
            passengers=passengers, files=[TravelDocumentFile(upload.filename, upload.content, upload.content_type)],
            created_by_user_id=current_user.id, actor_email=current_user.email,
            forced_passenger_id=passenger_id, preclassified_documents=[classification],
            audit_source="dashboard_explicit_passenger_upload", isolate_pdf_parsing=True,
            before_persistence=reauthorize, before_persistence_documents=replace,
            before_persistence_capacity=capacity,
        )
        # Save this new batch only; unrelated drafts never become published as a
        # side effect of a single-passenger upload.
        ingestion.batch.status = "saved"
        ingestion.batch.saved_at = datetime.now(UTC)
        await AuditLogRepository(session).record(
            action="document_distribution_manual_passenger_upload", entity_type="distributed_document",
            entity_id=str(ingestion.documents[0].id), agency_id=agency_id,
            user_id=actor.id, actor_email=actor.email,
            metadata={"group_id": str(group_id), "passenger_id": str(passenger_id),
                "document_type": document_type, "mode": mode, "matching": "explicit_staff_selection"},
        )
        if released_passenger_ids:
            await propagate_mobile_passenger_change(session, agency_id=agency_id, group_id=group_id,
                passenger_submission_ids=released_passenger_ids, actor_user_id=actor.id,
                operation="delete", change_kind="documents", reconcile_identities=False)
        await session.flush()
    except BaseException as exc:
        await session.rollback()
        if ingestion is not None:
            await _cleanup_distribution_storage_keys(list(ingestion.created_storage_keys),
                agency_id=agency_id, group_id=group_id, document_type=document_type)
        if isinstance(exc, DocumentDistributionCapacityError):
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        raise
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        logger.warning("document_distribution_commit_outcome_ambiguous", group_id=str(group_id),
            document_type=document_type, object_count=len(ingestion.created_storage_keys))
        raise
    documents = await _all_group_documents(session, group_id=group_id,
        agency_id=agency_id, document_type=document_type)
    return await _batch_response(session=session, group_id=group_id, agency_id=agency_id,
        document_type=document_type, passengers=passengers, batch=ingestion.batch, documents=documents)
