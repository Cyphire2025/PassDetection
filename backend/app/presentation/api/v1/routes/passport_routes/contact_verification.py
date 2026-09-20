"""Submission-scoped WhatsApp OTPs, separate from mobile account authentication."""

from __future__ import annotations

import hashlib
import hmac
import math
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.otp_provider import OTPDeliveryError
from app.application.security.public_upload_capability import require_active_public_upload
from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES, PassportSubmission
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.domain.value_objects.phone_number import normalize_phone_number
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.database.public_upload_contact_model import (
    PublicUploadContactChallengeModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.security.mobile_otp_rate_limiter import (
    OTPRateLimitExceeded,
    OTPRateLimitUnavailable,
)
from app.infrastructure.security.public_upload_otp_rate_limiter import PublicUploadOTPRateLimiter
from app.infrastructure.whatsapp.otp_provider import get_otp_provider
from app.presentation.api.v1.schemas.public_upload_contact_schemas import (
    PublicContactOTPRequest,
    PublicContactOTPRequestResponse,
    PublicContactOTPVerifyRequest,
    PublicContactOTPVerifyResponse,
)
from app.presentation.security.client_ip import trusted_client_ip

from .public_security import _require_public_upload_credential

router = APIRouter()
logger = get_logger(__name__)
CONTACT_PROOF_TTL_SECONDS = 3600


def _digest(purpose: str, value: str) -> str:
    # A secret-key HMAC prevents offline guessing of six-digit codes from a DB
    # snapshot; separate domain labels prevent interchange with mobile login.
    return hmac.new(
        get_settings().app_secret_key.encode("utf-8"),
        f"public-upload-contact\0{purpose}\0{value}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _code_digest(challenge_id: uuid.UUID, code: str) -> str:
    return _digest("code", f"{challenge_id}\0{code}")


def _utc(value: datetime) -> datetime:
    # SQLite loses timezone information; PostgreSQL stores aware timestamps.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _remaining(value: datetime, now: datetime) -> int:
    return max(0, math.ceil((_utc(value) - now).total_seconds()))


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"


async def _locked_upload(
    session: AsyncSession, submission_id: uuid.UUID, group_token: str, upload_session_id: str,
) -> PassportSubmission:
    group = await ClientGroupRepository(session).get_by_token(group_token)
    try:
        group = require_active_public_upload(group)
    except EntityNotFoundError as exc:
        raise HTTPException(404, "This upload link is unavailable.") from exc
    submission = await PassportSubmissionRepository(session).get_by_id_for_update(submission_id)
    if submission is None or submission.group_id != group.id:
        raise HTTPException(404, "Passport submission was not found")
    _require_public_upload_credential(submission, upload_session_id)
    if submission.status.value in OFFICE_VISIBLE_PASSPORT_STATUS_VALUES:
        raise HTTPException(409, "Passport details were already submitted.")
    return submission


async def _locked_challenge(
    session: AsyncSession, submission_id: uuid.UUID,
) -> PublicUploadContactChallengeModel | None:
    return (
        await session.execute(
            select(PublicUploadContactChallengeModel)
            .where(PublicUploadContactChallengeModel.submission_id == submission_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


@router.post("/{submission_id}/contact-otp/request", response_model=PublicContactOTPRequestResponse)
async def request_public_contact_otp(
    submission_id: uuid.UUID,
    body: PublicContactOTPRequest,
    request: Request,
    response: Response,
    upload_session_id: str = Header(..., alias="X-Upload-Session-ID", min_length=32, max_length=128),
    session: AsyncSession = Depends(get_db_session),
) -> PublicContactOTPRequestResponse:
    _no_store(response)
    submission = await _locked_upload(session, submission_id, body.group_token, upload_session_id)
    settings = get_settings().mobile
    # Public uploads support families of up to twenty members, including shared
    # household numbers, without altering the stricter mobile login quotas.
    try:
        await PublicUploadOTPRateLimiter().consume(
            normalized_phone=body.phone_number, ip_address=trusted_client_ip(request),
        )
    except OTPRateLimitExceeded as exc:
        raise HTTPException(429, "Please wait before requesting another code.") from exc
    except OTPRateLimitUnavailable as exc:
        raise HTTPException(503, "WhatsApp verification is temporarily unavailable.") from exc

    now = datetime.now(UTC)
    challenge = await _locked_challenge(session, submission_id)
    email_hash = _digest("email", str(body.email).lower().strip())
    session_hash = _digest("upload-session", upload_session_id)
    if challenge is not None and _utc(challenge.resend_available_at) > now:
        retry_after = _remaining(challenge.resend_available_at, now)
        if (
            challenge.status == "pending" and _utc(challenge.expires_at) > now
            and challenge.phone_number == body.phone_number
            and hmac.compare_digest(challenge.email_hash, email_hash)
            and hmac.compare_digest(challenge.upload_session_hash, session_hash)
        ):
            return PublicContactOTPRequestResponse(
                challenge_id=challenge.id,
                expires_in_seconds=_remaining(challenge.expires_at, now),
                resend_after_seconds=retry_after,
            )
        raise HTTPException(
            429, "Please wait before requesting another code.",
            headers={"Retry-After": str(retry_after), "Cache-Control": "no-store"},
        )

    challenge_id = uuid.uuid4()
    development_code = settings.otp_development_code
    code = (
        development_code.get_secret_value()
        if settings.otp_provider == "development" and development_code is not None
        else f"{secrets.randbelow(1_000_000):06d}"
    )
    # The durable submission row lock serializes creation and rotation, including
    # when no challenge exists yet. There can be only one row per submission.
    if challenge is None:
        challenge = PublicUploadContactChallengeModel(submission_id=submission_id)
        session.add(challenge)
    cooldown = max(settings.otp_resend_cooldown_seconds, math.ceil(settings.otp_delivery_timeout_seconds) + 5)
    challenge.id = challenge_id
    challenge.group_id = submission.group_id
    challenge.upload_session_hash = session_hash
    challenge.email_hash = email_hash
    challenge.phone_number = body.phone_number
    challenge.code_hash = _code_digest(challenge_id, code)
    challenge.status = "sending"
    challenge.attempt_count = 0
    challenge.max_attempts = settings.otp_max_attempts
    challenge.expires_at = now + timedelta(seconds=settings.otp_ttl_seconds)
    challenge.resend_available_at = now + timedelta(seconds=cooldown)
    challenge.verified_at = None
    challenge.proof_expires_at = None
    challenge.consumed_at = None
    challenge.created_at = now
    challenge.updated_at = now
    await session.commit()

    # No database locks are held while Meta is contacted. Sending is fail-closed:
    # the code is unusable until the successful result is durably recorded.
    delivered = False
    try:
        await get_otp_provider().send_code(
            normalized_phone=body.phone_number,
            code=code,
            expires_in_seconds=settings.otp_ttl_seconds,
        )
        delivered = True
    except OTPDeliveryError as exc:
        logger.warning("public_contact_otp_delivery_failed", error_code=exc.code)
    except Exception as exc:
        logger.error("public_contact_otp_delivery_failed", error_type=type(exc).__name__)

    await _locked_upload(session, submission_id, body.group_token, upload_session_id)
    challenge = await _locked_challenge(session, submission_id)
    if challenge is None or challenge.id != challenge_id or challenge.status != "sending":
        raise HTTPException(409, "The verification request changed. Request a new code.")
    challenge.status = "pending" if delivered else "failed"
    if not delivered:
        challenge.code_hash = None
    challenge.updated_at = datetime.now(UTC)
    await session.commit()
    if not delivered:
        raise HTTPException(
            503, "We could not send your WhatsApp code. Please try again shortly.",
            headers={"Retry-After": str(cooldown), "Cache-Control": "no-store"},
        )
    return PublicContactOTPRequestResponse(
        challenge_id=challenge_id,
        expires_in_seconds=_remaining(challenge.expires_at, datetime.now(UTC)),
        resend_after_seconds=_remaining(challenge.resend_available_at, datetime.now(UTC)),
    )


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
    challenge.attempt_count += 1
    challenge.updated_at = now
    if not hmac.compare_digest(challenge.code_hash, _code_digest(challenge.id, body.code)):
        if challenge.attempt_count >= challenge.max_attempts:
            challenge.status = "locked"
            challenge.code_hash = None
        # Persist failed attempts even though the HTTP request returns an error.
        await session.commit()
        raise HTTPException(400, "Invalid or expired verification code. Request a new code if needed.")

    challenge.status = "verified"
    challenge.code_hash = None
    challenge.verified_at = now
    challenge.proof_expires_at = now + timedelta(seconds=CONTACT_PROOF_TTL_SECONDS)
    await session.commit()
    return PublicContactOTPVerifyResponse(
        phone_verification_id=challenge.id,
        phone_number=challenge.phone_number,
        expires_in_seconds=CONTACT_PROOF_TTL_SECONDS,
    )


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


async def require_verified_family_head(
    session: AsyncSession,
    *,
    submission: PassportSubmission,
    own_proof: PublicUploadContactChallengeModel,
    family_group_id: uuid.UUID | None,
    family_member_index: int | None,
    family_head_email: str | None,
    family_head_phone: str | None,
) -> None:
    """Bind family broadcast contacts to member zero's consumed OTP proof."""
    email = (family_head_email or "").lower().strip()
    phone = normalize_phone_number(family_head_phone)
    valid = False
    if family_group_id is not None and family_member_index == 0:
        valid = bool(
            email and phone == own_proof.phone_number
            and hmac.compare_digest(own_proof.email_hash, _digest("email", email))
        )
    elif family_group_id is not None and family_member_index is not None and family_member_index > 0:
        heads = (
            await session.execute(
                select(PassportSubmissionModel, PublicUploadContactChallengeModel)
                .join(
                    PublicUploadContactChallengeModel,
                    PublicUploadContactChallengeModel.submission_id == PassportSubmissionModel.id,
                )
                .where(
                    PassportSubmissionModel.agency_id == submission.agency_id,
                    PassportSubmissionModel.group_id == submission.group_id,
                    PassportSubmissionModel.family_group_id == family_group_id,
                    PassportSubmissionModel.submission_mode == "family",
                    PassportSubmissionModel.family_member_index == 0,
                    PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
                    PublicUploadContactChallengeModel.group_id == submission.group_id,
                    PublicUploadContactChallengeModel.status == "consumed",
                    PublicUploadContactChallengeModel.consumed_at.is_not(None),
                )
                .limit(2)
                .execution_options(populate_existing=True)
            )
        ).all()
        if len(heads) == 1:
            head, head_proof = heads[0]
            valid = bool(
                email and phone == head_proof.phone_number
                and normalize_phone_number(head.client_phone) == phone
                and (head.client_email or "").lower().strip() == email
                and hmac.compare_digest(head_proof.email_hash, _digest("email", email))
            )
    if not valid:
        raise HTTPException(
            400,
            detail={
                "code": "FAMILY_CONTACT_VERIFICATION_REQUIRED",
                "message": "Family contact details must match the verified first member. Submit that member first.",
                "field": "family_head_phone",
            },
            headers={"Cache-Control": "no-store"},
        )
