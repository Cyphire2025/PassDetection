"""Bounded Rekognition result validation and canonical face projections."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping
from typing import cast

from app.application.my_photos.errors import MyPhotosUnavailable
from app.application.my_photos.providers import (
    CanonicalFaceBox,
    FaceIndexAsset,
    IndexedFaceOccurrence,
)
from app.infrastructure.my_photos.aws_references import (
    _valid_s3_version_id,
)

_FACE_ID = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")


_PERMANENT_INDEX_FAILURES = {
    "ImageTooLargeException": "IMAGE_TOO_LARGE",
    "InvalidImageFormatException": "IMAGE_FORMAT_INVALID",
    "InvalidParameterException": "IMAGE_INVALID",
    "InvalidS3ObjectException": "MEDIA_OBJECT_INVALID",
}


def _indexed_occurrence(
    record: object,
    *,
    asset: FaceIndexAsset,
    model_version: str,
) -> IndexedFaceOccurrence:
    if not isinstance(record, Mapping):
        raise MyPhotosUnavailable(
            "MY_PHOTOS_PROVIDER_RESULT_INVALID", "Face indexing is temporarily unavailable."
        )
    face = record.get("Face")
    if not isinstance(face, Mapping):
        raise MyPhotosUnavailable(
            "MY_PHOTOS_PROVIDER_RESULT_INVALID", "Face indexing is temporarily unavailable."
        )
    face_id = str(face.get("FaceId", ""))
    box = face.get("BoundingBox")
    confidence = face.get("Confidence")
    if _FACE_ID.fullmatch(face_id) is None or not isinstance(box, Mapping):
        raise MyPhotosUnavailable(
            "MY_PHOTOS_PROVIDER_RESULT_INVALID", "Face indexing is temporarily unavailable."
        )
    values: list[float] = []
    for name in ("Left", "Top", "Width", "Height"):
        value = box.get(name)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or not 0 <= float(value) <= 1
        ):
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_RESULT_INVALID", "Face indexing is temporarily unavailable."
            )
        values.append(float(value))
    quality: float | None = None
    if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
        quality = float(confidence)
        if not math.isfinite(quality) or not 0 <= quality <= 100:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_RESULT_INVALID", "Face indexing is temporarily unavailable."
            )
    idempotency = hashlib.sha256(
        f"{asset.idempotency_identity}|{face_id}".encode("utf-8")
    ).hexdigest()
    return IndexedFaceOccurrence(
        asset_identity=asset.asset_identity,
        provider_face_reference=face_id,
        bounding_box=CanonicalFaceBox(
            left=values[0],
            top=values[1],
            width=values[2],
            height=values[3],
        ),
        quality_score=quality,
        provider_model_version=model_version,
        idempotency_identity=f"aws-index:{idempotency}",
    )


def _unindexed_reason(response: Mapping[str, object]) -> str:
    unindexed = response.get("UnindexedFaces", ())
    if not isinstance(unindexed, (list, tuple)) or not unindexed:
        return "NO_FACE"
    first = unindexed[0]
    if not isinstance(first, Mapping):
        return "FACE_NOT_INDEXED"
    reasons = first.get("Reasons", ())
    if not isinstance(reasons, (list, tuple)):
        return "FACE_NOT_INDEXED"
    normalized = {str(reason) for reason in reasons}
    if "EXCEEDS_MAX_FACES" in normalized:
        return "FACE_LIMIT_EXCEEDED"
    if normalized & {
        "LOW_BRIGHTNESS",
        "LOW_SHARPNESS",
        "LOW_CONFIDENCE",
        "EXTREME_POSE",
        "FACE_OCCLUDED",
    }:
        return "FACE_QUALITY_INSUFFICIENT"
    return "FACE_NOT_INDEXED"


def _provider_model_version(response: Mapping[str, object]) -> str:
    value = response.get("FaceModelVersion") or response.get("FaceModelVersionNumber")
    if not isinstance(value, str) or not value or len(value) > 64 or not value.isprintable():
        raise MyPhotosUnavailable(
            "MY_PHOTOS_PROVIDER_RESULT_INVALID", "Face provider is temporarily unavailable."
        )
    return value


def _s3_image_from_liveness_response(
    response: Mapping[str, object],
    *,
    expected_bucket: str,
    expected_prefix: str,
) -> dict[str, str]:
    reference = response.get("ReferenceImage")
    if not isinstance(reference, Mapping):
        raise MyPhotosUnavailable(
            "MY_PHOTOS_REFERENCE_NO_FACE", "Face Scan did not return a usable face."
        )
    image = reference.get("S3Object")
    if not isinstance(image, Mapping):
        # Production always supplies OutputConfig so raw biometric bytes never
        # enter application memory or cross the domain adapter.
        raise MyPhotosUnavailable(
            "MY_PHOTOS_PROVIDER_RESULT_INVALID",
            "Face Scan verification is temporarily unavailable.",
        )
    bucket = image.get("Bucket")
    name = image.get("Name")
    if (
        bucket != expected_bucket
        or not isinstance(name, str)
        or not name.startswith(f"{expected_prefix}/")
        or len(name) > 512
        or not name.isprintable()
        or ".." in name.split("/")
    ):
        raise MyPhotosUnavailable(
            "MY_PHOTOS_PROVIDER_RESULT_INVALID",
            "Face Scan verification is temporarily unavailable.",
        )
    result = {"Bucket": bucket, "Name": name}
    version = image.get("Version")
    if version is not None:
        if not _valid_s3_version_id(version):
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_RESULT_INVALID",
                "Face Scan verification is temporarily unavailable.",
            )
        result["Version"] = cast(str, version)
    return result
