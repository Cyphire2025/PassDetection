"""Verification receipt payload."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from app.domain.value_objects.travel_document_taxonomy import DOCUMENT_TYPES
from app.infrastructure.documents.document_matcher import ClassifiedDocument
from app.infrastructure.documents.verification_receipt_models import (
    _SHA256_PATTERN,
    VERIFICATION_RECEIPT_VERSION,
    StagedDocumentReceipt,
    VerificationReceiptError,
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


_receipt_payload.__module__ = "app.infrastructure.documents.verification_staging"
_receipt_from_payload.__module__ = "app.infrastructure.documents.verification_staging"
_serialized_receipt_payload.__module__ = "app.infrastructure.documents.verification_staging"
_optional_string.__module__ = "app.infrastructure.documents.verification_staging"
