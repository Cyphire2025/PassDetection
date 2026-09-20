"""Authorize a public submission's contact before any final submission side effects."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.public_upload_contact_model import (
    PublicUploadContactChallengeModel,
)
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.presentation.api.v1.schemas.passport_schemas import ClientSubmitPassportRequest

from .contact_verification import require_public_contact_proof, require_verified_family_head
from .public_security import _require_public_upload_credential


async def require_verified_submission_contact(
    session: AsyncSession,
    *,
    submission_id: uuid.UUID,
    body: ClientSubmitPassportRequest,
    upload_session_id: str,
) -> PublicUploadContactChallengeModel:
    """Lock the draft, then validate its capability and contact/family proof in order."""
    existing = await PassportSubmissionRepository(session).get_by_id_for_update(submission_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Passport submission was not found",
        )
    _require_public_upload_credential(existing, upload_session_id)
    contact_proof = await require_public_contact_proof(
        session,
        submission=existing,
        phone_verification_id=body.phone_verification_id,
        upload_session_id=upload_session_id,
        client_phone=body.client_phone,
        client_email=str(body.client_email),
    )
    if body.submission_mode == "family":
        await require_verified_family_head(
            session,
            submission=existing,
            own_proof=contact_proof,
            family_group_id=body.family_group_id,
            family_member_index=body.family_member_index,
            family_head_email=str(body.family_head_email) if body.family_head_email else None,
            family_head_phone=body.family_head_phone,
        )
    return contact_proof
