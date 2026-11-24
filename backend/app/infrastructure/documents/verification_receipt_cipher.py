"""Verification receipt cipher."""

from __future__ import annotations

import base64
import hashlib
import json
import zlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config.settings import get_settings
from app.infrastructure.documents.verification_receipt_models import (
    MAX_VERIFICATION_RECEIPT_LENGTH,
    MAX_VERIFICATION_RECEIPT_PAYLOAD,
    StagedDocumentReceipt,
    VerificationReceiptError,
)
from app.infrastructure.documents.verification_receipt_payload import (
    _receipt_from_payload,
    _serialized_receipt_payload,
)


class VerificationReceiptCipher:
    """Versioned, domain-separated encryption for opaque client receipts."""

    def __init__(self) -> None:
        settings = get_settings()
        configured = settings.storage_cleanup_encryption_key
        active_secret = (
            configured.get_secret_value() if configured is not None else settings.app_secret_key
        )
        active_version = settings.storage_cleanup_encryption_key_version
        self._active_version = active_version
        self._fernets = {
            active_version: _verification_receipt_fernet(active_secret, active_version)
        }
        for version, secret in settings.storage_cleanup_decryption_keys.items():
            self._fernets.setdefault(
                version,
                _verification_receipt_fernet(secret.get_secret_value(), version),
            )

    def encrypt(self, receipt: StagedDocumentReceipt) -> str:
        payload = _serialized_receipt_payload(receipt)
        compressed = zlib.compress(payload, level=6)
        token = self._fernets[self._active_version].encrypt(compressed).decode("ascii")
        return f"{self._active_version}.{token}"

    def decrypt(self, token: str) -> StagedDocumentReceipt:
        if not token or len(token) > MAX_VERIFICATION_RECEIPT_LENGTH:
            raise VerificationReceiptError("The document verification receipt is invalid")
        version_text, separator, ciphertext = token.partition(".")
        if separator != "." or not version_text.isdigit():
            raise VerificationReceiptError("The document verification receipt is invalid")
        try:
            fernet = self._fernets.get(int(version_text))
            if fernet is None:
                raise VerificationReceiptError("The document verification receipt is invalid")
            compressed = fernet.decrypt(ciphertext.encode("ascii"))
            decompressor = zlib.decompressobj()
            payload = decompressor.decompress(compressed, MAX_VERIFICATION_RECEIPT_PAYLOAD + 1)
            if (
                len(payload) > MAX_VERIFICATION_RECEIPT_PAYLOAD
                or decompressor.unconsumed_tail
                or not decompressor.eof
            ):
                raise VerificationReceiptError("The document verification receipt is invalid")
            parsed = json.loads(payload)
        except (
            InvalidToken,
            UnicodeError,
            ValueError,
            TypeError,
            json.JSONDecodeError,
            zlib.error,
        ) as exc:
            if isinstance(exc, VerificationReceiptError):
                raise
            raise VerificationReceiptError("The document verification receipt is invalid") from exc
        return _receipt_from_payload(parsed)


def _verification_receipt_fernet(secret: str, version: int) -> Fernet:
    derived = hashlib.sha256(
        b"document-verification-receipt\x00"
        + str(version).encode("ascii")
        + b"\x00"
        + secret.encode("utf-8")
    ).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


VerificationReceiptCipher.__module__ = "app.infrastructure.documents.verification_staging"
_verification_receipt_fernet.__module__ = "app.infrastructure.documents.verification_staging"
