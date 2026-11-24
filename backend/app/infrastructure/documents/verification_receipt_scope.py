"""Verification receipt scope."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from app.infrastructure.documents.verification_receipt_cipher import (
    VerificationReceiptCipher,
)
from app.infrastructure.documents.verification_receipt_models import (
    MAX_VERIFICATION_RECEIPT_BATCH_BYTES,
    MAX_VERIFICATION_RECEIPT_DECODED_BATCH_BYTES,
    MAX_VERIFICATION_RECEIPT_LENGTH,
    VERIFICATION_STAGING_PREFIX,
    StagedDocumentReceipt,
    VerificationReceiptBatchTooLargeError,
    VerificationReceiptError,
    VerificationReceiptExpiredError,
    VerificationReceiptScopeChangedError,
)
from app.infrastructure.documents.verification_receipt_payload import (
    _serialized_receipt_payload,
)


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


_staging_storage_key.__module__ = "app.infrastructure.documents.verification_staging"
_scope_fingerprint.__module__ = "app.infrastructure.documents.verification_staging"
verification_scope_fingerprints.__module__ = "app.infrastructure.documents.verification_staging"
validate_verification_receipt_token_batch.__module__ = "app.infrastructure.documents.verification_staging"
decode_verification_receipts.__module__ = "app.infrastructure.documents.verification_staging"
staged_document_chunk_fingerprint.__module__ = "app.infrastructure.documents.verification_staging"
