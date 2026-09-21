"""Explicit human type approval for previously safety-checked unknown PDFs."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import StorageError
from app.domain.value_objects.travel_document_taxonomy import (
    DOCUMENT_TYPES,
    classification_document_type,
)
from app.infrastructure.database.models import DocumentDistributionBatchModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.documents.distribution_ingestion import automatic_passenger_matches
from app.infrastructure.documents.document_matcher import DocumentMatcher, MatchResult
from app.infrastructure.documents.manual_type_approval import (
    MANUAL_APPROVAL_TOKEN_LIMIT,
    ManualDocumentApprovalCipher,
    ManualDocumentApprovalError,
)
from app.infrastructure.documents.verification_staging import (
    VerificationStagingInput,
    stage_verified_documents,
    verification_scope_fingerprints,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.security.upload_security import UploadSecurityContext
from app.presentation.api.v1.document_uploads import read_bounded_document_uploads
from app.presentation.api.v1.routes.document_distribution_matching import (
    _linked_document_match_identifiers,
    _read_linked_document_match_source,
)
from app.presentation.api.v1.routes.document_distribution_scope import (
    _get_authorized_group,
    _group_passengers,
    _lock_and_validate_document_match_scope,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    _document_match_roster_snapshot,
)
from app.presentation.api.v1.schemas.document_distribution_schemas import VerifiedDocumentResponse
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


async def _require_unstarted_upload(session: AsyncSession, upload_id: uuid.UUID) -> None:
    existing = await session.scalar(
        select(DocumentDistributionBatchModel.id).where(
            DocumentDistributionBatchModel.id == upload_id
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="This upload has already started. Check the remaining PDFs in a new upload first.",
        )


@router.post(
    "/groups/{group_id}/{document_type}/manual-verify",
    response_model=VerifiedDocumentResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def manually_verify_document(
    group_id: uuid.UUID,
    document_type: str,
    file: Annotated[UploadFile, File()],
    approval_token: Annotated[str, Form(min_length=1, max_length=MANUAL_APPROVAL_TOKEN_LIMIT)],
    upload_id: Annotated[uuid.UUID, Form()],
    chunk_id: Annotated[uuid.UUID, Form()],
    confirmed: Annotated[bool, Form()],
    target_upload_id: Annotated[uuid.UUID | None, Form()] = None,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> VerifiedDocumentResponse:
    if document_type not in DOCUMENT_TYPES or classification_document_type(document_type) not in {
        "visa",
        "flight_ticket",
    }:
        raise HTTPException(status_code=400, detail="Unsupported document type for manual approval")
    if not confirmed:
        raise HTTPException(
            status_code=400,
            detail="Confirm the PDF's document type after reviewing it",
        )
    group = await _get_authorized_group(group_id, current_user=current_user, session=session)
    agency_id = group.agency_id
    staging_upload_id = target_upload_id or upload_id
    await _require_unstarted_upload(session, staging_upload_id)
    await session.rollback()
    uploads = await read_bounded_document_uploads(
        [file],
        security_context=UploadSecurityContext(
            ingestion_flow="document_distribution_manual_type_approval",
            agency_id=agency_id,
            user_id=current_user.id,
        ),
    )
    upload = uploads[0]
    try:
        classification = ManualDocumentApprovalCipher().approve(
            approval_token,
            filename=upload.filename,
            content=upload.content,
            agency_id=agency_id,
            actor_id=current_user.id,
            group_id=group_id,
            upload_id=upload_id,
            document_type=document_type,
        )
    except ManualDocumentApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # Approval chooses only the document lane. Passenger identity is resolved
    # again from the current authorized roster with the ordinary matcher.
    group = await _get_authorized_group(group_id, current_user=current_user, session=session)
    passengers = await _group_passengers(group_id, current_user=current_user, session=session)
    if not passengers:
        raise HTTPException(
            status_code=400,
            detail="This group has no passengers to match documents against",
        )
    matcher = DocumentMatcher()
    linked_source = await _read_linked_document_match_source(session, group=group, lock=False)
    identifiers = await _linked_document_match_identifiers(
        session,
        group=group,
        passengers=passengers,
        matcher=matcher,
        source=linked_source,
    )
    roster_snapshot = _document_match_roster_snapshot(passengers)
    fingerprints = verification_scope_fingerprints(
        roster_snapshot=roster_snapshot,
        source_snapshot=linked_source.snapshot,
        identifiers=identifiers,
    )
    await session.rollback()

    def match_document() -> list[MatchResult]:
        index = matcher.build_index(
            passengers,
            agency_id=agency_id,
            group_id=group_id,
            supplemental_identifiers=identifiers,
        )
        return matcher.match_all(classification, passengers, index=index)

    candidate_matches = await asyncio.to_thread(match_document)
    passengers_by_id = {passenger.id: passenger for passenger in passengers}
    matches = automatic_passenger_matches(
        candidate_matches, allowed_passenger_ids=set(passengers_by_id)
    )
    receipt: str | None = None
    if matches:
        try:
            tokens = await stage_verified_documents(
                [
                    VerificationStagingInput(
                        filename=upload.filename,
                        content=upload.content,
                        content_type=upload.content_type,
                        classification=classification,
                    )
                ],
                agency_id=agency_id,
                actor_id=current_user.id,
                group_id=group_id,
                upload_id=staging_upload_id,
                chunk_id=chunk_id,
                document_type=document_type,
                roster_fingerprint=fingerprints[0],
                source_fingerprint=fingerprints[1],
                identifiers_fingerprint=fingerprints[2],
            )
        except StorageError as exc:
            raise HTTPException(
                status_code=503,
                detail="Approved PDF staging is temporarily unavailable. Please try again.",
                headers={"Retry-After": "1"},
            ) from exc
        if not tokens:
            # Manual approval must never use raw finalization: that path has no
            # proof of this review and correctly repeats strict classification.
            raise HTTPException(
                status_code=413,
                detail=(
                    "This PDF is too large for a review receipt. "
                    "Upload a smaller PDF and check it again."
                ),
            )
        receipt = tokens[0]

    actor, _ = await _lock_and_validate_document_match_scope(
        session,
        current_user=current_user,
        group_id=group_id,
        agency_id=agency_id,
        matcher=matcher,
        expected_roster_snapshot=roster_snapshot,
        expected_source_snapshot=linked_source.snapshot,
        expected_supplemental_identifiers=identifiers,
    )
    await _require_unstarted_upload(session, staging_upload_id)
    await AuditLogRepository(session).record(
        action="document_type_manually_approved",
        entity_type="client_group",
        entity_id=str(group_id),
        agency_id=agency_id,
        user_id=actor.id,
        actor_email=actor.email,
        metadata={
            "document_type": document_type,
            "original_detected_type": "unknown",
            "content_sha256": hashlib.sha256(upload.content).hexdigest(),
            "upload_id": str(staging_upload_id),
            "reviewed_upload_id": str(upload_id),
            "chunk_id": str(chunk_id),
            "passenger_match_count": len(matches),
            "staged_for_upload": receipt is not None,
        },
    )
    feedback = matches[0] if matches else candidate_matches[0] if candidate_matches else None
    matched_passengers = [
        passengers_by_id[match.passenger_id] for match in matches if match.passenger_id
    ]
    primary = matched_passengers[0] if matched_passengers else None
    return VerifiedDocumentResponse(
        filename=upload.filename,
        detected_type=classification.detected_type,
        accepted=bool(matches),
        reason=(
            classification.reason
            if matches
            else feedback.reason if feedback else "No passenger match found"
        ),
        matched_passenger_id=matches[0].passenger_id if matches else None,
        matched_passenger_name=primary.client_name if primary else None,
        matched_passenger_ids=[match.passenger_id for match in matches if match.passenger_id],
        matched_passenger_names=[passenger.client_name for passenger in matched_passengers],
        match_confidence=feedback.confidence if feedback else 0.0,
        match_status=feedback.status if feedback else None,
        match_reason=(
            f"Matched {len(matches)} passengers in one PDF"
            if len(matches) > 1
            else feedback.reason if feedback else None
        ),
        staging_receipt=receipt,
        manual_type_approved=True,
    )
