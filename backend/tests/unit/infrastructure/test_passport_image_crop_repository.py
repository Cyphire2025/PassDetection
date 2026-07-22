from __future__ import annotations

import uuid

import pytest

from app.domain.value_objects.passport_image_crop import PassportImageType
from app.infrastructure.repositories.passport_image_crop_repository import (
    PassportImageCropRepository,
    PassportImageCropRevisionConflict,
)


class _ScalarResult:
    def __init__(self, value):  # type: ignore[no-untyped-def]
        self._value = value

    def scalar_one_or_none(self):  # type: ignore[no-untyped-def]
        return self._value


class _MemorySession:
    def __init__(self) -> None:
        self.model = None
        self.flush_count = 0

    async def execute(self, _stmt):  # type: ignore[no-untyped-def]
        return _ScalarResult(self.model)

    def add(self, model) -> None:  # type: ignore[no-untyped-def]
        self.model = model

    async def flush(self) -> None:
        self.flush_count += 1


@pytest.mark.asyncio
async def test_revision_is_monotonic_across_reset_and_recrop() -> None:
    session = _MemorySession()
    repository = PassportImageCropRepository(session)  # type: ignore[arg-type]
    submission_id = uuid.uuid4()
    user_id = uuid.uuid4()

    first, previous, previous_edit = await repository.upsert(
        submission_id=submission_id,
        image_type=PassportImageType.PASSPORT_FRONT,
        source_storage_key="original/front-v1.jpg",
        edit_source_storage_key=None,
        derived_storage_key="derived/front-r1.jpg",
        x=0.1,
        y=0.1,
        width=0.8,
        height=0.8,
        rotation_degrees=0,
        sharpness=1.0,
        source_width=1000,
        source_height=700,
        updated_by_user_id=user_id,
        expected_revision=0,
    )
    assert first.revision == 1
    assert first.active is True
    assert previous is None
    assert previous_edit is None

    reset, removed, removed_edit = await repository.reset(
        submission_id=submission_id,
        image_type=PassportImageType.PASSPORT_FRONT,
        updated_by_user_id=user_id,
        expected_revision=1,
    )
    assert reset is not None
    assert reset.revision == 2
    assert reset.active is False
    assert removed == "derived/front-r1.jpg"
    assert removed_edit is None

    # Resetting an already-reset image is idempotent and does not create an
    # ABA revision window.
    repeated, removed_again, removed_edit_again = await repository.reset(
        submission_id=submission_id,
        image_type=PassportImageType.PASSPORT_FRONT,
        updated_by_user_id=user_id,
        expected_revision=2,
    )
    assert repeated is not None
    assert repeated.revision == 2
    assert removed_again is None
    assert removed_edit_again is None

    with pytest.raises(PassportImageCropRevisionConflict) as stale:
        await repository.upsert(
            submission_id=submission_id,
            image_type=PassportImageType.PASSPORT_FRONT,
            source_storage_key="original/front-v1.jpg",
            edit_source_storage_key=None,
            derived_storage_key="derived/stale.jpg",
            x=0.1,
            y=0.1,
            width=0.8,
            height=0.8,
            rotation_degrees=0,
            sharpness=1.0,
            source_width=1000,
            source_height=700,
            updated_by_user_id=user_id,
            expected_revision=1,
        )
    assert stale.value.current_revision == 2

    third, _, _ = await repository.upsert(
        submission_id=submission_id,
        image_type=PassportImageType.PASSPORT_FRONT,
        source_storage_key="original/front-v2.jpg",
        edit_source_storage_key=None,
        derived_storage_key="derived/front-r3.jpg",
        x=0.0,
        y=0.0,
        width=1.0,
        height=1.0,
        rotation_degrees=90,
        sharpness=1.5,
        source_width=700,
        source_height=1000,
        updated_by_user_id=user_id,
        expected_revision=2,
    )
    assert third.revision == 3
    assert third.active is True
    assert third.source_storage_key == "original/front-v2.jpg"
    assert third.sharpness == 1.5
