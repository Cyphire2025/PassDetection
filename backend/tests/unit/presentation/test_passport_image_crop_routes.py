from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from PIL import Image
from pydantic import ValidationError

from app.domain.exceptions.exceptions import AuthorizationError
from app.domain.value_objects.passport_image_crop import PassportImageType
from app.domain.value_objects.passport_visa_ai_image import PassportVisaAiImage
from app.infrastructure.ai.gemini_visa_image_edit_service import (
    GeminiVisaImageEditError,
    GeminiVisaImageEditNotConfigured,
    GeminiVisaImageEditProviderRejected,
    GeminiVisaImageEditProviderUnavailable,
    GeminiVisaImageEditRejected,
    GeminiVisaImageEditResult,
)
from app.infrastructure.imaging.passport_thumbnail_cache import (
    PassportThumbnailCache,
)
from app.infrastructure.repositories.passport_image_crop_repository import (
    PassportImageCropRevisionConflict,
)
from app.presentation.api.v1.routes.passports import (
    _authorized_staff_passport_image,
    _staff_image_urls,
    _visa_ai_edit_http_exception,
    create_visa_ai_library_image,
    get_passport_image_thumbnail,
    update_passport_image_crop,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportImageCropResetRequest,
    PassportImageCropUpdateRequest,
    PassportVisaAiPreviewRequest,
)


def _submission(*, front_key: str = "original/front.jpg") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        agency_id=uuid.uuid4(),
        image_s3_key=front_key,
        passport_photo_s3_key="original/photo.jpg",
        passport_back_s3_key="original/back.jpg",
    )


def _jpeg(*, size: tuple[int, int] = (900, 600)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, color=(235, 235, 235)).save(output, format="JPEG")
    return output.getvalue()


@pytest.mark.asyncio
async def test_thumbnail_is_private_bounded_and_cached_after_authorization() -> None:
    submission = _submission()
    storage = MagicMock()
    storage.get_file = AsyncMock(return_value=_jpeg())
    crop_repository = MagicMock()
    crop_repository.get = AsyncMock(return_value=None)
    thumbnail_cache = PassportThumbnailCache(max_bytes=1024 * 1024)
    current_user = SimpleNamespace(id=uuid.uuid4(), email="staff@example.com")

    with (
        patch(
            "app.presentation.api.v1.routes.passports._authorized_staff_passport_image",
            new=AsyncMock(return_value=(submission, submission.image_s3_key)),
        ) as authorize,
        patch(
            "app.presentation.api.v1.routes.passports.MinioStorageRepository",
            return_value=storage,
        ),
        patch(
            "app.presentation.api.v1.routes.passports.PassportImageCropRepository",
            return_value=crop_repository,
        ),
        patch(
            "app.presentation.api.v1.routes.passports._dashboard_thumbnail_cache",
            return_value=thumbnail_cache,
        ),
        patch(
            "app.presentation.api.v1.routes.passports.get_settings",
            return_value=SimpleNamespace(dashboard_thumbnail_max_dimension=320),
        ),
    ):
        first = await get_passport_image_thumbnail(
            submission_id=submission.id,
            image_type=PassportImageType.PASSPORT_FRONT,
            crop_revision=None,
            current_user=current_user,  # type: ignore[arg-type]
            session=MagicMock(),
        )
        second = await get_passport_image_thumbnail(
            submission_id=submission.id,
            image_type=PassportImageType.PASSPORT_FRONT,
            crop_revision=1,
            current_user=current_user,  # type: ignore[arg-type]
            session=MagicMock(),
        )

    assert first.media_type == "image/jpeg"
    assert first.headers["cache-control"] == "private, no-store"
    assert first.body == second.body
    with Image.open(io.BytesIO(first.body)) as thumbnail:
        assert max(thumbnail.size) == 320
    assert authorize.await_count == 2
    storage.get_file.assert_awaited_once()


@pytest.mark.asyncio
async def test_effective_stream_uses_view_permission_but_original_editor_uses_confirm_permission() -> (
    None
):
    submission = _submission()
    repository = MagicMock()
    repository.get_by_id = AsyncMock(return_value=submission)
    policy = MagicMock()
    policy.require_view_passport = AsyncMock()
    policy.require_confirm_passport = AsyncMock()

    with (
        patch(
            "app.presentation.api.v1.routes.passports.PassportSubmissionRepository",
            return_value=repository,
        ),
        patch("app.presentation.api.v1.routes.passports.AuthorizationPolicy", return_value=policy),
    ):
        await _authorized_staff_passport_image(
            submission_id=submission.id,
            image_type=PassportImageType.PASSPORT_FRONT,
            current_user=SimpleNamespace(),  # type: ignore[arg-type]
            session=MagicMock(),
            require_editor=False,
        )
        policy.require_view_passport.assert_awaited_once()
        policy.require_confirm_passport.assert_not_awaited()

        policy.require_view_passport.reset_mock()
        await _authorized_staff_passport_image(
            submission_id=submission.id,
            image_type=PassportImageType.PASSPORT_FRONT,
            current_user=SimpleNamespace(),  # type: ignore[arg-type]
            session=MagicMock(),
            require_editor=True,
        )
        policy.require_confirm_passport.assert_awaited_once()
        policy.require_view_passport.assert_not_awaited()


