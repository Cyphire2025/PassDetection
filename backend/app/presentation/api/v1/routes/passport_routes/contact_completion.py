"""Verify public contact OTP attempts and return capability-bound proof receipts."""

from __future__ import annotations

import hmac
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.public_contact_proof import (
    CONTACT_PROOF_TTL_SECONDS,
    verify_contact_code,
)
from app.application.security.public_contact_proof import digest as _digest
from app.application.security.public_contact_proof import remaining as _remaining
from app.application.security.public_contact_proof import utc as _utc
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.schemas.public_upload_contact_schemas import (
    PublicContactOTPVerifyRequest,
    PublicContactOTPVerifyResponse,
)

from .contact_challenges import _locked_challenge, _locked_upload, _no_store

router = APIRouter()


@router.post("/{submission_id}/contact-otp/verify", response_model=PublicContactOTPVerifyResponse)
async def verify_public_contact_otp(
    submission_id: uuid.UUID,
    body: PublicContactOTPVerifyRequest,
    response: Response,
    upload_session_id: str = Header(..., alias="X-Upload-Session-ID", min_length=32, max_length=128),
    session: AsyncSession = Depends(get_db_session),
) -> PublicContactOTPVerifyResponse:
    _no_store(response)
    submission = await _locked_upload(session, submission_id, body.group_token, upload_session_id)
    challenge = await _locked_challenge(session, submission_id)
    now = datetime.now(UTC)
    if (
        challenge is not None and challenge.id == body.challenge_id
        and challenge.group_id == submission.group_id
        and hmac.compare_digest(challenge.upload_session_hash, _digest("upload-session", upload_session_id))
        and challenge.status == "verified" and challenge.proof_expires_at is not None
        and _utc(challenge.proof_expires_at) > now
    ):
        # Recover a lost success response for this exact bearer capability.
        # This returns the existing proof and never extends its expiry.
        return PublicContactOTPVerifyResponse(
            phone_verification_id=challenge.id,
            phone_number=challenge.phone_number,
            expires_in_seconds=_remaining(challenge.proof_expires_at, now),
        )
    if (
        challenge is None or challenge.id != body.challenge_id
        or challenge.group_id != submission.group_id
        or not hmac.compare_digest(challenge.upload_session_hash, _digest("upload-session", upload_session_id))
        or challenge.status != "pending" or _utc(challenge.expires_at) <= now
        or challenge.attempt_count >= challenge.max_attempts or not challenge.code_hash
    ):
        raise HTTPException(400, "Invalid or expired verification code. Request a new code.")
    if not verify_contact_code(challenge, body.code, now):
        # Failed attempts remain durable even though the request is rejected.
        await session.commit()
        raise HTTPException(400, "Invalid or expired verification code. Request a new code if needed.")
    await session.commit()
    return PublicContactOTPVerifyResponse(
        phone_verification_id=challenge.id,
        phone_number=challenge.phone_number,
        expires_in_seconds=CONTACT_PROOF_TTL_SECONDS,
    )
