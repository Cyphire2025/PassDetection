"""Verification receipt models."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.infrastructure.documents.document_matcher import ClassifiedDocument

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


VerificationReceiptError.__module__ = "app.infrastructure.documents.verification_staging"
VerificationReceiptExpiredError.__module__ = "app.infrastructure.documents.verification_staging"
VerificationReceiptScopeChangedError.__module__ = "app.infrastructure.documents.verification_staging"
VerificationReceiptBatchTooLargeError.__module__ = "app.infrastructure.documents.verification_staging"
VerificationStagingInput.__module__ = "app.infrastructure.documents.verification_staging"
StagedDocumentReceipt.__module__ = "app.infrastructure.documents.verification_staging"
