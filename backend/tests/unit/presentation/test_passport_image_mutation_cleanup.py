"""Actual prior-crop replacement/reset and stale-revision compensation."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.infrastructure.database.models import PassportImageCropModel
from tests.passport_image_mutations import (
    configure_image_mutation_adapters,
    invoke_image_mutation,
    seed_existing_image_crop,
    seed_image_mutation_context,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["crop", "generate", "select-ai", "apply-ai", "reset"])
async def test_prior_image_objects_are_retained_only_when_still_current(
    db_session, monkeypatch, operation
):
    context = await seed_image_mutation_context(db_session)
    edit, derived = await seed_existing_image_crop(context, db_session)
    configure_image_mutation_adapters(monkeypatch, context)
    await invoke_image_mutation(operation, context, db_session)
    assert (derived in context.storage.objects) == (operation == "generate")
    assert (edit in context.storage.objects) == (operation in {"crop", "generate"})
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as observer:
        crop = (
            await observer.scalars(
                select(PassportImageCropModel).where(
                    PassportImageCropModel.submission_id == context.submission.id,
                )
            )
        ).one()
        assert crop.active == (operation != "reset")
        assert crop.revision == (1 if operation == "generate" else 2)
        for key in [
            crop.source_storage_key,
            crop.edit_source_storage_key,
            crop.derived_storage_key,
        ]:
            if key:
                assert key in context.storage.objects


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["crop", "select-ai", "apply-ai", "reset"])
async def test_stale_image_revision_keeps_previous_objects_and_removes_only_uncommitted_writes(
    db_session,
    monkeypatch,
    operation,
):
    context = await seed_image_mutation_context(db_session)
    edit, derived = await seed_existing_image_crop(context, db_session)
    context.expected_revision = 0
    configure_image_mutation_adapters(monkeypatch, context)
    previous = dict(context.storage.objects)
    with pytest.raises(HTTPException) as caught:
        await invoke_image_mutation(operation, context, db_session)
    assert caught.value.status_code == 409
    assert caught.value.headers == {"X-Current-Crop-Revision": "1"}
    assert context.storage.objects == previous
    assert edit not in context.storage.deleted and derived not in context.storage.deleted
