"""Retained document purge is rechecked after external image work."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.travellers.retention import revoke_retained_profile
from app.application.travellers.snapshot_access import can_read_snapshot_asset
from app.domain.value_objects.passport_image_crop import PassportImageType
from app.infrastructure.database.models import UserModel
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentAssetModel,
    TravellerProfileModel,
)
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.repositories.passport_visa_ai_image_repository import (
    PassportVisaAiImageRepository,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes import passport_image_library
from app.presentation.api.v1.routes.passport_routes import images, visa_ai_edits
from app.presentation.api.v1.schemas.passport_schemas import PassportVisaAiImageUseRequest
from tests.passport_image_mutations import (
    ImageMutationContext,
    configure_image_mutation_adapters,
    invoke_image_mutation,
)
from tests.route_dependencies import set_route_dependency
from tests.unit.application.test_traveller_snapshot_access import snapshot
from tests.unit.presentation.test_passport_image_library_commit_outcomes import ImageStorage


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation",
    [
        "crop",
        "generate",
        "select-ai",
        "apply-ai",
        "preview",
        "reset",
        "manual-library",
        "select-library",
    ],
)
@pytest.mark.parametrize("change", ["withdrawal", "asset-purge", "profile-delete"])
async def test_retained_image_authority_after_external_work(
    db_session, monkeypatch, operation, change
):
    _, enrolled, asset, group, source, _ = await snapshot(db_session)
    # The image is an owned frozen-trip reference. Content decoding and the
    # provider are synthetic; retained authority and persistence remain real.
    source.passport_photo_s3_key = asset.object_key
    agency_id, company_id, group_id, source_id, asset_id, person_id, source_key = (
        group.agency_id,
        group.company_id,
        group.id,
        source.id,
        asset.id,
        enrolled.traveller_id,
        asset.object_key,
    )
    user_id = await db_session.scalar(select(UserModel.id).where(UserModel.agency_id == agency_id))
    generation_key = f"passport-ai-library/{agency_id}/{source_id}/visa_photo/existing.jpg"
    generation = await PassportVisaAiImageRepository(db_session).create(
        submission_id=source_id,
        original_source_storage_key=source_key,
        input_storage_key=source_key,
        generated_storage_key=generation_key,
        prompt="Keep original",
        prompt_sha256="b" * 64,
        content_sha256="a" * 64,
        model="synthetic",
        created_by_user_id=user_id,
    )
    await db_session.commit()
    actor = await UserRepository(db_session).get_by_id(user_id)
    submission = await PassportSubmissionRepository(db_session).get_by_id(source_id)
    assert actor is not None and submission is not None
    assert await can_read_snapshot_asset(
        db_session,
        submission_id=source_id,
        group_id=group_id,
        agency_id=agency_id,
        storage_key=source_key,
    )
    await db_session.rollback()
    context = ImageMutationContext(
        actor,
        submission,
        generation.id,
        ImageStorage({source_key: b"retained source", generation_key: b"existing"}),
    )
    configure_image_mutation_adapters(monkeypatch, context)
    for name, value in [
        ("MinioStorageRepository", lambda: context.storage),
        ("render_passport_image_crop", images.render_passport_image_crop),
    ]:
        set_route_dependency(monkeypatch, passport_image_library, name, value)
    # Use the same isolated raster adapter for the manual library endpoint.
    set_route_dependency(
        monkeypatch,
        passport_image_library,
        "_validated_upload_file",
        AsyncMock(
            return_value=SimpleNamespace(content=b"synthetic raster", content_type="image/jpeg"),
        ),
    )
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    previous = set(context.storage.objects)
    changed = False

    async def change_retained_authority():
        nonlocal changed
        if changed:
            return
        async with factory() as editor:
            if change == "withdrawal":
                assert await revoke_retained_profile(
                    editor,
                    agency_id=agency_id,
                    company_id=company_id,
                    traveller_id=person_id,
                    expected_revision=1,
                )
            elif change == "asset-purge":
                await editor.execute(
                    update(TravellerDocumentAssetModel)
                    .where(
                        TravellerDocumentAssetModel.id == asset_id,
                    )
                    .values(availability="purged", purged_at=datetime.now(UTC))
                )
            else:
                await editor.execute(
                    update(TravellerProfileModel)
                    .where(
                        TravellerProfileModel.id == person_id,
                    )
                    .values(status="deleted", deleted_at=datetime.now(UTC))
                )
            await editor.commit()
        changed = True

    write = context.storage.upload_file

    async def upload(content, key, content_type):
        await write(content, key, content_type)
        await change_retained_authority()
        return key

    context.storage.upload_file = upload
    if operation == "preview":
        service = visa_ai_edits.GeminiVisaImageEditService()
        edit = service.edit

        async def preview(*args, **kwargs):
            result = await edit(*args, **kwargs)
            await change_retained_authority()
            return result

        service.edit = preview
        set_route_dependency(
            monkeypatch, visa_ai_edits, "GeminiVisaImageEditService", lambda: service
        )
    elif operation == "reset":
        authorize = images._resolve_authorized_staff_passport_image

        async def initial_scope(**kwargs):
            result = await authorize(**kwargs)
            await change_retained_authority()
            return result

        set_route_dependency(
            monkeypatch, images, "_resolve_authorized_staff_passport_image", initial_scope
        )

    async def execute():
        if operation == "manual-library":
            return await passport_image_library.upload_passport_image_library_item(
                submission_id=source_id,
                image_type=PassportImageType.VISA_PHOTO,
                background_tasks=BackgroundTasks(),
                image=SimpleNamespace(),
                expected_revision=0,
                _csrf=None,
                current_user=actor,
                session=db_session,
            )
        if operation == "select-library":
            return await passport_image_library.use_passport_image_library_item(
                submission_id=source_id,
                image_type=PassportImageType.VISA_PHOTO,
                item_id=generation.id,
                body=PassportVisaAiImageUseRequest(
                    x=0, y=0, width=1, height=1, expected_revision=0
                ),
                background_tasks=BackgroundTasks(),
                _csrf=None,
                current_user=actor,
                session=db_session,
            )
        return await invoke_image_mutation(operation, context, db_session)

    if change == "withdrawal":
        await execute()
    else:
        with pytest.raises(HTTPException) as caught:
            await execute()
        assert caught.value.status_code == 404
        assert set(context.storage.objects) == previous
    assert changed
