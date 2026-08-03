from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.value_objects.passport_image_crop import PassportImageType
from app.domain.value_objects.passport_image_library import (
    PassportImageLibraryItem,
    PassportImageLibrarySource,
)
from app.presentation.api.v1.router import api_v1_router
from app.presentation.api.v1.routes.passport_image_library import (
    list_passport_image_library,
    upload_passport_image_library_item,
    use_passport_image_library_item,
)
from app.presentation.api.v1.routes.passports import (
    _delete_ephemeral_edit_source_best_effort,
    _delete_unreferenced_passport_image_keys_best_effort,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportVisaAiImageUseRequest,
)


def _submission() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        image_s3_key="original/front.jpg",
        passport_photo_s3_key="original/visa.jpg",
        passport_back_s3_key="original/back.jpg",
        created_at=datetime.now(tz=UTC),
    )


def _item(
    submission_id: uuid.UUID,
    *,
    image_type: PassportImageType,
    source: PassportImageLibrarySource,
    storage_key: str,
    prompt: str | None = None,
    model: str | None = None,
) -> PassportImageLibraryItem:
    return PassportImageLibraryItem(
        id=uuid.uuid4(),
        submission_id=submission_id,
        image_type=image_type,
        source=source,
        storage_key=storage_key,
        original_source_storage_key="original/front.jpg",
        content_sha256="a" * 64 if source is not PassportImageLibrarySource.ORIGINAL else None,
        prompt=prompt,
        prompt_sha256="b" * 64 if prompt else None,
        model=model,
        created_by_user_id=uuid.uuid4(),
        created_at=datetime.now(tz=UTC),
    )


def test_common_library_routes_are_registered_under_passports() -> None:
    paths = {route.path for route in api_v1_router.routes}
    base = "/passports/{submission_id}/images/{image_type}/library"
    assert base in paths
    assert f"{base}/{{item_id}}/image" in paths
    assert f"{base}/{{item_id}}/use" in paths


