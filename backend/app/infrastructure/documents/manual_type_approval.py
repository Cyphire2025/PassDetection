"""Short-lived proof that an unidentified PDF passed server-side safety checks.

This proof cannot finalize an upload. An affirmative, authorized review exchanges
it for the existing accepted-document staging receipt after passenger matching.
"""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
import zlib
from datetime import UTC, datetime

from cryptography.fernet import Fernet, InvalidToken

from app.core.config.settings import get_settings
from app.domain.value_objects.travel_document_taxonomy import classification_document_type
from app.infrastructure.documents.document_approval_provenance import (
    MANUAL_DOCUMENT_TYPE_APPROVAL_PREFIX,
)
from app.infrastructure.documents.document_matcher import ClassifiedDocument

MANUAL_APPROVAL_TOKEN_LIMIT = 512 * 1024
_PAYLOAD_LIMIT = 2 * 1024 * 1024
_TTL_SECONDS = 30 * 60


class ManualDocumentApprovalError(ValueError):
    """The review proof is missing, expired, altered, or outside its scope."""


class ManualDocumentApprovalCipher:
    def __init__(self) -> None:
        settings = get_settings()
        secret = settings.storage_cleanup_encryption_key
        active_secret = secret.get_secret_value() if secret else settings.app_secret_key
        self._active_version = settings.storage_cleanup_encryption_key_version
        secrets = {
            version: old_secret.get_secret_value()
            for version, old_secret in settings.storage_cleanup_decryption_keys.items()
        }
        secrets[self._active_version] = active_secret
        self._fernets = {
            version: Fernet(
                base64.urlsafe_b64encode(
                    hashlib.sha256(
                        b"document-manual-type-approval\x00"
                        + str(version).encode("ascii")
                        + b"\x00"
                        + value.encode("utf-8")
                    ).digest()
                )
            )
            for version, value in secrets.items()
        }

    def issue(
        self,
        *,
        classification: ClassifiedDocument,
        content: bytes,
        agency_id: uuid.UUID,
        actor_id: uuid.UUID,
        group_id: uuid.UUID,
        upload_id: uuid.UUID,
        document_type: str,
    ) -> str | None:
        if (
            not classification.manual_review_allowed
            or classification.accepted
            or classification.detected_type != "unknown"
            or classification_document_type(document_type) not in {"visa", "flight_ticket"}
        ):
            return None
        payload = {
            "v": 1,
            "agency_id": str(agency_id),
            "actor_id": str(actor_id),
            "group_id": str(group_id),
            "upload_id": str(upload_id),
            "document_type": document_type,
            "filename": classification.original_filename,
            "byte_count": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
            "pdf_safety_passed": True,
            "detected_type": "unknown",
            "text": classification.text,
            "extracted_name": classification.extracted_name,
            "extracted_passport_number": classification.extracted_passport_number,
            "extracted_reference": classification.extracted_reference,
        }
        serialized = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(serialized) > _PAYLOAD_LIMIT:
            return None
        encrypted = self._fernets[self._active_version].encrypt(zlib.compress(serialized, 6))
        token = f"{self._active_version}.{encrypted.decode('ascii')}"
        return token if len(token) <= MANUAL_APPROVAL_TOKEN_LIMIT else None

    def approve(
        self,
        token: str,
        *,
        filename: str,
        content: bytes,
        agency_id: uuid.UUID,
        actor_id: uuid.UUID,
        group_id: uuid.UUID,
        upload_id: uuid.UUID,
        document_type: str,
    ) -> ClassifiedDocument:
        error = "This PDF review has expired or changed. Select and check the PDF again."
        try:
            if not token or len(token) > MANUAL_APPROVAL_TOKEN_LIMIT:
                raise ValueError("Invalid proof size")
            version, separator, ciphertext = token.partition(".")
            if separator != "." or not version.isdigit():
                raise ValueError("Invalid proof version")
            cipher = self._fernets.get(int(version))
            if cipher is None:
                raise ValueError("Unknown proof version")
            compressed = cipher.decrypt_at_time(
                ciphertext.encode("ascii"),
                ttl=_TTL_SECONDS,
                current_time=int(datetime.now(tz=UTC).timestamp()),
            )
            decoder = zlib.decompressobj()
            raw = decoder.decompress(compressed, _PAYLOAD_LIMIT + 1)
            if len(raw) > _PAYLOAD_LIMIT or decoder.unconsumed_tail or not decoder.eof:
                raise ValueError("Invalid proof payload")
            payload = json.loads(raw)
            expected = {
                "v": 1,
                "agency_id": str(agency_id),
                "actor_id": str(actor_id),
                "group_id": str(group_id),
                "upload_id": str(upload_id),
                "document_type": document_type,
                "filename": filename,
                "byte_count": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "pdf_safety_passed": True,
                "detected_type": "unknown",
            }
            if (
                not isinstance(payload, dict)
                or any(payload.get(key) != value for key, value in expected.items())
                or classification_document_type(document_type) not in {"visa", "flight_ticket"}
                or not isinstance(payload.get("text"), str)
            ):
                raise ValueError("Review scope changed")
            for key in ("extracted_name", "extracted_passport_number", "extracted_reference"):
                if payload.get(key) is not None and not isinstance(payload[key], str):
                    raise ValueError("Invalid extracted field")
        except (InvalidToken, UnicodeError, ValueError, TypeError, zlib.error) as exc:
            raise ManualDocumentApprovalError(error) from exc
        return ClassifiedDocument(
            original_filename=filename,
            detected_type="unknown",
            accepted=True,
            reason=MANUAL_DOCUMENT_TYPE_APPROVAL_PREFIX + document_type,
            text=payload["text"],
            extracted_name=payload.get("extracted_name"),
            extracted_passport_number=payload.get("extracted_passport_number"),
            extracted_reference=payload.get("extracted_reference"),
        )
