"""Versioned Fernet encryption for provider OAuth tokens at rest."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from cryptography.fernet import Fernet, InvalidToken

from app.core.config.settings import Settings, get_settings


class TokenEncryptionError(Exception):
    """Safe configuration/encryption failure without token material."""


class TokenDecryptionError(TokenEncryptionError):
    """Safe decryption failure without ciphertext or token material."""


@dataclass(frozen=True, slots=True)
class EncryptedToken:
    ciphertext: str = field(repr=False)
    key_version: int


class EmailTokenCipher:
    """Encrypt with one active key and decrypt with a versioned rotation keyring."""

    def __init__(
        self,
        *,
        key: str,
        key_version: int,
        decryption_keys: Mapping[int, str] | None = None,
    ) -> None:
        if key_version < 1:
            raise TokenEncryptionError("Email token encryption key version is invalid")
        self._fernets: dict[int, Fernet] = {
            key_version: _build_fernet(key),
        }
        for version, fallback_key in (decryption_keys or {}).items():
            if not isinstance(version, int) or version < 1:
                raise TokenEncryptionError("Email token encryption key version is invalid")
            fallback = _build_fernet(fallback_key)
            if version == key_version:
                if fallback_key != key:
                    raise TokenEncryptionError(
                        "The active email token key version has conflicting keys"
                    )
                continue
            self._fernets[version] = fallback
        self._fernet = self._fernets[key_version]
        self._key_version = key_version

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> EmailTokenCipher:
        active_settings = settings or get_settings()
        key_value = _secret_value(getattr(active_settings, "email_token_encryption_key", None))
        if key_value is None or not key_value.strip():
            raise TokenEncryptionError("Email token encryption is not configured")
        raw_version = getattr(active_settings, "email_token_encryption_key_version", 0)
        if not isinstance(raw_version, int):
            raise TokenEncryptionError("Email token encryption key version is invalid")
        raw_decryption_keys = getattr(
            active_settings,
            "email_token_decryption_keys",
            {},
        )
        if not isinstance(raw_decryption_keys, Mapping):
            raise TokenEncryptionError("Email token decryption keyring is invalid")
        decryption_keys: dict[int, str] = {}
        for version, value in raw_decryption_keys.items():
            if not isinstance(version, int):
                raise TokenEncryptionError("Email token encryption key version is invalid")
            fallback_value = _secret_value(value)
            if fallback_value is None or not fallback_value.strip():
                raise TokenEncryptionError("Email token decryption key is invalid")
            decryption_keys[version] = fallback_value.strip()
        return cls(
            key=key_value.strip(),
            key_version=raw_version,
            decryption_keys=decryption_keys,
        )

    @property
    def key_version(self) -> int:
        return self._key_version

    def encrypt(self, token: str) -> EncryptedToken:
        if not token:
            raise TokenEncryptionError("Email provider token cannot be empty")
        try:
            plaintext = token.encode("utf-8")
        except UnicodeEncodeError:
            raise TokenEncryptionError("Email provider token is invalid") from None
        ciphertext = self._fernet.encrypt(plaintext).decode("ascii")
        return EncryptedToken(ciphertext=ciphertext, key_version=self._key_version)

    def decrypt(self, encrypted: EncryptedToken) -> str:
        fernet = self._fernets.get(encrypted.key_version)
        if fernet is None:
            raise TokenDecryptionError("Email token encryption key version is unavailable")
        try:
            plaintext = fernet.decrypt(encrypted.ciphertext.encode("ascii"))
            return plaintext.decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError):
            raise TokenDecryptionError("Email provider token could not be decrypted") from None


def _secret_value(value: object) -> str | None:
    if value is None:
        return None
    getter = getattr(value, "get_secret_value", None)
    if callable(getter):
        secret = getter()
        return secret if isinstance(secret, str) else None
    return value if isinstance(value, str) else None


def _build_fernet(key: str) -> Fernet:
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        raise TokenEncryptionError("Email token encryption key is invalid") from None
