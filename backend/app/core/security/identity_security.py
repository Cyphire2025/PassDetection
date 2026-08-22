"""Cryptographic primitives for workforce identity lifecycle controls."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
import struct
from datetime import UTC, datetime
from urllib.parse import quote, urlencode

from cryptography.fernet import Fernet, InvalidToken

from app.core.config.settings import Settings, get_settings

TOTP_DIGITS = 6
TOTP_PERIOD_SECONDS = 30
TOTP_ALLOWED_DRIFT_STEPS = 1


class IdentitySecurityError(RuntimeError):
    """Safe identity-credential encryption or validation failure."""


def hash_identity_value(
    value: str,
    *,
    purpose: str,
    settings: Settings | None = None,
) -> str:
    """Return a domain-separated HMAC for a high-entropy identity value."""

    if not value or not purpose:
        raise IdentitySecurityError("Identity security value is invalid")
    resolved = settings or get_settings()
    return hmac.new(
        resolved.app_secret_key.encode("utf-8"),
        f"identity:{purpose}:v1:{value}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def identity_mfa_fernet(settings: Settings | None = None) -> Fernet:
    """Derive a domain-separated encryption key for TOTP secrets."""

    resolved = settings or get_settings()
    derived = hmac.new(
        resolved.app_secret_key.encode("utf-8"),
        b"identity:mfa-secret-encryption:v1",
        hashlib.sha256,
    ).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_mfa_secret(secret: str, settings: Settings | None = None) -> str:
    if not secret:
        raise IdentitySecurityError("MFA secret is invalid")
    return identity_mfa_fernet(settings).encrypt(secret.encode("ascii")).decode("ascii")


def decrypt_mfa_secret(ciphertext: str, settings: Settings | None = None) -> str:
    try:
        return identity_mfa_fernet(settings).decrypt(ciphertext.encode("ascii")).decode("ascii")
    except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError):
        raise IdentitySecurityError("MFA secret could not be decrypted") from None


def generate_mfa_secret() -> str:
    """Generate a 160-bit RFC 4226/6238 base32 secret."""

    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def build_totp_uri(*, secret: str, email: str, issuer: str = "Global Connect") -> str:
    label = quote(f"{issuer}:{email}", safe="")
    query = urlencode(
        {
            "secret": secret,
            "issuer": issuer,
            "algorithm": "SHA1",
            "digits": str(TOTP_DIGITS),
            "period": str(TOTP_PERIOD_SECONDS),
        }
    )
    return f"otpauth://totp/{label}?{query}"


def totp_code(secret: str, *, counter: int) -> str:
    """Generate a six-digit TOTP code for a specific counter."""

    if counter < 0:
        raise IdentitySecurityError("TOTP counter is invalid")
    try:
        padded = secret + ("=" * ((8 - len(secret) % 8) % 8))
        key = base64.b32decode(padded, casefold=True)
    except (binascii.Error, ValueError, TypeError):
        raise IdentitySecurityError("MFA secret is invalid") from None
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10**TOTP_DIGITS)).zfill(TOTP_DIGITS)


def verify_totp(
    secret: str,
    code: str,
    *,
    now: datetime | None = None,
    last_accepted_counter: int | None = None,
) -> int | None:
    """Validate a TOTP code and return its counter for replay fencing."""

    if len(code) != TOTP_DIGITS or not code.isascii() or not code.isdigit():
        return None
    active_now = now or datetime.now(tz=UTC)
    if active_now.tzinfo is None:
        active_now = active_now.replace(tzinfo=UTC)
    current_counter = int(active_now.timestamp()) // TOTP_PERIOD_SECONDS
    for offset in range(-TOTP_ALLOWED_DRIFT_STEPS, TOTP_ALLOWED_DRIFT_STEPS + 1):
        counter = current_counter + offset
        if counter < 0:
            continue
        if last_accepted_counter is not None and counter <= last_accepted_counter:
            continue
        if hmac.compare_digest(totp_code(secret, counter=counter), code):
            return counter
    return None


def generate_recovery_codes(*, count: int = 10) -> list[str]:
    """Generate one-time 80-bit recovery codes in a transcription-safe form."""

    if count < 1 or count > 20:
        raise IdentitySecurityError("Recovery-code count is invalid")
    codes: list[str] = []
    for _ in range(count):
        raw = base64.b32encode(secrets.token_bytes(10)).decode("ascii").rstrip("=")
        codes.append("-".join(raw[index : index + 4] for index in range(0, len(raw), 4)))
    return codes


def normalize_recovery_code(code: str) -> str:
    return "".join(character for character in code.upper() if character.isalnum())


def hash_recovery_code(
    code: str,
    *,
    user_id: object,
    settings: Settings | None = None,
) -> str:
    normalized = normalize_recovery_code(code)
    if len(normalized) < 16:
        raise IdentitySecurityError("Recovery code is invalid")
    return hash_identity_value(
        f"{user_id}:{normalized}",
        purpose="mfa-recovery-code",
        settings=settings,
    )


__all__ = [
    "IdentitySecurityError",
    "build_totp_uri",
    "decrypt_mfa_secret",
    "encrypt_mfa_secret",
    "generate_mfa_secret",
    "generate_recovery_codes",
    "hash_identity_value",
    "hash_recovery_code",
    "normalize_recovery_code",
    "totp_code",
    "verify_totp",
]