@pytest.mark.asyncio
async def test_object_scope_denial_is_returned_as_forbidden() -> None:
    submission = _submission()
    repository = MagicMock()
    repository.get_by_id = AsyncMock(return_value=submission)
    policy = MagicMock()
    policy.require_view_passport = AsyncMock(side_effect=AuthorizationError("wrong agency"))

    with (
        patch(
            "app.presentation.api.v1.routes.passports.PassportSubmissionRepository",
            return_value=repository,
        ),
        patch("app.presentation.api.v1.routes.passports.AuthorizationPolicy", return_value=policy),
        pytest.raises(HTTPException) as denied,
    ):
        await _authorized_staff_passport_image(
            submission_id=submission.id,
            image_type=PassportImageType.PASSPORT_FRONT,
            current_user=SimpleNamespace(),  # type: ignore[arg-type]
            session=MagicMock(),
            require_editor=False,
        )
    assert denied.value.status_code == 403


@pytest.mark.asyncio
async def test_excel_placeholder_is_not_exposed_as_a_document() -> None:
    submission = _submission(front_key="excel-imports/agency/group/placeholder")
    repository = MagicMock()
    repository.get_by_id = AsyncMock(return_value=submission)
    policy = MagicMock()
    policy.require_view_passport = AsyncMock()

    with (
        patch(
            "app.presentation.api.v1.routes.passports.PassportSubmissionRepository",
            return_value=repository,
        ),
        patch("app.presentation.api.v1.routes.passports.AuthorizationPolicy", return_value=policy),
        pytest.raises(HTTPException) as missing,
    ):
        await _authorized_staff_passport_image(
            submission_id=submission.id,
            image_type=PassportImageType.PASSPORT_FRONT,
            current_user=SimpleNamespace(),  # type: ignore[arg-type]
            session=MagicMock(),
            require_editor=False,
        )
    assert missing.value.status_code == 404
    assert _staff_image_urls(submission)["image_url"] is None


def test_crop_write_and_reset_require_optimistic_revision() -> None:
    with pytest.raises(ValidationError):
        PassportImageCropUpdateRequest(
            x=0,
            y=0,
            width=1,
            height=1,
            rotation_degrees=0,
        )
    with pytest.raises(ValidationError):
        PassportImageCropResetRequest()


def test_crop_schema_rejects_non_finite_values() -> None:
    with pytest.raises(ValidationError):
        PassportImageCropUpdateRequest(
            x=float("nan"),
            y=0,
            width=1,
            height=1,
            rotation_degrees=0,
            expected_revision=0,
        )


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_retry_after"),
    [
        (GeminiVisaImageEditRejected("unsafe edit"), 422, None),
        (GeminiVisaImageEditNotConfigured("not configured"), 503, None),
        (GeminiVisaImageEditProviderUnavailable("retry later"), 503, None),
        (GeminiVisaImageEditProviderRejected("provider rejected"), 502, None),
        (GeminiVisaImageEditError("unreadable provider response"), 502, None),
    ],
)
def test_visa_ai_edit_errors_map_to_truthful_http_statuses(
    error: GeminiVisaImageEditError,
    expected_status: int,
    expected_retry_after: str | None,
) -> None:
    mapped = _visa_ai_edit_http_exception(error)

    assert mapped.status_code == expected_status
    assert mapped.detail == str(error)
    assert mapped.headers is None or mapped.headers.get("Retry-After") == expected_retry_after


