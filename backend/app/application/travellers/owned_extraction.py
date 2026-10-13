"""Owned fresh evidence may locate a candidate, never authorize disclosure."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.travellers.identity_index import find_exact_identity
from app.core.security.upload_session import upload_session_matches_identifier
from app.domain.services.traveller_identity import identity_evidence
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto


async def owned_extraction_candidate(session: AsyncSession, *, group: ClientGroupModel,
    source_submission_id: uuid.UUID, expected_extraction_revision: int, upload_session_id: str,
    crypto: TravellerReuseCrypto, lock_source: bool = False,
) -> uuid.UUID | None:
    if group.company_id is None:
        return None
    query = select(PassportSubmissionModel).where(PassportSubmissionModel.id == source_submission_id,
        PassportSubmissionModel.agency_id == group.agency_id, PassportSubmissionModel.group_id == group.id)
    if lock_source:
        query = query.with_for_update().execution_options(populate_existing=True)
    source = await session.scalar(query)
    if (source is None or source.extraction_revision != expected_extraction_revision
            or source.extraction_status != "extraction_complete" or source.status in {"deleted", "rejected"}
            or not upload_session_matches_identifier(upload_session_id, source.upload_idempotency_key or "")):
        return None
    evidence = identity_evidence(source.extracted_fields or {}, name=source.client_name,
        phone=source.client_phone, email=source.client_email)
    match = await find_exact_identity(session, agency_id=group.agency_id, company_id=group.company_id,
        evidence=evidence, crypto=crypto)
    return match.traveller_id
