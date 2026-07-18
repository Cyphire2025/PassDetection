from __future__ import annotations

from types import SimpleNamespace

from app.infrastructure.storage.passport_object_keys import (
    PASSPORT_OBJECT_KEY_ATTRIBUTES,
    passport_storage_keys,
)


def test_all_passport_object_variants_have_one_canonical_cleanup_contract() -> None:
    submission = SimpleNamespace(
        image_s3_key="front/original.jpg",
        thumbnail_s3_key="front/thumbnail.jpg",
        passport_back_s3_key="back/original.jpg",
        passport_photo_s3_key="visa/original.jpg",
    )

    assert PASSPORT_OBJECT_KEY_ATTRIBUTES == (
        "image_s3_key",
        "thumbnail_s3_key",
        "passport_back_s3_key",
        "passport_photo_s3_key",
    )
    assert passport_storage_keys([submission, submission]) == [
        "front/original.jpg",
        "front/thumbnail.jpg",
        "back/original.jpg",
        "visa/original.jpg",
    ]