@pytest.mark.asyncio
async def test_generated_visa_ai_image_is_uploaded_and_committed_to_library() -> None:
    submission = _submission()
    generated_id = uuid.uuid4()
    user_id = uuid.uuid4()
    generated_at = datetime.now(tz=UTC)
    current_user = SimpleNamespace(id=user_id, email="staff@example.com")
    storage = MagicMock()
    storage.get_file = AsyncMock(return_value=b"source-image")
    storage.upload_file = AsyncMock(return_value="saved")
    storage.delete_files = AsyncMock(return_value=1)
    crop_repository = MagicMock()
    crop_repository.get = AsyncMock(return_value=None)
    submission_repository = MagicMock()
    submission_repository.get_by_id_for_update = AsyncMock(return_value=submission)
    library_repository = MagicMock()
    library_repository.create = AsyncMock(
        return_value=PassportVisaAiImage(
            id=generated_id,
            submission_id=submission.id,
            original_source_storage_key=submission.passport_photo_s3_key,
            input_storage_key=submission.passport_photo_s3_key,
            generated_storage_key="passport-ai-library/generated.jpg",
            prompt="Make the background plain white",
            prompt_sha256="a" * 64,
            content_sha256="b" * 64,
            model="gemini-3-pro-image",
            created_by_user_id=user_id,
            created_at=generated_at,
        )
    )
    ai_service = MagicMock()
    ai_service.edit = AsyncMock(
        return_value=GeminiVisaImageEditResult(
            content=b"generated-image",
            content_type="image/jpeg",
            prompt_sha256="a" * 64,
            model="gemini-3-pro-image",
        )
    )
    audit_repository = MagicMock()
    audit_repository.record = AsyncMock()
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    with (
        patch(
            "app.presentation.api.v1.routes.passports._authorized_staff_passport_image",
            new=AsyncMock(return_value=(submission, submission.passport_photo_s3_key)),
        ),
        patch(
            "app.presentation.api.v1.routes.passports.MinioStorageRepository",
            return_value=storage,
        ),
        patch(
            "app.presentation.api.v1.routes.passports.PassportImageCropRepository",
            return_value=crop_repository,
        ),
        patch(
            "app.presentation.api.v1.routes.passports.PassportSubmissionRepository",
            return_value=submission_repository,
        ),
        patch(
            "app.presentation.api.v1.routes.passports.PassportVisaAiImageRepository",
            return_value=library_repository,
        ),
        patch(
            "app.presentation.api.v1.routes.passports.GeminiVisaImageEditService",
            return_value=ai_service,
        ),
        patch(
            "app.presentation.api.v1.routes.passports.AuditLogRepository",
            return_value=audit_repository,
        ),
    ):
        response = await create_visa_ai_library_image(
            submission_id=submission.id,
            body=PassportVisaAiPreviewRequest(prompt="  Make   the background plain white  "),
            _csrf=None,
            current_user=current_user,  # type: ignore[arg-type]
            session=session,
        )

    storage.upload_file.assert_awaited_once()
    uploaded_key = storage.upload_file.await_args.args[1]
    assert uploaded_key.startswith(
        f"passport-ai-library/{submission.agency_id}/{submission.id}/visa_photo/"
    )
    library_repository.create.assert_awaited_once()
    assert library_repository.create.await_args.kwargs["prompt"] == (
        "Make the background plain white"
    )
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()
    assert response.id == generated_id
    assert response.model == "gemini-3-pro-image"
    assert str(generated_id) in response.image_url


@pytest.mark.asyncio
async def test_stale_crop_save_returns_409_and_cleans_uncommitted_derivative() -> None:
    submission = _submission()
    storage = MagicMock()
    storage.get_file = AsyncMock(return_value=b"source")
    storage.upload_file = AsyncMock(return_value="derived")
    storage.delete_files = AsyncMock(return_value=1)
    submission_repository = MagicMock()
    submission_repository.get_by_id_for_update = AsyncMock(return_value=submission)
    crop_repository = MagicMock()
    crop_repository.get = AsyncMock(return_value=None)
    crop_repository.upsert = AsyncMock(side_effect=PassportImageCropRevisionConflict(4))
    session = MagicMock()
    session.rollback = AsyncMock()
    current_user = SimpleNamespace(id=uuid.uuid4(), email="staff@example.com")
    rendered = SimpleNamespace(
        content=b"derived",
        content_type="image/jpeg",
        extension=".jpg",
        source_width=400,
        source_height=300,
    )

    with (
        patch(
            "app.presentation.api.v1.routes.passports._authorized_staff_passport_image",
            new=AsyncMock(return_value=(submission, submission.image_s3_key)),
        ),
        patch(
            "app.presentation.api.v1.routes.passports.MinioStorageRepository", return_value=storage
        ),
        patch(
            "app.presentation.api.v1.routes.passports.PassportSubmissionRepository",
            return_value=submission_repository,
        ),
        patch(
            "app.presentation.api.v1.routes.passports.PassportImageCropRepository",
            return_value=crop_repository,
        ),
        patch(
            "app.presentation.api.v1.routes.passports.render_passport_image_crop",
            return_value=rendered,
        ),
        pytest.raises(HTTPException) as conflict,
    ):
        await update_passport_image_crop(
            submission_id=submission.id,
            image_type=PassportImageType.PASSPORT_FRONT,
            body=PassportImageCropUpdateRequest(
                x=0,
                y=0,
                width=1,
                height=1,
                rotation_degrees=0,
                expected_revision=3,
            ),
            _csrf=None,
            current_user=current_user,  # type: ignore[arg-type]
            session=session,
        )
    assert conflict.value.status_code == 409
    assert "current revision 4" in str(conflict.value.detail)
    assert conflict.value.headers == {"X-Current-Crop-Revision": "4"}
    session.rollback.assert_awaited_once()
    storage.delete_files.assert_awaited_once()
