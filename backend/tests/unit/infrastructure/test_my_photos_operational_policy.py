"""Reject malformed provider output before durable media or face publication."""

import uuid
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.application.my_photos.limits import MAX_MY_PHOTOS_MEDIA_BYTES
from app.application.my_photos.providers import (
    CanonicalFaceBox,
    FaceIndexAsset,
    FaceIndexBatchResult,
    FaceIndexFailure,
    IndexedFaceOccurrence,
    MediaAvailabilityResult,
)
from app.core.config.settings import MyPhotosSettings
from app.infrastructure.my_photos.operational_job_policy import (
    _retry_delay,
    _validated_index_result,
    _validated_media_result,
)

MEDIA = MediaAvailabilityResult(
    state="delivery_available",
    delivery_version=1,
    byte_size=1234,
    checksum_sha256="a" * 64,
    storage_reference="synthetic-private-reference",
    content_type="image/jpeg",
    width=640,
    height=480,
)


@pytest.mark.parametrize(
    "changes",
    [
        {"delivery_version": 0},
        {"state": "preparing_delivery"},
        {"byte_size": None},
        {"byte_size": 0},
        {"byte_size": MAX_MY_PHOTOS_MEDIA_BYTES + 1},
        {"checksum_sha256": None},
        {"checksum_sha256": "a" * 63},
        {"checksum_sha256": "A" * 64},
        {"storage_reference": None},
        {"storage_reference": "https://synthetic-private-location"},
        {"content_type": "text/html"},
        {"width": None},
        {"width": 0},
        {"width": 100001},
        {"height": None},
        {"height": 0},
        {"height": 100001},
    ],
)
def test_media_publication_rejects_incomplete_or_invalid_integrity_metadata(changes):
    with pytest.raises(ValueError):
        _validated_media_result(replace(MEDIA, **changes), variant="preview")


def test_media_boundary_preserves_valid_and_non_delivery_results():
    assert _validated_media_result(MEDIA, variant="preview") is MEDIA
    preparing = MediaAvailabilityResult(
        state="preparing_delivery", delivery_version=1, byte_size=None, checksum_sha256=None
    )
    assert _validated_media_result(preparing, variant="preview") is preparing


ASSET = FaceIndexAsset("synthetic-asset", "synthetic-analysis", "synthetic-input-identity")
FACE = IndexedFaceOccurrence(
    asset_identity=ASSET.asset_identity,
    provider_face_reference="synthetic-face",
    bounding_box=CanonicalFaceBox(0.1, 0.1, 0.3, 0.3),
    quality_score=90,
    provider_model_version="7.0",
    idempotency_identity="synthetic-face-identity",
)


@pytest.mark.parametrize(
    "changes",
    [
        {"asset_identity": "foreign-asset"},
        {"provider_face_reference": "https://synthetic-private-location"},
        {"idempotency_identity": ""},
        {"provider_model_version": "x" * 65},
        {"bounding_box": CanonicalFaceBox(-0.1, 0.1, 0.3, 0.3)},
        {"bounding_box": CanonicalFaceBox(0.1, -0.1, 0.3, 0.3)},
        {"bounding_box": CanonicalFaceBox(0.1, 0.1, 0, 0.3)},
        {"bounding_box": CanonicalFaceBox(0.1, 0.1, 0.3, 0)},
        {"bounding_box": CanonicalFaceBox(0.9, 0.1, 0.3, 0.3)},
        {"bounding_box": CanonicalFaceBox(0.1, 0.9, 0.3, 0.3)},
        {"quality_score": float("nan")},
        {"quality_score": 101},
    ],
)
def test_face_publication_rejects_foreign_or_invalid_occurrences(changes):
    result = FaceIndexBatchResult(occurrences=(replace(FACE, **changes),), failures=())
    with pytest.raises(ValueError):
        _validated_index_result(result, (ASSET,))


@pytest.mark.parametrize(
    "result",
    [
        FaceIndexBatchResult(occurrences=(FACE,) * 101, failures=()),
        FaceIndexBatchResult(occurrences=(FACE, FACE), failures=()),
        FaceIndexBatchResult(
            occurrences=(FACE, replace(FACE, provider_face_reference="synthetic-other-face")),
            failures=(),
        ),
        FaceIndexBatchResult((), (FaceIndexFailure("foreign", "NO_FACE"),)),
        FaceIndexBatchResult((), (FaceIndexFailure(ASSET.asset_identity, "private raw details"),)),
        FaceIndexBatchResult((FACE,), (FaceIndexFailure(ASSET.asset_identity, "NO_FACE"),)),
        FaceIndexBatchResult((), (FaceIndexFailure(ASSET.asset_identity, "NO_FACE"),) * 2),
    ],
)
def test_face_batch_rejects_duplicate_unbounded_or_contradictory_results(result):
    with pytest.raises(ValueError):
        _validated_index_result(result, (ASSET,))


def test_valid_face_results_and_retry_jitter_stay_deterministic_and_bounded():
    for result in (
        FaceIndexBatchResult((FACE,), ()),
        FaceIndexBatchResult((), (FaceIndexFailure(ASSET.asset_identity, "NO_FACE"),)),
    ):
        assert _validated_index_result(result, (ASSET,)) is result
    settings = SimpleNamespace(my_photos=MyPhotosSettings(_env_file=None))
    job_id = uuid.uuid4()
    for attempt in (0, 1, 2, 20):
        delay = _retry_delay(job_id, attempt, settings)
        assert delay == _retry_delay(job_id, attempt, settings)
        assert 1 <= delay <= settings.my_photos.job_retry_max_seconds
