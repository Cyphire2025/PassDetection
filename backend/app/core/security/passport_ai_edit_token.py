"""Short-lived, user-bound proof for a server-generated Visa edit preview."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
import uuid
from dataclasses import dataclass

_MODEL_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")


class PassportAiEditTokenError(ValueError):
    """Raised when an AI preview token is invalid, expired, or out of scope."""


@dataclass(frozen=True, slots=True)
class PassportAiEditTokenClaims:
    submission_id: uuid.UUID
    user_id: uuid.UUID
    image_type: str
    expected_revision: int
    source_key_sha256: str
    prompt_sha256: str
    image_sha256: str
    model: str
    expires_at: int


def issue_passport_ai_edit_token(
    *,
    secret: str,
    submission_id: uuid.UUID,
    user_id: uuid.UUID,
    image_type: str,
    expected_revision: int,
    source_storage_key: str,
    prompt: str,
    image_content: bytes,
    model: str,
    ttl_seconds: int = 600,
) -> str:
    normalized_model = model.strip()
    if not _MODEL_IDENTIFIER_PATTERN.fullmatch(normalized_model):
        raise ValueError("The AI model identifier is invalid.")
    payload = {
        "sid": str(submission_id),
        "uid": str(user_id),
        "typ": image_type,
        "rev": expected_revision,
        "src": hashlib.sha256(source_storage_key.encode("utf-8")).hexdigest(),
        "prm": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "img": hashlib.sha256(image_content).hexdigest(),
        "mdl": normalized_model,
        "exp": int(time.time()) + ttl_seconds,
    }
    encoded = _b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = hmac.new(
        secret.encode("utf-8"),
        encoded.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{encoded}.{_b64encode(signature)}"


def verify_passport_ai_edit_token(
    token: str,
    *,
    secret: str,
    submission_id: uuid.UUID,
    user_id: uuid.UUID,
    image_type: str,
    expected_revision: int,
    source_storage_key: str,
    prompt: str,
    image_content: bytes,
) -> PassportAiEditTokenClaims:
    if not token or len(token) > 2048 or token.count(".") != 1:
        raise PassportAiEditTokenError("The AI preview has expired. Generate it again.")
    encoded, encoded_signature = token.split(".", 1)
    try:
        supplied_signature = _b64decode(encoded_signature)
        expected_signature = hmac.new(
            secret.encode("utf-8"),
            encoded.encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise PassportAiEditTokenError("The AI preview is not valid.")
        payload = json.loads(_b64decode(encoded))
        claims = PassportAiEditTokenClaims(
            submission_id=uuid.UUID(str(payload["sid"])),
            user_id=uuid.UUID(str(payload["uid"])),
            image_type=str(payload["typ"]),
            expected_revision=int(payload["rev"]),
            source_key_sha256=str(payload["src"]),
            prompt_sha256=str(payload["prm"]),
            image_sha256=str(payload["img"]),
            model=str(payload["mdl"]).strip(),
            expires_at=int(payload["exp"]),
        )
    except PassportAiEditTokenError:
        raise
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PassportAiEditTokenError("The AI preview is not valid.") from exc

    expected_source_hash = hashlib.sha256(source_storage_key.encode("utf-8")).hexdigest()
    expected_prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    expected_image_hash = hashlib.sha256(image_content).hexdigest()
    if (
        claims.expires_at < int(time.time())
        or claims.submission_id != submission_id
        or claims.user_id != user_id
        or claims.image_type != image_type
        or claims.expected_revision != expected_revision
        or not _MODEL_IDENTIFIER_PATTERN.fullmatch(claims.model)
        or not hmac.compare_digest(claims.source_key_sha256, expected_source_hash)
        or not hmac.compare_digest(claims.prompt_sha256, expected_prompt_hash)
        or not hmac.compare_digest(claims.image_sha256, expected_image_hash)
    ):
        raise PassportAiEditTokenError("The AI preview has expired or changed. Generate it again.")
    return claims


def _b64encode(content: bytes) -> str:
    return base64.urlsafe_b64encode(content).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(
        f"{value}{padding}",
        altchars=b"-_",
        validate=True,
    )
