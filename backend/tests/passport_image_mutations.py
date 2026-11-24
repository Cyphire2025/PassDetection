"""Real persisted image scope with isolated raster, token, and storage adapters."""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import UploadFile

from app.domain.entities.entities import PassportSubmission, User
from app.domain.value_objects.passport_image_crop import PassportImageType
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    PassportSubmissionModel,
    UserModel,
    UserSecurityStateModel,
)
from app.infrastructure.repositories.passport_image_crop_repository import (
    PassportImageCropRepository,
)
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.repositories.passport_visa_ai_image_repository import (
    PassportVisaAiImageRepository,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes.passport_routes import images, visa_ai_edits, visa_ai_library
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportImageCropResetRequest,
    PassportImageCropUpdateRequest,
    PassportVisaAiImageUseRequest,
    PassportVisaAiPreviewRequest,
)
from tests.route_dependencies import set_route_dependency
from tests.unit.presentation.test_passport_image_library_commit_outcomes import ImageStorage


@dataclass
class ImageMutationContext:
    actor: User
    submission: PassportSubmission
    generation_id: uuid.UUID
    storage: ImageStorage
    expected_revision: int = 0


async def seed_image_mutation_context(session) -> ImageMutationContext:
    agency_id, user_id, group_id, submission_id = (uuid.uuid4() for _ in range(4))
    session.add(AgencyModel(id=agency_id, name="Image edits", email="image-edits@example.test"))
    await session.flush()
    session.add(
        UserModel(
            id=user_id,
            agency_id=agency_id,
            email="image-editor@example.test",
            full_name="Image Editor",
            hashed_password="synthetic",
            role="agency_admin",
            is_active=True,
        )
    )
    await session.flush()
    session.add_all(
        [
            UserSecurityStateModel(user_id=user_id, credential_state="active", session_version=1),
            ClientGroupModel(
                id=group_id,
                agency_id=agency_id,
                created_by_user_id=user_id,
                name="Image edit group",
                token=uuid.uuid4().hex,
                travel_date=datetime.now(UTC).date() + timedelta(days=20),
            ),
        ]
    )
    await session.flush()
    source = f"photo/{submission_id}.jpg"
    session.add(
        PassportSubmissionModel(
            id=submission_id,
            agency_id=agency_id,
            group_id=group_id,
            client_name="Synthetic",
            image_s3_key=f"front/{submission_id}.jpg",
            passport_photo_s3_key=source,
            status="staff_approved",
        )
    )
    await session.flush()
    key = f"passport-ai-library/{agency_id}/{submission_id}/visa_photo/existing.jpg"
    generation = await PassportVisaAiImageRepository(session).create(
        submission_id=submission_id,
        original_source_storage_key=source,
        input_storage_key=source,
        generated_storage_key=key,
        prompt="Keep original",
        prompt_sha256="b" * 64,
        content_sha256="a" * 64,
        model="synthetic-image-model",
        created_by_user_id=user_id,
    )
    await session.commit()
    actor = await UserRepository(session).get_by_id(user_id)
    submission = await PassportSubmissionRepository(session).get_by_id(submission_id)
    assert actor is not None and submission is not None
    await session.rollback()
    return ImageMutationContext(
        actor,
        submission,
        generation.id,
        ImageStorage(
            {
                source: b"source",
                key: b"existing",
                submission.image_s3_key: b"front",
            }
        ),
    )


def configure_image_mutation_adapters(monkeypatch, context):
    rendered = SimpleNamespace(
        content=b"synthetic raster",
        content_type="image/jpeg",
        extension=".jpg",
        source_width=900,
        source_height=600,
    )
    for owner in [images, visa_ai_edits, visa_ai_library]:
        set_route_dependency(monkeypatch, owner, "MinioStorageRepository", lambda: context.storage)
        set_route_dependency(
            monkeypatch, owner, "render_passport_image_crop", lambda *_args, **_kwargs: rendered
        )
    set_route_dependency(
        monkeypatch,
        visa_ai_edits,
        "verify_passport_ai_edit_token",
        lambda *_args, **_kwargs: SimpleNamespace(model="synthetic-image-model"),
    )
    for owner in [visa_ai_library, visa_ai_edits]:
        set_route_dependency(
            monkeypatch,
            owner,
            "GeminiVisaImageEditService",
            lambda: SimpleNamespace(
                edit=AsyncMock(
                    return_value=SimpleNamespace(
                        content=rendered.content,
                        content_type=rendered.content_type,
                        prompt_sha256="b" * 64,
                        model="synthetic-image-model",
                    )
                ),
            ),
        )


async def invoke_image_mutation(operation, context, session):
    args = dict(
        submission_id=context.submission.id, _csrf=None, current_user=context.actor, session=session
    )
    coordinates = dict(
        x=0,
        y=0,
        width=1,
        height=1,
        rotation_degrees=0,
        sharpness=1,
        expected_revision=context.expected_revision,
    )
    if operation == "crop":
        return await images.update_passport_image_crop(
            **args,
            image_type=PassportImageType.VISA_PHOTO,
            body=PassportImageCropUpdateRequest(**coordinates),
        )
    if operation == "generate":
        return await visa_ai_library.create_visa_ai_library_image(
            **args,
            body=PassportVisaAiPreviewRequest(prompt="Keep original"),
        )
    if operation == "select-ai":
        return await visa_ai_library.use_visa_ai_library_image(
            **args,
            generation_id=context.generation_id,
            body=PassportVisaAiImageUseRequest(**coordinates),
        )
    if operation == "preview":
        return await visa_ai_edits.preview_visa_ai_image_edit(
            **args,
            body=PassportVisaAiPreviewRequest(prompt="Keep original"),
        )
    if operation == "reset":
        return await images.reset_passport_image_crop(
            **args,
            image_type=PassportImageType.VISA_PHOTO,
            body=PassportImageCropResetRequest(expected_revision=context.expected_revision),
        )
    assert operation == "apply-ai"
    return await visa_ai_edits.apply_visa_ai_image_edit(
        **args,
        **coordinates,
        image=UploadFile(filename="synthetic.jpg", file=io.BytesIO(b"synthetic raster")),
        preview_token="synthetic signed preview",
        prompt="Keep original",
    )


async def seed_existing_image_crop(context, session):
    source = context.submission.passport_photo_s3_key
    edit = f"passport-edits/{context.submission.id}/previous.jpg"
    derived = f"passport-crops/{context.submission.id}/previous.jpg"
    await PassportImageCropRepository(session).upsert(
        submission_id=context.submission.id,
        image_type=PassportImageType.VISA_PHOTO,
        source_storage_key=source,
        edit_source_storage_key=edit,
        derived_storage_key=derived,
        x=0,
        y=0,
        width=1,
        height=1,
        rotation_degrees=0,
        sharpness=1,
        source_width=900,
        source_height=600,
        updated_by_user_id=context.actor.id,
        expected_revision=0,
        sharpness_algorithm_version=2,
    )
    await session.commit()
    context.storage.objects.update({edit: b"previous edit", derived: b"previous derivative"})
    context.expected_revision = 1
    return edit, derived
