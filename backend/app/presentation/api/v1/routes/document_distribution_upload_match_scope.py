"""Authorize and snapshot the group scope before untrusted PDF processing."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import PassportSubmission, User
from app.infrastructure.documents.document_matcher import (
    DocumentMatcher,
    PassengerIdentifier,
)
from app.infrastructure.documents.verification_staging import (
    verification_scope_fingerprints,
)
from app.presentation.api.v1.document_chunk_uploads import (
    DocumentChunkMetadata,
)
from app.presentation.api.v1.routes.document_distribution_matching import (
    _linked_document_match_identifiers,
    _read_linked_document_match_source,
)
from app.presentation.api.v1.routes.document_distribution_queries import (
    _first_blocking_processing_upload_id,
)
from app.presentation.api.v1.routes.document_distribution_review_support import (
    _LinkedDocumentMatchSource,
)
from app.presentation.api.v1.routes.document_distribution_scope import (
    _get_authorized_group,
    _group_passengers,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    _document_match_roster_snapshot,
)


@dataclass(frozen=True, slots=True)
class DistributionUploadMatchScope:
    agency_id: uuid.UUID
    passengers: list[PassportSubmission]
    matcher: DocumentMatcher
    linked_source: _LinkedDocumentMatchSource
    supplemental_identifiers: tuple[PassengerIdentifier, ...]
    roster_fingerprint: str
    source_fingerprint: str
    identifiers_fingerprint: str


async def authorize_distribution_upload(
    *,
    session: AsyncSession,
    current_user: User,
    group_id: uuid.UUID,
    document_type: str,
    chunk_metadata: DocumentChunkMetadata | None,
) -> DistributionUploadMatchScope:
    authorized_group = await _get_authorized_group(
        group_id,
        current_user=current_user,
        session=session,
    )
    if chunk_metadata is not None and chunk_metadata.chunk_index == 0:
        blocking_upload_id = await _first_blocking_processing_upload_id(
            session,
            group_id=group_id,
            agency_id=authorized_group.agency_id,
            document_type=document_type,
            exclude_upload_id=chunk_metadata.upload_id,
        )
        if blocking_upload_id is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Discard or resume the existing incomplete upload before starting another one"
                ),
            )
    initial_passengers = await _group_passengers(
        group_id,
        current_user=current_user,
        session=session,
    )
    if not initial_passengers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This group has no passengers to match documents against",
        )
    matcher = DocumentMatcher()
    group = authorized_group
    passengers = initial_passengers
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
    agency_id = group.agency_id
    roster_fingerprint, source_fingerprint, identifiers_fingerprint = (
        verification_scope_fingerprints(
            roster_snapshot=_document_match_roster_snapshot(passengers),
            source_snapshot=linked_source.snapshot,
            identifiers=supplemental_identifiers,
        )
    )
    await session.rollback()

    return DistributionUploadMatchScope(
        agency_id,
        passengers,
        matcher,
        linked_source,
        supplemental_identifiers,
        roster_fingerprint,
        source_fingerprint,
        identifiers_fingerprint,
    )
