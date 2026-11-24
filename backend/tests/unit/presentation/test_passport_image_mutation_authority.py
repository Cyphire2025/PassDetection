"""Actual persisted image authority changes during external work are enforced."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.infrastructure.database.models import PassportSubmissionModel, UserModel
from app.presentation.api.v1.routes.passport_routes import images, visa_ai_edits
from tests.passport_image_mutations import (
    configure_image_mutation_adapters,
    invoke_image_mutation,
    seed_image_mutation_context,
)
from tests.route_dependencies import set_route_dependency


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation", ["crop", "generate", "select-ai", "apply-ai", "preview", "reset"]
)
@pytest.mark.parametrize("change", ["profile", "deactivate", "source-changed"])
async def test_persisted_image_authority_after_external_work(
    db_session, monkeypatch, operation, change
):
    context = await seed_image_mutation_context(db_session)
    configure_image_mutation_adapters(monkeypatch, context)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    write = context.storage.upload_file
    existing = set(context.storage.objects)
    changed = False

    async def replace_scope():
        nonlocal changed
        if changed:
            return
        async with factory() as editor:
            if change == "source-changed":
                key = f"photo/{context.submission.id}-replacement.jpg"
                context.storage.objects[key] = b"another writer"
                existing.add(key)
                statement = (
                    update(PassportSubmissionModel)
                    .where(
                        PassportSubmissionModel.id == context.submission.id,
                    )
                    .values(passport_photo_s3_key=key)
                )
            else:
                values = (
                    {"full_name": "Renewed image editor"}
                    if change == "profile"
                    else {"is_active": False}
                )
                statement = (
                    update(UserModel).where(UserModel.id == context.actor.id).values(**values)
                )
            await editor.execute(statement)
            await editor.commit()
        changed = True

    async def upload(content, key, content_type):
        await write(content, key, content_type)
        await replace_scope()
        return key

    context.storage.upload_file = upload
    if operation == "reset":
        authorize = images._resolve_authorized_staff_passport_image

        async def initial_scope(**kwargs):
            result = await authorize(**kwargs)
            await replace_scope()
            return result

        set_route_dependency(
            monkeypatch, images, "_resolve_authorized_staff_passport_image", initial_scope
        )
    if operation == "preview":
        service = visa_ai_edits.GeminiVisaImageEditService()
        edit = service.edit

        async def preview(*args, **kwargs):
            result = await edit(*args, **kwargs)
            await replace_scope()
            return result

        set_route_dependency(
            monkeypatch, visa_ai_edits, "GeminiVisaImageEditService", lambda: service
        )
        service.edit = preview
    if change == "profile":
        await invoke_image_mutation(operation, context, db_session)
    else:
        with pytest.raises(HTTPException) as caught:
            await invoke_image_mutation(operation, context, db_session)
        assert caught.value.status_code == (409 if change == "source-changed" else 403)
        assert set(context.storage.objects) == existing
    assert changed
