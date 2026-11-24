"""Storage cleanup policy: focused encrypted tombstone owner."""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.core.config.settings import get_settings

from .storage_cleanup_types import (
    StorageCleanupPayloadError,
)

STORAGE_CLEANUP_KEY_VERSION = 1
STORAGE_CLEANUP_LEASE_SECONDS = 300
MAX_STORAGE_CLEANUP_KEYS = 2_000
MAX_STORAGE_CLEANUP_KEY_LENGTH = 512
MAX_STORAGE_CLEANUP_ATTEMPTS = 12
STORAGE_CLEANUP_SOURCES: dict[str, tuple[str, ...]] = {
    "branding_image": ("branding/",),
    "returning_draft_discard": ("returning-drafts/",),
    "company_data_export_expiry": ("company-data-exports/",),
    "traveller_copy_revoked": ("travellers/",),
    "traveller_profile_withdrawal": ("travellers/",),
    "document_distribution_delete": ("document-distribution/",),
    "document_distribution_replace": (
        "document-distribution/",
        "email-integrations-canonical/",
    ),
    "document_distribution_abort": ("document-distribution/",),
    "document_distribution_compensation": ("document-distribution/",),
    "document_rename_batch_delete": ("document-rename/",),
    "document_rename_compensation": ("document-rename/",),
    "document_verification_staging": ("document-verification-staging/",),
    "passport_ai_generation_compensation": ("passport-ai-library/",),
    "untrusted_upload_quarantine": (),
    "passport_submission_delete": (
        "returning-drafts/",
        "travellers/",
        # Legacy deployments stored the four canonical submission images in
        # short top-level namespaces.  They remain ownership-bound because
        # keys are read only from the locked submission/crop rows selected for
        # deletion; accepting these prefixes keeps durable cleanup compatible
        # with retained production data.
        "front/",
        "thumbnail/",
        "back/",
        "photo/",
        "visa-photo/",
        "visa_photo/",
        "drafts/",
        "excel-imports/",
        "passport-bulk/",
        "passport-crops/",
        "passport-edits/",
        # Collected from the deleted submissions' image-library rows together
        # with edit sources, including AI variants never applied to the image.
        "passport-ai-library/",
        "passport-image-library/",
    ),
}
_UUID_PATH_SEGMENT = r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
_CANONICAL_PASSPORT_OBJECT_KEY = re.compile(
    rf"^{_UUID_PATH_SEGMENT}/{_UUID_PATH_SEGMENT}/{_UUID_PATH_SEGMENT}"
    r"(?:-(?:photo|back|cover|back_cover))?\.(?:jpe?g|png|webp)$",
    re.IGNORECASE,
)


def _validated_storage_keys(
    *,
    source: str,
    storage_keys: Sequence[str],
    max_keys: int | None = MAX_STORAGE_CLEANUP_KEYS,
) -> tuple[str, ...]:
    allowed_prefixes = STORAGE_CLEANUP_SOURCES.get(source)
    if allowed_prefixes is None:
        raise StorageCleanupPayloadError("Unsupported storage cleanup source")
    keys = tuple(dict.fromkeys(storage_keys))
    if not keys or (max_keys is not None and len(keys) > max_keys):
        raise StorageCleanupPayloadError("Storage cleanup object count is invalid")
    if any(
        not key
        or len(key) > MAX_STORAGE_CLEANUP_KEY_LENGTH
        or "\x00" in key
        or not _storage_key_matches_source(
            source=source,
            key=key,
            allowed_prefixes=allowed_prefixes,
        )
        for key in keys
    ):
        raise StorageCleanupPayloadError("Storage cleanup object scope is invalid")
    return keys


def _storage_key_matches_source(
    *,
    source: str,
    key: str,
    allowed_prefixes: tuple[str, ...],
) -> bool:
    if source == "untrusted_upload_quarantine":
        configured_prefix = get_settings().malware_quarantine_prefix.rstrip("/") + "/"
        return key.startswith(configured_prefix)
    if key.startswith(allowed_prefixes):
        return True
    return bool(
        source == "passport_submission_delete" and _CANONICAL_PASSPORT_OBJECT_KEY.fullmatch(key)
    )


_validated_storage_keys.__module__ = "app.infrastructure.documents.storage_cleanup"

_storage_key_matches_source.__module__ = "app.infrastructure.documents.storage_cleanup"
