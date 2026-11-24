"""Authorize final public submission using a scoped verified contact proof."""

from __future__ import annotations

import hmac
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.public_contact_proof import digest as _digest
from app.application.security.public_contact_proof import utc as _utc
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES, PassportSubmission
from app.domain.value_objects.phone_number import normalize_phone_number
from app.infrastructure.database.public_upload_contact_model import (
    PublicUploadContactChallengeModel,
)

from .contact_challenges import _locked_challenge


async def require_public_contact_proof(
    session: AsyncSession,
    *,
    submission: PassportSubmission,
    phone_verification_id: uuid.UUID,
    upload_session_id: str,
    client_phone: str,
    client_email: str,
) -> PublicUploadContactChallengeModel:
    """Validate under the already-held submission lock before storage promotion.

    Consumed proofs only permit retry of the same already-submitted contact;
    the use case still checks every field for its exact idempotent replay.
    """
    challenge = await _locked_challenge(session, submission.id)
    now = datetime.now(UTC)
    if (
        challenge is None or challenge.id != phone_verification_id
        or challenge.group_id != submission.group_id
        or challenge.phone_number != normalize_phone_number(client_phone)
        or not hmac.compare_digest(challenge.email_hash, _digest("email", client_email.lower().strip()))
        or not hmac.compare_digest(challenge.upload_session_hash, _digest("upload-session", upload_session_id))
        or not (
            (
                challenge.status == "verified" and challenge.proof_expires_at is not None
                and _utc(challenge.proof_expires_at) > now
            )
            or (
                challenge.status == "consumed" and challenge.consumed_at is not None
                and submission.status.value in OFFICE_VISIBLE_PASSPORT_STATUS_VALUES
                and normalize_phone_number(submission.client_phone) == challenge.phone_number
                and (submission.client_email or "").lower().strip() == client_email.lower().strip()
            )
        )
    ):
        raise HTTPException(
            400,
            detail={
                "code": "CONTACT_VERIFICATION_REQUIRED",
                "message": "Verify your WhatsApp number again before submitting.",
                "field": "phone_verification_id",
            },
            headers={"Cache-Control": "no-store"},
        )
    return challenge
