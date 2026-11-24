"""Versioned S3 media integrity, encryption and metadata validation."""

from __future__ import annotations

import base64
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from app.application.my_photos.errors import MyPhotosUnavailable
from app.application.my_photos.limits import MAX_MY_PHOTOS_MEDIA_BYTES
from app.infrastructure.my_photos.aws_references import (
    _valid_s3_version_id,
)

_CHECKSUM = re.compile(r"^[0-9a-f]{64}$")


_SUPPORTED_MIME = {"image/jpeg", "image/png", "image/webp"}


class _MediaObjectNotFound(Exception):
    pass


@dataclass(frozen=True, slots=True)
class _MediaMetadata:
    size: int
    checksum: str
    content_type: str
    width: int
    height: int
    delivery_version: int
    version_id: str


def _media_metadata(
    response: Mapping[str, object],
    *,
    expected_kms_key_id: str,
    expected_version_id: str | None,
) -> _MediaMetadata:
    size = response.get("ContentLength")
    content_type = response.get("ContentType")
    metadata = response.get("Metadata")
    if (
        isinstance(size, bool)
        or not isinstance(size, int)
        or not 1 <= size <= MAX_MY_PHOTOS_MEDIA_BYTES
        or content_type not in _SUPPORTED_MIME
        or not isinstance(metadata, Mapping)
        or response.get("ServerSideEncryption") != "aws:kms"
        or response.get("SSEKMSKeyId") != expected_kms_key_id
    ):
        raise MyPhotosUnavailable(
            "MY_PHOTOS_MEDIA_METADATA_INVALID", "Photo storage metadata is invalid."
        )
    checksum = metadata.get("sha256")
    native_checksum = _full_object_sha256(response)
    width = _positive_metadata_int(metadata.get("width"))
    height = _positive_metadata_int(metadata.get("height"))
    delivery_version = _positive_metadata_int(metadata.get("delivery-version", "1"))
    version_id = response.get("VersionId")
    if (
        not isinstance(checksum, str)
        or _CHECKSUM.fullmatch(checksum) is None
        or checksum != native_checksum
        or not _valid_s3_version_id(version_id)
        or (expected_version_id is not None and version_id != expected_version_id)
    ):
        raise MyPhotosUnavailable(
            "MY_PHOTOS_MEDIA_METADATA_INVALID", "Photo storage metadata is invalid."
        )
    return _MediaMetadata(
        size=size,
        checksum=checksum,
        content_type=content_type,
        width=width,
        height=height,
        delivery_version=delivery_version,
        version_id=cast(str, version_id),
    )


def _full_object_sha256(response: Mapping[str, object]) -> str:
    """Require uploader-supplied S3-native SHA-256 for a non-composite object."""

    encoded = response.get("ChecksumSHA256")
    if response.get("ChecksumType") != "FULL_OBJECT" or not isinstance(encoded, str):
        raise MyPhotosUnavailable(
            "MY_PHOTOS_MEDIA_CHECKSUM_INVALID",
            "Photo storage checksum is invalid.",
        )
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise MyPhotosUnavailable(
            "MY_PHOTOS_MEDIA_CHECKSUM_INVALID",
            "Photo storage checksum is invalid.",
        ) from exc
    if len(decoded) != 32 or base64.b64encode(decoded).decode("ascii") != encoded:
        raise MyPhotosUnavailable(
            "MY_PHOTOS_MEDIA_CHECKSUM_INVALID",
            "Photo storage checksum is invalid.",
        )
    return decoded.hex()


def _positive_metadata_int(value: object) -> int:
    try:
        parsed = int(cast(Any, value))
    except (TypeError, ValueError) as exc:
        raise MyPhotosUnavailable(
            "MY_PHOTOS_MEDIA_METADATA_INVALID", "Photo storage metadata is invalid."
        ) from exc
    if not 1 <= parsed <= 100_000:
        raise MyPhotosUnavailable(
            "MY_PHOTOS_MEDIA_METADATA_INVALID", "Photo storage metadata is invalid."
        )
    return parsed


def _require_media_integrity(
    metadata: _MediaMetadata,
    *,
    expected_size: int,
    expected_checksum: str,
    expected_content_type: str,
    expected_width: int | None = None,
    expected_height: int | None = None,
) -> None:
    if (
        metadata.size != expected_size
        or metadata.checksum != expected_checksum
        or metadata.content_type != expected_content_type
        or (expected_width is not None and metadata.width != expected_width)
        or (expected_height is not None and metadata.height != expected_height)
    ):
        raise MyPhotosUnavailable(
            "MY_PHOTOS_MEDIA_INTEGRITY_CHANGED", "Photo storage integrity check failed."
        )
