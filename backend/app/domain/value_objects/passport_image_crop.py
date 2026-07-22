"""Non-destructive edit metadata for stored passport submission images."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class PassportImageType(StrEnum):
    """Staff-facing names for the three supported submission images."""

    VISA_PHOTO = "visa_photo"
    PASSPORT_FRONT = "passport_front"
    PASSPORT_BACK = "passport_back"


PASSPORT_IMAGE_STORAGE_ATTRIBUTES: dict[PassportImageType, str] = {
    PassportImageType.VISA_PHOTO: "passport_photo_s3_key",
    PassportImageType.PASSPORT_FRONT: "image_s3_key",
    PassportImageType.PASSPORT_BACK: "passport_back_s3_key",
}


@dataclass(frozen=True, slots=True)
class PassportImageCrop:
    """A crop rectangle in a rotated, EXIF-normalized source coordinate space.

    Rectangle coordinates are normalized fractions so metadata remains stable
    across browser display sizes. ``source_width`` and ``source_height`` bind
    the metadata to the exact canonical source geometry used when it was saved.
    """

    submission_id: uuid.UUID
    image_type: PassportImageType
    source_storage_key: str
    derived_storage_key: str | None
    active: bool
    x: float
    y: float
    width: float
    height: float
    rotation_degrees: int
    source_width: int
    source_height: int
    revision: int
    edit_source_storage_key: str | None = None
    sharpness: float = 1.0
    sharpness_algorithm_version: int = 1
    updated_by_user_id: uuid.UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


def passport_image_storage_key(submission: object, image_type: PassportImageType) -> str | None:
    """Return the immutable source key for one supported image type."""

    value = getattr(submission, PASSPORT_IMAGE_STORAGE_ATTRIBUTES[image_type], None)
    return value if isinstance(value, str) and value else None
