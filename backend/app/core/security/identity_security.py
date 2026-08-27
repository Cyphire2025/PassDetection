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
_MFA_CIPHERTEXT_PREFIX = "idsec:mfa:v2:"
_LEGACY_KEY_ID = "legacy-v1"


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


def _secret_text(value: object) -> str:
    getter = getattr(value, "get_secret_value", None)
    if callable(getter):
        return str(getter())
    return str(value)


def _action_hmac_keys(settings: Settings) -> tuple[str, dict[str, str]]:
    active_key_id = settings.identity_action_hmac_key_id
    configured = settings.identity_action_hmac_key
    keys = {
        active_key_id: (
            _secret_text(configured) if configured is not None else settings.app_secret_key
        )
    }
    keys.update(
        {
            key_id: _secret_text(secret)
            for key_id, secret in settings.identity_action_hmac_previous_keys.items()
        }
    )
    return active_key_id, keys


def active_identity_action_key_id(settings: Settings | None = None) -> str:
    resolved = settings or get_settings()
    return resolved.identity_action_hmac_key_id


def hash_identity_action_token(
    value: str,
    *,
    purpose: str,
    key_id: str | None = None,
    settings: Settings | None = None,
) -> str:
    """Hash one action token with its persisted, independently rotatable key."""

    if not value or not purpose:
        raise IdentitySecurityError("Identity action token is invalid")
    resolved = settings or get_settings()
    active_key_id, keys = _action_hmac_keys(resolved)
    selected_key_id = key_id or active_key_id
    secret = keys.get(selected_key_id)
    if secret is None:
        raise IdentitySecurityError("Identity action token key is unavailable")
    if selected_key_id == _LEGACY_KEY_ID:
        # Exact pre-keyring digest so active links survive the first rollout and
        # an old APP_SECRET_KEY can be retained explicitly during later rotation.
        message = f"identity:action-{purpose}:v1:{value}"
    else:
        message = f"identity:action-token:{purpose}:v2:{value}"
    return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def identity_action_token_hash_candidates(
    value: str,
    *,
    purpose: str,
    settings: Settings | None = None,
) -> tuple[tuple[str, str], ...]:
    """Return the bounded active/previous digest candidates for indexed lookup."""

    resolved = settings or get_settings()
    _, keys = _action_hmac_keys(resolved)
    return tuple(
        (
            key_id,
            hash_identity_action_token(
                value,
                purpose=purpose,
                key_id=key_id,
                settings=resolved,
            ),
        )
        for key_id in keys
    )


def _identity_mfa_fernet(secret: str, *, legacy: bool) -> Fernet:
    purpose = (
        b"identity:mfa-secret-encryption:v1"
        if legacy
        else b"identity:mfa-secret-encryption:keyring:v2"
    )
    derived = hmac.new(
        secret.encode("utf-8"),
        purpose,
        hashlib.sha256,
    ).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def _identity_mfa_keyring(settings: Settings) -> tuple[str, dict[str, Fernet]]:
    active_key_id = settings.identity_mfa_encryption_key_id
    configured = settings.identity_mfa_encryption_key
    active_secret = _secret_text(configured) if configured is not None else settings.app_secret_key
    keys = {
        active_key_id: _identity_mfa_fernet(
            active_secret,
            legacy=active_key_id == _LEGACY_KEY_ID,
        )
    }
    for key_id, secret in settings.identity_mfa_decryption_keys.items():
        keys[key_id] = _identity_mfa_fernet(
            _secret_text(secret),
            legacy=key_id == _LEGACY_KEY_ID,
        )
    return active_key_id, keys


def identity_mfa_fernet(settings: Settings | None = None) -> Fernet:
    """Return the active domain-separated TOTP encryption key."""

    resolved = settings or get_settings()
    active_key_id, keys = _identity_mfa_keyring(resolved)
    return keys[active_key_id]


def encrypt_mfa_secret(secret: str, settings: Settings | None = None) -> str:
    if not secret:
        raise IdentitySecurityError("MFA secret is invalid")
    resolved = settings or get_settings()
    active_key_id, keys = _identity_mfa_keyring(resolved)
    token = keys[active_key_id].encrypt(secret.encode("ascii")).decode("ascii")
    return f"{_MFA_CIPHERTEXT_PREFIX}{active_key_id}:{token}"


def decrypt_mfa_secret(ciphertext: str, settings: Settings | None = None) -> str:
    resolved = settings or get_settings()
    _, keys = _identity_mfa_keyring(resolved)
    key_id = _LEGACY_KEY_ID
    token = ciphertext
    if ciphertext.startswith(_MFA_CIPHERTEXT_PREFIX):
        encoded = ciphertext[len(_MFA_CIPHERTEXT_PREFIX) :]
        key_id, separator, token = encoded.partition(":")
        if not separator or not key_id or not token:
            raise IdentitySecurityError("MFA secret could not be decrypted")
    fernet = keys.get(key_id)
    if fernet is None:
        raise IdentitySecurityError("MFA secret encryption key is unavailable")
    try:
        return fernet.decrypt(token.encode("ascii")).decode("ascii")
    except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError):
        raise IdentitySecurityError("MFA secret could not be decrypted") from None


def mfa_ciphertext_key_id(ciphertext: str) -> str:
    """Return a non-secret key identifier for rotation planning."""

    if not ciphertext.startswith(_MFA_CIPHERTEXT_PREFIX):
        return _LEGACY_KEY_ID
    encoded = ciphertext[len(_MFA_CIPHERTEXT_PREFIX) :]
    key_id, separator, _ = encoded.partition(":")
    if not separator or not key_id:
        raise IdentitySecurityError("MFA secret ciphertext header is invalid")
    return key_id


def reencrypt_mfa_secret_if_needed(
    ciphertext: str,
    settings: Settings | None = None,
) -> str:
    """Decrypt-old/encrypt-new helper used inside an already locked mutation."""

    resolved = settings or get_settings()
    if mfa_ciphertext_key_id(
        ciphertext
    ) == resolved.identity_mfa_encryption_key_id and ciphertext.startswith(_MFA_CIPHERTEXT_PREFIX):
        return ciphertext
    return encrypt_mfa_secret(decrypt_mfa_secret(ciphertext, resolved), resolved)


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
    "active_identity_action_key_id",
    "hash_identity_action_token",
    "identity_action_token_hash_candidates",
    "hash_identity_value",
    "hash_recovery_code",
    "normalize_recovery_code",
    "mfa_ciphertext_key_id",
    "reencrypt_mfa_secret_if_needed",
    "totp_code",
    "verify_totp",
]
