"""Canonical object-key collection for permanent passport-data removal."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

PASSPORT_OBJECT_KEY_ATTRIBUTES = (
    "image_s3_key",
    "thumbnail_s3_key",
    "passport_back_s3_key",
    "passport_cover_s3_key",
    "passport_back_cover_s3_key",
    "passport_photo_s3_key",
)


def passport_storage_keys(submissions: Iterable[Any]) -> list[str]:
    """Collect every referenced passport image object without duplicates."""

    keys: list[str] = []
    seen: set[str] = set()
    for submission in submissions:
        for attribute in PASSPORT_OBJECT_KEY_ATTRIBUTES:
            key = getattr(submission, attribute, None)
            if isinstance(key, str) and key and key not in seen:
                keys.append(key)
                seen.add(key)
    return keys