@pytest.mark.asyncio
async def test_library_lists_original_manual_and_ai_with_current_item() -> None:
    submission = _submission()
    original = _item(
        submission.id,
        image_type=PassportImageType.PASSPORT_FRONT,
        source=PassportImageLibrarySource.ORIGINAL,
        storage_key=submission.image_s3_key,
    )
    manual = _item(
        submission.id,
        image_type=PassportImageType.PASSPORT_FRONT,
        source=PassportImageLibrarySource.MANUAL,
        storage_key="passport-image-library/manual.jpg",
    )
    ai_item = _item(
        submission.id,
        image_type=PassportImageType.PASSPORT_FRONT,
        source=PassportImageLibrarySource.AI_GENERATED,
        storage_key="passport-image-library/ai.jpg",
        prompt="Clean the background",
        model="gemini-image-edit",
    )
    library_repository = MagicMock()
    library_repository.ensure_original = AsyncMock(return_value=(original, False))
    library_repository.list_for_image = AsyncMock(
        return_value=[manual, ai_item, original]
    )
    crop_repository = MagicMock()
    crop_repository.get = AsyncMock(
        return_value=SimpleNamespace(
            active=True,
            derived_storage_key="passport-crops/current.jpg",
            source_storage_key=submission.image_s3_key,
            edit_source_storage_key=manual.storage_key,
        )
    )
    session = MagicMock()
    session.commit = AsyncMock()

    with (
        patch(
            "app.presentation.api.v1.routes.passport_image_library."
            "_authorized_staff_passport_image",
            new=AsyncMock(return_value=(submission, submission.image_s3_key)),
        ),
        patch(
            "app.presentation.api.v1.routes.passport_image_library."
            "PassportImageLibraryRepository",
            return_value=library_repository,
        ),
        patch(
            "app.presentation.api.v1.routes.passport_image_library."
            "PassportImageCropRepository",
            return_value=crop_repository,
        ),
        patch(
            "app.presentation.api.v1.routes.passport_image_library.get_settings",
            return_value=SimpleNamespace(api_v1_prefix="/api/v1"),
        ),
    ):
        response = await list_passport_image_library(
            submission_id=submission.id,
            image_type=PassportImageType.PASSPORT_FRONT,
            current_user=SimpleNamespace(),  # type: ignore[arg-type]
            session=session,
        )

    assert [item.source for item in response.items] == [
        "manual",
        "ai_generated",
        "original",
    ]
    assert response.items[0].is_current is True
    assert response.items[1].prompt == "Clean the background"
    assert response.items[2].is_current is False
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_manual_upload_is_saved_to_library_and_immediately_made_current() -> None:
    submission = _submission()
    submission.thumbnail_s3_key = "original/front-thumbnail.jpg"
    submission.promote_image = MagicMock(
        side_effect=lambda key: setattr(submission, "image_s3_key", key)
    )
    submission.update_reviewed_fields = MagicMock()
    current_user = SimpleNamespace(id=uuid.uuid4(), email="staff@example.com")
    validated = SimpleNamespace(
        content=b"canonical-manual-image",
        content_type="image/jpeg",
    )
    rendered = SimpleNamespace(
        content=b"derived-manual-image",
        content_type="image/jpeg",
        extension=".jpg",
        source_width=900,
        source_height=600,
    )
    storage = MagicMock()
    storage.upload_file = AsyncMock()
    storage.delete_files = AsyncMock()
    library_repository = MagicMock()
    library_repository.ensure_original = AsyncMock(
        return_value=(
            _item(
                submission.id,
                image_type=PassportImageType.PASSPORT_FRONT,
                source=PassportImageLibrarySource.ORIGINAL,
                storage_key=submission.image_s3_key,
            ),
            False,
        )
    )
    library_repository.create_manual = AsyncMock(
        side_effect=lambda **kwargs: _item(
            submission.id,
            image_type=PassportImageType.PASSPORT_FRONT,
            source=PassportImageLibrarySource.MANUAL,
            storage_key=kwargs["storage_key"],
        )
    )
    crop_row = SimpleNamespace(revision=2)
    crop_repository = MagicMock()
    crop_repository.upsert = AsyncMock(return_value=(crop_row, None, None))
    submission_repository = MagicMock()
    submission_repository.get_by_id_for_update = AsyncMock(return_value=submission)
    submission_repository.update = AsyncMock()
    reextract_result = SimpleNamespace(
        id=submission.id,
        processing_job_id=uuid.uuid4(),
    )
    reextract_use_case = MagicMock()
    reextract_use_case.execute = AsyncMock(return_value=reextract_result)
    audit_repository = MagicMock()
    audit_repository.record = AsyncMock()
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    async def dispatch_and_commit(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args
        await kwargs["session"].commit()

    with (
        patch(
            "app.presentation.api.v1.routes.passport_image_library."
            "_authorized_staff_passport_image",
            new=AsyncMock(return_value=(submission, submission.image_s3_key)),
        ),
        patch(
            "app.presentation.api.v1.routes.passport_image_library."
            "_validated_upload_file",
            new=AsyncMock(return_value=validated),
        ),
        patch(
            "app.presentation.api.v1.routes.passport_image_library."
            "render_passport_image_crop",
            return_value=rendered,
        ),
        patch(
            "app.presentation.api.v1.routes.passport_image_library."
            "MinioStorageRepository",
            return_value=storage,
        ),
        patch(
            "app.presentation.api.v1.routes.passport_image_library."
            "PassportImageLibraryRepository",
            return_value=library_repository,
        ),
        patch(
            "app.presentation.api.v1.routes.passport_image_library."
            "PassportImageCropRepository",
            return_value=crop_repository,
        ),
        patch(
            "app.presentation.api.v1.routes.passport_image_library."
            "PassportSubmissionRepository",
            return_value=submission_repository,
        ),
        patch(
            "app.presentation.api.v1.routes.passport_image_library."
            "ReextractPassportSubmissionUseCase",
            return_value=reextract_use_case,
        ),
        patch(
            "app.presentation.api.v1.routes.passport_image_library."
            "_dispatch_processing_job",
            new=AsyncMock(side_effect=dispatch_and_commit),
        ) as dispatch_processing_job,
        patch(
            "app.presentation.api.v1.routes.passport_image_library.AuditLogRepository",
            return_value=audit_repository,
        ),
        patch(
            "app.presentation.api.v1.routes.passport_image_library.get_settings",
            return_value=SimpleNamespace(api_v1_prefix="/api/v1"),
        ),
        patch(
            "app.presentation.api.v1.routes.passport_image_library."
            "propagate_mobile_passenger_change",
            new=AsyncMock(),
        ) as propagate_mobile_change,
    ):
        response = await upload_passport_image_library_item(
            submission_id=submission.id,
            image_type=PassportImageType.PASSPORT_FRONT,
            background_tasks=MagicMock(),
            image=MagicMock(),
            expected_revision=1,
            _csrf=None,
            current_user=current_user,  # type: ignore[arg-type]
            session=session,
        )

    assert storage.upload_file.await_count == 2
    first_upload = storage.upload_file.await_args_list[0]
    assert first_upload.args[0] == validated.content
    assert first_upload.args[1].endswith(".jpg")
    assert first_upload.args[2] == validated.content_type
    library_repository.create_manual.assert_awaited_once()
    upsert = crop_repository.upsert.await_args.kwargs
    assert upsert["edit_source_storage_key"] is None
    assert upsert["source_storage_key"].startswith("passport-image-library/")
    assert upsert["expected_revision"] == 1
    submission.promote_image.assert_called_once_with(upsert["source_storage_key"])
    submission.update_reviewed_fields.assert_called_once_with({})
    submission_repository.update.assert_awaited_once_with(submission)
    reextract_use_case.execute.assert_awaited_once_with(submission.id)
    dispatch_processing_job.assert_awaited_once()
    propagate_mobile_change.assert_awaited_once()
    assert response.source == "manual"
    assert response.is_current is True
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_use_library_item_is_scoped_and_updates_current_edit_source() -> None:
    submission = _submission()
    current_user = SimpleNamespace(id=uuid.uuid4(), email="staff@example.com")
    manual_item = _item(
        submission.id,
        image_type=PassportImageType.PASSPORT_BACK,
        source=PassportImageLibrarySource.MANUAL,
        storage_key="passport-image-library/back-manual.jpg",
    )
    storage = MagicMock()
    storage.get_file = AsyncMock(return_value=b"manual")
    storage.upload_file = AsyncMock()
    library_repository = MagicMock()
    library_repository.get_for_image = AsyncMock(return_value=manual_item)
    crop_repository = MagicMock()
    crop_repository.upsert = AsyncMock(
        return_value=(SimpleNamespace(revision=4), None, None)
    )
    submission_repository = MagicMock()
    submission_repository.get_by_id_for_update = AsyncMock(return_value=submission)
    audit_repository = MagicMock()
    audit_repository.record = AsyncMock()
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    rendered = SimpleNamespace(
        content=b"derived",
        content_type="image/jpeg",
        extension=".jpg",
        source_width=800,
        source_height=600,
    )
    expected_response = MagicMock()

    with (
        patch(
            "app.presentation.api.v1.routes.passport_image_library."
            "_authorized_staff_passport_image",
            new=AsyncMock(return_value=(submission, submission.passport_back_s3_key)),
        ),
        patch(
            "app.presentation.api.v1.routes.passport_image_library."
            "PassportImageLibraryRepository",
            return_value=library_repository,
        ),
        patch(
            "app.presentation.api.v1.routes.passport_image_library."
            "PassportImageCropRepository",
            return_value=crop_repository,
        ),
        patch(
            "app.presentation.api.v1.routes.passport_image_library."
            "PassportSubmissionRepository",
            return_value=submission_repository,
        ),
        patch(
            "app.presentation.api.v1.routes.passport_image_library."
            "MinioStorageRepository",
            return_value=storage,
        ),
        patch(
            "app.presentation.api.v1.routes.passport_image_library."
            "render_passport_image_crop",
            return_value=rendered,
        ),
        patch(
            "app.presentation.api.v1.routes.passport_image_library.AuditLogRepository",
            return_value=audit_repository,
        ),
        patch(
            "app.presentation.api.v1.routes.passport_image_library._crop_response",
            return_value=expected_response,
        ),
    ):
        response = await use_passport_image_library_item(
            submission_id=submission.id,
            image_type=PassportImageType.PASSPORT_BACK,
            item_id=manual_item.id,
            body=PassportVisaAiImageUseRequest(
                x=0,
                y=0,
                width=1,
                height=1,
                rotation_degrees=0,
                expected_revision=3,
            ),
            background_tasks=MagicMock(),
            _csrf=None,
            current_user=current_user,  # type: ignore[arg-type]
            session=session,
        )

    library_repository.get_for_image.assert_awaited_once_with(
        submission_id=submission.id,
        image_type=PassportImageType.PASSPORT_BACK,
        item_id=manual_item.id,
    )
    assert crop_repository.upsert.await_args.kwargs["edit_source_storage_key"] == (
        manual_item.storage_key
    )
    assert response is expected_response
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_selecting_passport_front_makes_it_authoritative_and_reextracts() -> None:
    submission = _submission()
    submission.thumbnail_s3_key = "original/front-thumbnail.jpg"
    submission.promote_image = MagicMock(
        side_effect=lambda key: setattr(submission, "image_s3_key", key)
    )
    submission.update_reviewed_fields = MagicMock()
    current_user = SimpleNamespace(id=uuid.uuid4(), email="staff@example.com")
    manual_item = _item(
        submission.id,
        image_type=PassportImageType.PASSPORT_FRONT,
        source=PassportImageLibrarySource.MANUAL,
        storage_key="passport-image-library/front-manual.jpg",
    )
    storage = MagicMock()
    storage.get_file = AsyncMock(return_value=b"manual")
    storage.upload_file = AsyncMock()
    library_repository = MagicMock()
    library_repository.get_for_image = AsyncMock(return_value=manual_item)
    crop_repository = MagicMock()
    crop_repository.upsert = AsyncMock(
        return_value=(SimpleNamespace(revision=5), None, None)
    )
    submission_repository = MagicMock()
    submission_repository.get_by_id_for_update = AsyncMock(return_value=submission)
    submission_repository.update = AsyncMock()
    reextract_result = SimpleNamespace(
        id=submission.id,
        processing_job_id=uuid.uuid4(),
    )
    reextract_use_case = MagicMock()
    reextract_use_case.execute = AsyncMock(return_value=reextract_result)
    audit_repository = MagicMock()
    audit_repository.record = AsyncMock()
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    rendered = SimpleNamespace(
        content=b"derived",
        content_type="image/jpeg",
        extension=".jpg",
        source_width=900,
        source_height=600,
    )
    expected_response = MagicMock()

    async def dispatch_and_commit(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args
        await kwargs["session"].commit()

    with (
        patch(
            "app.presentation.api.v1.routes.passport_image_library."
            "_authorized_staff_passport_image",
            new=AsyncMock(return_value=(submission, submission.image_s3_key)),
        ),
        patch(
            "app.presentation.api.v1.routes.passport_image_library."
            "PassportImageLibraryRepository",
            return_value=library_repository,
        ),
        patch(
            "app.presentation.api.v1.routes.passport_image_library."
            "PassportImageCropRepository",
            return_value=crop_repository,
        ),
        patch(
            "app.presentation.api.v1.routes.passport_image_library."
            "PassportSubmissionRepository",
            return_value=submission_repository,
        ),
        patch(
            "app.presentation.api.v1.routes.passport_image_library."
            "ReextractPassportSubmissionUseCase",
            return_value=reextract_use_case,
        ),
        patch(
            "app.presentation.api.v1.routes.passport_image_library."
            "_dispatch_processing_job",
            new=AsyncMock(side_effect=dispatch_and_commit),
        ) as dispatch_processing_job,
        patch(
            "app.presentation.api.v1.routes.passport_image_library."
            "MinioStorageRepository",
            return_value=storage,
        ),
        patch(
            "app.presentation.api.v1.routes.passport_image_library."
            "render_passport_image_crop",
            return_value=rendered,
        ),
        patch(
            "app.presentation.api.v1.routes.passport_image_library.AuditLogRepository",
            return_value=audit_repository,
        ),
        patch(
            "app.presentation.api.v1.routes.passport_image_library._crop_response",
            return_value=expected_response,
        ),
        patch(
            "app.presentation.api.v1.routes.passport_image_library."
            "propagate_mobile_passenger_change",
            new=AsyncMock(),
        ) as propagate_mobile_change,
    ):
        response = await use_passport_image_library_item(
            submission_id=submission.id,
            image_type=PassportImageType.PASSPORT_FRONT,
            item_id=manual_item.id,
            body=PassportVisaAiImageUseRequest(
                x=0,
                y=0,
                width=1,
                height=1,
                rotation_degrees=0,
                expected_revision=4,
            ),
            background_tasks=MagicMock(),
            _csrf=None,
            current_user=current_user,  # type: ignore[arg-type]
            session=session,
        )

    upsert = crop_repository.upsert.await_args.kwargs
    assert upsert["source_storage_key"] == manual_item.storage_key
    assert upsert["edit_source_storage_key"] is None
    submission.promote_image.assert_called_once_with(manual_item.storage_key)
    submission.update_reviewed_fields.assert_called_once_with({})
    submission_repository.update.assert_awaited_once_with(submission)
    reextract_use_case.execute.assert_awaited_once_with(submission.id)
    dispatch_processing_job.assert_awaited_once()
    propagate_mobile_change.assert_awaited_once()
    assert response is expected_response
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_reset_cleanup_never_deletes_a_common_library_variant() -> None:
    storage = MagicMock()
    storage.delete_files = AsyncMock()
    repository = MagicMock()
    repository.contains_storage_key = AsyncMock(return_value=True)

    with patch(
        "app.presentation.api.v1.routes.passports.PassportImageLibraryRepository",
        return_value=repository,
    ):
        await _delete_ephemeral_edit_source_best_effort(
            session=MagicMock(),
            storage=storage,
            key="passport-image-library/durable-manual.jpg",
            submission_id=uuid.uuid4(),
        )

    repository.contains_storage_key.assert_awaited_once()
    storage.delete_files.assert_not_awaited()


@pytest.mark.asyncio
async def test_bulk_replacement_cleanup_keeps_library_images() -> None:
    storage = MagicMock()
    storage.delete_files = AsyncMock()
    repository = MagicMock()
    repository.referenced_storage_keys = AsyncMock(
        return_value={"passport-image-library/durable-manual.jpg"}
    )

    with patch(
        "app.presentation.api.v1.routes.passports.PassportImageLibraryRepository",
        return_value=repository,
    ):
        await _delete_unreferenced_passport_image_keys_best_effort(
            session=MagicMock(),
            storage=storage,
            keys=[
                "passport-image-library/durable-manual.jpg",
                "passport-crops/obsolete-derived.jpg",
                "passport-crops/obsolete-derived.jpg",
            ],
            group_id=uuid.uuid4(),
        )

    repository.referenced_storage_keys.assert_awaited_once_with(
        [
            "passport-image-library/durable-manual.jpg",
            "passport-crops/obsolete-derived.jpg",
        ]
    )
    storage.delete_files.assert_awaited_once_with(
        ["passport-crops/obsolete-derived.jpg"]
    )
