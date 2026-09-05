"""Document distribution: verification."""

from __future__ import annotations

import asyncio
import uuid
from time import perf_counter
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import StorageError
from app.domain.value_objects.travel_document_taxonomy import DOCUMENT_TYPES
from app.infrastructure.database.session import get_db_session
from app.infrastructure.documents.distribution_ingestion import automatic_passenger_matches
from app.infrastructure.documents.document_matcher import (
    DocumentMatcher,
    DocumentParserUnavailableError,
    MatchResult,
    UnsupportedDocumentBatchFormatError,
    classify_documents_bounded,
)
from app.infrastructure.documents.pdf_parser_sandbox import bounded_pdf_batch_timeout_seconds
from app.infrastructure.documents.verification_staging import (
    VerificationStagingInput,
    stage_verified_documents,
    verification_scope_fingerprints,
)
from app.infrastructure.security.upload_security import UploadSecurityContext
from app.presentation.api.v1.document_uploads import read_bounded_document_uploads
from app.presentation.api.v1.routes.document_distribution_matching import (
    _linked_document_match_identifiers,
    _read_linked_document_match_source,
)
from app.presentation.api.v1.routes.document_distribution_scope import (
    _get_authorized_group,
    _group_passengers,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    _document_match_roster_snapshot,
    logger,
)
from app.presentation.api.v1.schemas.document_distribution_schemas import (
    VerifiedDocumentResponse,
    VerifyDocumentBatchResponse,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


@router.post(
    "/groups/{group_id}/{document_type}/verify",
    response_model=VerifyDocumentBatchResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def verify_documents(
    group_id: uuid.UUID,
    document_type: str,
    files: list[UploadFile] = File(...),
    upload_id: Annotated[uuid.UUID | None, Form()] = None,
    chunk_id: Annotated[uuid.UUID | None, Form()] = None,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> VerifyDocumentBatchResponse:
    started_at = perf_counter()
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported document type"
        )
    if (upload_id is None) != (chunk_id is None):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document verification session metadata is incomplete",
        )
    group = await _get_authorized_group(group_id, current_user=current_user, session=session)
    passengers = await _group_passengers(group_id, current_user=current_user, session=session)
    if not passengers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This group has no passengers to match documents against",
        )

    matcher = DocumentMatcher()
    linked_source = await _read_linked_document_match_source(
        session,
        group=group,
        lock=False,
    )
    supplemental_identifiers = await _linked_document_match_identifiers(
        session,
        group=group,
        passengers=passengers,
        matcher=matcher,
        source=linked_source,
    )
    roster_fingerprint, source_fingerprint, identifiers_fingerprint = (
        verification_scope_fingerprints(
            roster_snapshot=_document_match_roster_snapshot(passengers),
            source_snapshot=linked_source.snapshot,
            identifiers=supplemental_identifiers,
        )
    )
    agency_id = group.agency_id
    await session.rollback()
    phase_started_at = perf_counter()
    uploads = await read_bounded_document_uploads(
        files,
        security_context=UploadSecurityContext(
            ingestion_flow="document_distribution_verify",
            agency_id=agency_id,
            user_id=current_user.id,
        ),
    )
    upload_read_ms = (perf_counter() - phase_started_at) * 1000
    phase_started_at = perf_counter()
    match_index = await asyncio.to_thread(
        matcher.build_index,
        passengers,
        agency_id=agency_id,
        group_id=group_id,
        supplemental_identifiers=supplemental_identifiers,
    )
    match_index_ms = (perf_counter() - phase_started_at) * 1000
    passengers_by_id = {passenger.id: passenger for passenger in passengers}
    phase_started_at = perf_counter()
    try:
        classifications = await asyncio.to_thread(
            classify_documents_bounded,
            matcher,
            [(upload.filename, upload.content, document_type) for upload in uploads],
            isolate_pdf_parsing=True,
            batch_timeout_seconds=bounded_pdf_batch_timeout_seconds(len(uploads)),
            reject_common_unsupported_format=True,
        )
    except UnsupportedDocumentBatchFormatError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc
    except DocumentParserUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
            headers={"Retry-After": "1"},
        ) from exc
    classification_ms = (perf_counter() - phase_started_at) * 1000

    def match_classifications() -> list[list[MatchResult]]:
        return [
            matcher.match_all(classification, passengers, index=match_index)
            if classification.accepted
            else []
            for classification in classifications
        ]

    phase_started_at = perf_counter()
    matches_by_classification = await asyncio.to_thread(match_classifications)
    matching_ms = (perf_counter() - phase_started_at) * 1000
    allowed_passenger_ids = set(passengers_by_id)
    uploadable_matches_by_classification = [
        automatic_passenger_matches(
            matches,
            allowed_passenger_ids=allowed_passenger_ids,
        )
        for matches in matches_by_classification
    ]
    accepted_indexes = [
        index
        for index, (classification, matches) in enumerate(
            zip(
                classifications,
                uploadable_matches_by_classification,
                strict=True,
            )
        )
        if classification.accepted and matches
    ]
    # Older clients do not send upload-session metadata. They keep the
    # established raw multipart finalization path and receive no unbound
    # receipts.
    staging_tokens: list[str] | None = (
        [] if upload_id is not None and chunk_id is not None else None
    )
    phase_started_at = perf_counter()
    if accepted_indexes and upload_id is not None and chunk_id is not None:
        try:
            staging_tokens = await stage_verified_documents(
                [
                    VerificationStagingInput(
                        filename=uploads[index].filename,
                        content=uploads[index].content,
                        content_type=uploads[index].content_type,
                        classification=classifications[index],
                    )
                    for index in accepted_indexes
                ],
                agency_id=agency_id,
                actor_id=current_user.id,
                group_id=group_id,
                upload_id=upload_id,
                chunk_id=chunk_id,
                document_type=document_type,
                roster_fingerprint=roster_fingerprint,
                source_fingerprint=source_fingerprint,
                identifiers_fingerprint=identifiers_fingerprint,
            )
        except StorageError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Verified PDF staging is temporarily unavailable. Please try again.",
                headers={"Retry-After": "1"},
            ) from exc
    staging_ms = (perf_counter() - phase_started_at) * 1000
    staging_token_by_index = (
        dict(zip(accepted_indexes, staging_tokens, strict=True))
        if staging_tokens is not None
        else {}
    )

    verified: list[VerifiedDocumentResponse] = []
    for index, (upload, classification, candidate_matches, matches) in enumerate(
        zip(
            uploads,
            classifications,
            matches_by_classification,
            uploadable_matches_by_classification,
            strict=True,
        )
    ):
        matched_passengers = [
            passengers_by_id[match.passenger_id]
            for match in matches
            if match.passenger_id in passengers_by_id
        ]
        primary_match = matches[0] if matches else None
        feedback_match = primary_match or (candidate_matches[0] if candidate_matches else None)
        primary_passenger = matched_passengers[0] if matched_passengers else None
        is_uploadable = classification.accepted and bool(matches)
        rejection_reason = (
            feedback_match.reason
            if classification.accepted and not is_uploadable and feedback_match
            else "No passenger match found"
            if classification.accepted and not is_uploadable
            else classification.reason
        )
        verified.append(
            VerifiedDocumentResponse(
                filename=upload.filename,
                detected_type=classification.detected_type,
                accepted=is_uploadable,
                reason=rejection_reason,
                matched_passenger_id=primary_match.passenger_id if primary_match else None,
                matched_passenger_name=primary_passenger.client_name if primary_passenger else None,
                matched_passenger_ids=[
                    match.passenger_id for match in matches if match.passenger_id
                ],
                matched_passenger_names=[passenger.client_name for passenger in matched_passengers],
                match_confidence=feedback_match.confidence if feedback_match else 0.0,
                match_status=feedback_match.status if feedback_match else None,
                match_reason=(
                    f"Matched {len(matched_passengers)} passengers in one PDF"
                    if len(matched_passengers) > 1
                    else feedback_match.reason
                    if feedback_match
                    else None
                ),
                staging_receipt=staging_token_by_index.get(index),
            )
        )

    accepted_count = sum(1 for item in verified if item.accepted)
    response = VerifyDocumentBatchResponse(
        group_id=group_id,
        document_type=document_type,
        total_count=len(verified),
        accepted_count=accepted_count,
        rejected_count=len(verified) - accepted_count,
        files=verified,
    )
    logger.info(
        "document_distribution_verify_completed",
        document_type=document_type,
        file_count=len(verified),
        accepted_count=accepted_count,
        rejected_count=len(verified) - accepted_count,
        staging_enabled=staging_tokens is not None,
        upload_read_ms=round(upload_read_ms, 1),
        match_index_ms=round(match_index_ms, 1),
        classification_ms=round(classification_ms, 1),
        matching_ms=round(matching_ms, 1),
        staging_ms=round(staging_ms, 1),
        duration_ms=round((perf_counter() - started_at) * 1000, 1),
    )
    return response
