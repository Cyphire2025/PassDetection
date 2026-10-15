"""Shared submission/draft OTP cryptography, attempt and proof lifetime rules."""
import hashlib
import hmac
import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Protocol

from app.core.config.settings import get_settings

CONTACT_PROOF_TTL_SECONDS = 3600


def digest(purpose: str, value: str) -> str:
    return hmac.new(get_settings().app_secret_key.encode(),
        f"public-upload-contact\0{purpose}\0{value}".encode(), hashlib.sha256).hexdigest()


def code_digest(challenge_id: uuid.UUID, code: str) -> str:
    return digest("code", f"{challenge_id}\0{code}")


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def remaining(value: datetime, now: datetime) -> int:
    return max(0, math.ceil((utc(value) - now).total_seconds()))


class ContactProof(Protocol):
    id: uuid.UUID
    status: str
    code_hash: str | None
    attempt_count: int
    max_attempts: int
    expires_at: datetime
    updated_at: datetime
    verified_at: datetime | None
    proof_expires_at: datetime | None


def verify_contact_code(challenge: ContactProof, code: str, now: datetime) -> bool:
    """Caller validates owner and commits attempts even on rejection."""
    if (challenge.status != "pending" or utc(challenge.expires_at) <= now
            or challenge.attempt_count >= challenge.max_attempts or not challenge.code_hash):
        return False
    challenge.attempt_count += 1
    challenge.updated_at = now
    if not hmac.compare_digest(challenge.code_hash, code_digest(challenge.id, code)):
        if challenge.attempt_count >= challenge.max_attempts:
            challenge.status, challenge.code_hash = "locked", None
        return False
    challenge.status, challenge.code_hash, challenge.verified_at = "verified", None, now
    challenge.proof_expires_at = now + timedelta(seconds=CONTACT_PROOF_TTL_SECONDS)
    return True
