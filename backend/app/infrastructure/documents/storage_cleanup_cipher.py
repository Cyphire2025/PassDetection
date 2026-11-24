"""Storage cleanup cipher: focused encrypted tombstone owner."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping, Sequence

from cryptography.fernet import Fernet, InvalidToken

from app.core.config.settings import get_settings

from .storage_cleanup_policy import (
    STORAGE_CLEANUP_KEY_VERSION,
)
from .storage_cleanup_types import (
    StorageCleanupPayloadError,
)


class StorageCleanupCipher:
    """Domain-separated encryption for short-lived storage-key tombstones."""

    def __init__(
        self,
        app_secret_key: str,
        *,
        key_version: int = STORAGE_CLEANUP_KEY_VERSION,
        decryption_keys: Mapping[int, str] | None = None,
    ) -> None:
        if key_version < 1:
            raise StorageCleanupPayloadError("Storage cleanup key version is invalid")
        self._fernets = {key_version: _storage_cleanup_fernet(app_secret_key, key_version)}
        for version, fallback_key in (decryption_keys or {}).items():
            if version < 1:
                raise StorageCleanupPayloadError("Storage cleanup key version is invalid")
            fallback = _storage_cleanup_fernet(fallback_key, version)
            if version == key_version and fallback_key != app_secret_key:
                raise StorageCleanupPayloadError("Storage cleanup keyring conflicts")
            self._fernets[version] = fallback
        self._key_version = key_version

    @classmethod
    def from_settings(cls) -> StorageCleanupCipher:
        settings = get_settings()
        configured_key = _secret_value(settings.storage_cleanup_encryption_key)
        active_key = configured_key or settings.app_secret_key
        fallback_keys: dict[int, str] = {}
        for version, value in settings.storage_cleanup_decryption_keys.items():
            fallback = _secret_value(value)
            if fallback is None:
                raise StorageCleanupPayloadError("Storage cleanup decryption key is invalid")
            fallback_keys[version] = fallback
        return cls(
            active_key,
            key_version=settings.storage_cleanup_encryption_key_version,
            decryption_keys=fallback_keys,
        )

    @property
    def key_version(self) -> int:
        return self._key_version

    def encrypt(self, storage_keys: Sequence[str]) -> bytes:
        payload = json.dumps(list(storage_keys), ensure_ascii=False, separators=(",", ":"))
        return bytes(self._fernets[self._key_version].encrypt(payload.encode("utf-8")))

    def decrypt(self, ciphertext: bytes, *, key_version: int) -> tuple[str, ...]:
        fernet = self._fernets.get(key_version)
        if fernet is None:
            raise StorageCleanupPayloadError("Storage cleanup key version is unavailable")
        try:
            plaintext = fernet.decrypt(ciphertext)
            payload = json.loads(plaintext.decode("utf-8"))
        except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError):
            raise StorageCleanupPayloadError("Storage cleanup payload is invalid") from None
        if not isinstance(payload, list) or not all(isinstance(item, str) for item in payload):
            raise StorageCleanupPayloadError("Storage cleanup payload is invalid")
        return tuple(payload)


def _secret_value(value: object) -> str | None:
    if value is None:
        return None
    getter = getattr(value, "get_secret_value", None)
    if callable(getter):
        secret = getter()
        return secret if isinstance(secret, str) else None
    return value if isinstance(value, str) else None


def _storage_cleanup_fernet(secret: str, key_version: int) -> Fernet:
    if not isinstance(secret, str) or len(secret) < 16:
        raise StorageCleanupPayloadError("Storage cleanup encryption is unavailable")
    derived = hashlib.sha256(
        b"passdetection-storage-cleanup\x00"
        + str(key_version).encode("ascii")
        + b"\x00"
        + secret.encode("utf-8")
    ).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


StorageCleanupCipher.__module__ = "app.infrastructure.documents.storage_cleanup"
StorageCleanupCipher.__init__.__module__ = "app.infrastructure.documents.storage_cleanup"
StorageCleanupCipher.__dict__["from_settings"].__func__.__module__ = (
    "app.infrastructure.documents.storage_cleanup"
)
StorageCleanupCipher.__dict__["key_version"].fget.__module__ = (
    "app.infrastructure.documents.storage_cleanup"
)
StorageCleanupCipher.encrypt.__module__ = "app.infrastructure.documents.storage_cleanup"
StorageCleanupCipher.decrypt.__module__ = "app.infrastructure.documents.storage_cleanup"

_secret_value.__module__ = "app.infrastructure.documents.storage_cleanup"

_storage_cleanup_fernet.__module__ = "app.infrastructure.documents.storage_cleanup"
