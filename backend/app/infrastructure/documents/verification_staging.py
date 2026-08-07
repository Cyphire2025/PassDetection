"""Durable, tenant-scoped staging receipts for verified distribution PDFs."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import uuid
import zlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet, InvalidToken

from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.domain.value_objects.travel_document_taxonomy import DOCUMENT_TYPES
from app.infrastructure.documents.document_matcher import ClassifiedDocument
from app.infrastructure.documents.storage_cleanup import persist_storage_cleanup_job
from app.infrastructure.documents.storage_transfers import (
    finish_cleanup_despite_cancellation,
    run_bounded_storage_operations,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository

logger = get_logger(__name__)
VERIFICATION_RECEIPT_VERSION = 2
VERIFICATION_RECEIPT_TTL = timedelta(minutes=30)
VERIFICATION_STAGING_PREFIX = "document-verification-staging"
MAX_VERIFICATION_RECEIPT_LENGTH = 512 * 1024
MAX_VERIFICATION_RECEIPT_BATCH_BYTES = 8 * 1024 * 1024
MAX_VERIFICATION_RECEIPT_PAYLOAD = 2 * 1024 * 1024
MAX_VERIFICATION_RECEIPT_DECODED_BATCH_BYTES = 64 * 1024 * 1024
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class VerificationReceiptError(ValueError):
    """A receipt is invalid, tampered with, or outside the active request scope."""


class VerificationReceiptExpiredError(VerificationReceiptError):
    """A valid receipt is past its short, server-controlled lifetime."""

    def __init__(self, message: str, *, storage_keys: tuple[str, ...]) -> None:
        super().__init__(message)
        self.storage_keys = storage_keys


class VerificationReceiptScopeChangedError(VerificationReceiptError):
    """The authorized roster/source changed after the PDFs were checked."""

    def __init__(self, message: str, *, storage_keys: tuple[str, ...]) -> None:
        super().__init__(message)
        self.storage_keys = storage_keys


class VerificationReceiptBatchTooLargeError(VerificationReceiptError):
    """The encoded or decoded receipt selection exceeds its bounded envelope."""


@dataclass(frozen=True, slots=True)
class VerificationStagingInput:
    filename: str
    content: bytes
    content_type: str
    classification: ClassifiedDocument


@dataclass(frozen=True, slots=True)
class StagedDocumentReceipt:
    receipt_id: uuid.UUID
    agency_id: uuid.UUID
    actor_id: uuid.UUID
    group_id: uuid.UUID
    upload_id: uuid.UUID
    chunk_id: uuid.UUID
    document_type: str
    expires_at: datetime
    storage_key: str
    filename: str
    content_type: str
    byte_count: int
    content_sha256: str
    roster_fingerprint: str
    source_fingerprint: str
    identifiers_fingerprint: str
    classification: ClassifiedDocument


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
        fernet = self._fernets.get(int(version_text))
        if fernet is None:
            raise VerificationReceiptError("The document verification receipt is invalid")
        try:
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


def _staging_storage_key(
    *, agency_id: uuid.UUID, actor_id: uuid.UUID, receipt_id: uuid.UUID
) -> str:
    return f"{VERIFICATION_STAGING_PREFIX}/{agency_id}/{actor_id}/{receipt_id}.pdf"


def _scope_fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def verification_scope_fingerprints(
    *, roster_snapshot: object, source_snapshot: object, identifiers: object
) -> tuple[str, str, str]:
    return (
        _scope_fingerprint(roster_snapshot),
        _scope_fingerprint(source_snapshot),
        _scope_fingerprint(identifiers),
    )


def validate_verification_receipt_token_batch(tokens: list[str]) -> None:
    """Reject oversized form receipts before any authenticated decrypt work."""

    encoded_batch_bytes = 0
    for token in tokens:
        try:
            encoded_length = len(token.encode("ascii"))
        except UnicodeEncodeError as exc:
            raise VerificationReceiptError("The document verification receipt is invalid") from exc
        if encoded_length <= 0 or encoded_length > MAX_VERIFICATION_RECEIPT_LENGTH:
            raise VerificationReceiptError("The document verification receipt is invalid")
        encoded_batch_bytes += encoded_length
        if encoded_batch_bytes > MAX_VERIFICATION_RECEIPT_BATCH_BYTES:
            raise VerificationReceiptBatchTooLargeError(
                "The document verification receipts are too large. Check the PDFs again."
            )


async def stage_verified_documents(
    inputs: list[VerificationStagingInput],
    *,
    agency_id: uuid.UUID,
    actor_id: uuid.UUID,
    group_id: uuid.UUID,
    upload_id: uuid.UUID,
    chunk_id: uuid.UUID,
    document_type: str,
    roster_fingerprint: str,
    source_fingerprint: str,
    identifiers_fingerprint: str,
    storage: MinioStorageRepository | None = None,
    cipher: VerificationReceiptCipher | None = None,
    now: datetime | None = None,
) -> list[str] | None:
    """Stage accepted PDFs and return aligned opaque receipts.

    ``None`` is a safe compatibility fallback when extracted text is too large
    for bounded form receipts; callers keep the legacy multipart upload path.
    """

    if not inputs:
        return []
    if document_type not in DOCUMENT_TYPES or any(
        not item.classification.accepted for item in inputs
    ):
        raise ValueError("Only accepted travel documents can be staged")
    timestamp = (now or datetime.now(tz=UTC)).replace(microsecond=0)
    expires_at = timestamp + VERIFICATION_RECEIPT_TTL
    active_cipher = cipher or VerificationReceiptCipher()
    receipts: list[StagedDocumentReceipt] = []
    tokens: list[str] = []
    decoded_payload_bytes = 0
    for item in inputs:
        receipt_id = uuid.uuid4()
        storage_key = _staging_storage_key(
            agency_id=agency_id,
            actor_id=actor_id,
            receipt_id=receipt_id,
        )
        receipt = StagedDocumentReceipt(
            receipt_id=receipt_id,
            agency_id=agency_id,
            actor_id=actor_id,
            group_id=group_id,
            upload_id=upload_id,
            chunk_id=chunk_id,
            document_type=document_type,
            expires_at=expires_at,
            storage_key=storage_key,
            filename=item.filename,
            content_type=item.content_type or "application/pdf",
            byte_count=len(item.content),
            content_sha256=hashlib.sha256(item.content).hexdigest(),
            roster_fingerprint=roster_fingerprint,
            source_fingerprint=source_fingerprint,
            identifiers_fingerprint=identifiers_fingerprint,
            classification=item.classification,
        )
        receipt_payload_bytes = len(_serialized_receipt_payload(receipt))
        decoded_payload_bytes += receipt_payload_bytes
        if (
            receipt_payload_bytes > MAX_VERIFICATION_RECEIPT_PAYLOAD
            or decoded_payload_bytes > MAX_VERIFICATION_RECEIPT_DECODED_BATCH_BYTES
        ):
            return None
        token = active_cipher.encrypt(receipt)
        if len(token) > MAX_VERIFICATION_RECEIPT_LENGTH:
            return None
        receipts.append(receipt)
        tokens.append(token)
    if sum(len(token.encode("ascii")) for token in tokens) > MAX_VERIFICATION_RECEIPT_BATCH_BYTES:
        return None

    active_storage = storage or MinioStorageRepository()
    storage_keys = [receipt.storage_key for receipt in receipts]

    def upload_operation(
        item: VerificationStagingInput, receipt: StagedDocumentReceipt
    ) -> Callable[[], Awaitable[str]]:
        return lambda: active_storage.upload_file(
            item.content,
            receipt.storage_key,
            item.content_type or "application/pdf",
        )

    async def cleanup() -> None:
        try:
            await active_storage.delete_files(storage_keys)
        except Exception as exc:
            logger.error(
                "document_verification_staging_cleanup_failed",
                object_count=len(storage_keys),
                error_type=type(exc).__name__,
            )

    try:
        # Commit the encrypted tombstone before the first object write so a
        # process exit cannot strand sensitive staging bytes between storage
        # upload and cleanup-job persistence. Missing-object deletion is
        # idempotent, so this also safely covers partial uploads and eager
        # finalize cleanup.
        await persist_storage_cleanup_job(
            agency_id=agency_id,
            source="document_verification_staging",
            context_id=str(receipts[0].receipt_id),
            storage_keys=storage_keys,
            not_before=expires_at,
        )
        await run_bounded_storage_operations(
            [
                upload_operation(item, receipt)
                for item, receipt in zip(inputs, receipts, strict=True)
            ]
        )
    except BaseException:
        await finish_cleanup_despite_cancellation(cleanup())
        raise
    return tokens


def decode_verification_receipts(
    tokens: list[str],
    *,
    agency_id: uuid.UUID,
    actor_id: uuid.UUID,
    group_id: uuid.UUID,
    upload_id: uuid.UUID,
    chunk_id: uuid.UUID,
    document_type: str,
    roster_fingerprint: str,
    source_fingerprint: str,
    identifiers_fingerprint: str,
    cipher: VerificationReceiptCipher | None = None,
    now: datetime | None = None,
) -> list[StagedDocumentReceipt]:
    active_cipher = cipher or VerificationReceiptCipher()
    timestamp = now or datetime.now(tz=UTC)
    receipts: list[StagedDocumentReceipt] = []
    decoded_payload_bytes = 0
    for token in tokens:
        receipt = active_cipher.decrypt(token)
        decoded_payload_bytes += len(_serialized_receipt_payload(receipt))
        if decoded_payload_bytes > MAX_VERIFICATION_RECEIPT_DECODED_BATCH_BYTES:
            raise VerificationReceiptBatchTooLargeError(
                "The document verification receipts are too large. Check the PDFs again."
            )
        receipts.append(receipt)
    seen_receipts: set[uuid.UUID] = set()
    for receipt in receipts:
        expected_key = _staging_storage_key(
            agency_id=receipt.agency_id,
            actor_id=receipt.actor_id,
            receipt_id=receipt.receipt_id,
        )
        if (
            receipt.receipt_id in seen_receipts
            or receipt.agency_id != agency_id
            or receipt.actor_id != actor_id
            or receipt.group_id != group_id
            or receipt.upload_id != upload_id
            or receipt.chunk_id != chunk_id
            or receipt.document_type != document_type
            or receipt.storage_key != expected_key
        ):
            raise VerificationReceiptError(
                "The document verification receipt is outside this upload scope"
            )
        seen_receipts.add(receipt.receipt_id)
    storage_keys = tuple(receipt.storage_key for receipt in receipts)
    if any(
        receipt.roster_fingerprint != roster_fingerprint
        or receipt.source_fingerprint != source_fingerprint
        or receipt.identifiers_fingerprint != identifiers_fingerprint
        for receipt in receipts
    ):
        raise VerificationReceiptScopeChangedError(
            "This group's passenger or linked WhatsApp details changed after the PDFs were checked. "
            "Check them again before uploading.",
            storage_keys=storage_keys,
        )
    if any(receipt.expires_at <= timestamp for receipt in receipts):
        raise VerificationReceiptExpiredError(
            "The document check expired. Check the PDFs again.",
            storage_keys=storage_keys,
        )
    return receipts


def staged_document_chunk_fingerprint(receipts: list[StagedDocumentReceipt]) -> str:
    digest = hashlib.sha256(b"document-verification-staging-chunk-v1\x00")
    for receipt in receipts:
        filename = receipt.filename.encode("utf-8")
        digest.update(len(filename).to_bytes(4, "big"))
        digest.update(filename)
        digest.update(receipt.byte_count.to_bytes(8, "big"))
        digest.update(bytes.fromhex(receipt.content_sha256))
    return digest.hexdigest()


async def cleanup_staged_storage_keys(
    storage_keys: list[str] | tuple[str, ...],
    *,
    storage: MinioStorageRepository | None = None,
) -> None:
    keys = list(dict.fromkeys(storage_keys))
    if not keys:
        return
    if any(not key.startswith(f"{VERIFICATION_STAGING_PREFIX}/") for key in keys):
        raise ValueError("Staging cleanup keys are outside the verification namespace")
    try:
        await (storage or MinioStorageRepository()).delete_files(keys)
    except Exception as exc:
        # A durable, encrypted tombstone was committed when staging succeeded.
        logger.warning(
            "document_verification_staging_eager_cleanup_deferred",
            object_count=len(keys),
            error_type=type(exc).__name__,
        )


def _receipt_payload(receipt: StagedDocumentReceipt) -> dict[str, object]:
    classification = receipt.classification
    return {
        "v": VERIFICATION_RECEIPT_VERSION,
        "receipt_id": str(receipt.receipt_id),
        "agency_id": str(receipt.agency_id),
        "actor_id": str(receipt.actor_id),
        "group_id": str(receipt.group_id),
        "upload_id": str(receipt.upload_id),
        "chunk_id": str(receipt.chunk_id),
        "document_type": receipt.document_type,
        "expires_at": int(receipt.expires_at.timestamp()),
        "storage_key": receipt.storage_key,
        "filename": receipt.filename,
        "content_type": receipt.content_type,
        "byte_count": receipt.byte_count,
        "content_sha256": receipt.content_sha256,
        "roster_fingerprint": receipt.roster_fingerprint,
        "source_fingerprint": receipt.source_fingerprint,
        "identifiers_fingerprint": receipt.identifiers_fingerprint,
        "classification": {
            "original_filename": classification.original_filename,
            "detected_type": classification.detected_type,
            "accepted": classification.accepted,
            "reason": classification.reason,
            "text": classification.text,
            "extracted_name": classification.extracted_name,
            "extracted_passport_number": classification.extracted_passport_number,
            "extracted_reference": classification.extracted_reference,
        },
    }


def _receipt_from_payload(value: object) -> StagedDocumentReceipt:
    if not isinstance(value, dict) or set(value) != {
        "v",
        "receipt_id",
        "agency_id",
        "actor_id",
        "group_id",
        "upload_id",
        "chunk_id",
        "document_type",
        "expires_at",
        "storage_key",
        "filename",
        "content_type",
        "byte_count",
        "content_sha256",
        "roster_fingerprint",
        "source_fingerprint",
        "identifiers_fingerprint",
        "classification",
    }:
        raise VerificationReceiptError("The document verification receipt is invalid")
    classification_value = value["classification"]
    if not isinstance(classification_value, dict) or set(classification_value) != {
        "original_filename",
        "detected_type",
        "accepted",
        "reason",
        "text",
        "extracted_name",
        "extracted_passport_number",
        "extracted_reference",
    }:
        raise VerificationReceiptError("The document verification receipt is invalid")
    try:
        receipt = StagedDocumentReceipt(
            receipt_id=uuid.UUID(str(value["receipt_id"])),
            agency_id=uuid.UUID(str(value["agency_id"])),
            actor_id=uuid.UUID(str(value["actor_id"])),
            group_id=uuid.UUID(str(value["group_id"])),
            upload_id=uuid.UUID(str(value["upload_id"])),
            chunk_id=uuid.UUID(str(value["chunk_id"])),
            document_type=str(value["document_type"]),
            expires_at=datetime.fromtimestamp(int(value["expires_at"]), tz=UTC),
            storage_key=str(value["storage_key"]),
            filename=str(value["filename"]),
            content_type=str(value["content_type"]),
            byte_count=int(value["byte_count"]),
            content_sha256=str(value["content_sha256"]),
            roster_fingerprint=str(value["roster_fingerprint"]),
            source_fingerprint=str(value["source_fingerprint"]),
            identifiers_fingerprint=str(value["identifiers_fingerprint"]),
            classification=ClassifiedDocument(
                original_filename=str(classification_value["original_filename"]),
                detected_type=str(classification_value["detected_type"]),
                accepted=classification_value["accepted"] is True,
                reason=str(classification_value["reason"]),
                text=str(classification_value["text"]),
                extracted_name=_optional_string(classification_value["extracted_name"]),
                extracted_passport_number=_optional_string(
                    classification_value["extracted_passport_number"]
                ),
                extracted_reference=_optional_string(classification_value["extracted_reference"]),
            ),
        )
    except (TypeError, ValueError, OverflowError) as exc:
        raise VerificationReceiptError("The document verification receipt is invalid") from exc
    if (
        value["v"] != VERIFICATION_RECEIPT_VERSION
        or receipt.document_type not in DOCUMENT_TYPES
        or not receipt.classification.accepted
        or receipt.classification.original_filename != receipt.filename
        or receipt.byte_count <= 0
        or receipt.byte_count > 64 * 1024 * 1024
        or not _SHA256_PATTERN.fullmatch(receipt.content_sha256)
        or any(
            not _SHA256_PATTERN.fullmatch(fingerprint)
            for fingerprint in (
                receipt.roster_fingerprint,
                receipt.source_fingerprint,
                receipt.identifiers_fingerprint,
            )
        )
        or len(receipt.filename) > 255
        or receipt.content_type != "application/pdf"
    ):
        raise VerificationReceiptError("The document verification receipt is invalid")
    return receipt


def _serialized_receipt_payload(receipt: StagedDocumentReceipt) -> bytes:
    return json.dumps(
        _receipt_payload(receipt),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Expected an optional string")
    return value
