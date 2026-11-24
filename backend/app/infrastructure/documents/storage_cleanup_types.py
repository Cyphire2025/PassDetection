"""Storage cleanup types: focused encrypted tombstone owner."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


class StorageCleanupPayloadError(ValueError):
    """Raised when a cleanup tombstone cannot be created or decrypted safely."""


class StorageCleanupIncompleteError(RuntimeError):
    """Raised when storage does not acknowledge every idempotent delete."""


@dataclass(frozen=True, slots=True)
class StorageCleanupClaim:
    job_id: uuid.UUID
    context_fingerprint: str
    ciphertext: bytes
    encryption_key_version: int
    source: str
    object_count: int
    attempts: int
    agency_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class StorageCleanupResult:
    job_id: uuid.UUID
    object_count: int
    deleted_count: int
    completed: bool


StorageCleanupPayloadError.__module__ = "app.infrastructure.documents.storage_cleanup"

StorageCleanupIncompleteError.__module__ = "app.infrastructure.documents.storage_cleanup"

StorageCleanupClaim.__module__ = "app.infrastructure.documents.storage_cleanup"
StorageCleanupClaim.__init__.__module__ = "app.infrastructure.documents.storage_cleanup"
StorageCleanupClaim.__repr__.__module__ = "app.infrastructure.documents.storage_cleanup"
StorageCleanupClaim.__eq__.__module__ = "app.infrastructure.documents.storage_cleanup"
StorageCleanupClaim.__setattr__.__module__ = "app.infrastructure.documents.storage_cleanup"
StorageCleanupClaim.__delattr__.__module__ = "app.infrastructure.documents.storage_cleanup"
StorageCleanupClaim.__hash__.__module__ = "app.infrastructure.documents.storage_cleanup"

StorageCleanupResult.__module__ = "app.infrastructure.documents.storage_cleanup"
StorageCleanupResult.__init__.__module__ = "app.infrastructure.documents.storage_cleanup"
StorageCleanupResult.__repr__.__module__ = "app.infrastructure.documents.storage_cleanup"
StorageCleanupResult.__eq__.__module__ = "app.infrastructure.documents.storage_cleanup"
StorageCleanupResult.__setattr__.__module__ = "app.infrastructure.documents.storage_cleanup"
StorageCleanupResult.__delattr__.__module__ = "app.infrastructure.documents.storage_cleanup"
StorageCleanupResult.__hash__.__module__ = "app.infrastructure.documents.storage_cleanup"
