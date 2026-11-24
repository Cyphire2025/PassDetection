"""Sibling image writes retain actual committed references after a lost ACK."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.infrastructure.database.models import PassportImageCropModel, PassportVisaAiImageModel
from app.infrastructure.database.passport_image_library_model import PassportImageLibraryItemModel
from tests.passport_image_mutations import (
    configure_image_mutation_adapters,
    invoke_image_mutation,
    seed_image_mutation_context,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["crop", "generate", "select-ai", "apply-ai"])
@pytest.mark.parametrize("lost_ack", [False, True], ids=["ordinary", "lost-ack"])
async def test_committed_image_objects_survive_lost_ack(
    db_session, monkeypatch, operation, lost_ack
):
    context = await seed_image_mutation_context(db_session)
    configure_image_mutation_adapters(monkeypatch, context)
    commit = db_session.commit

    async def committing():
        await commit()
        if lost_ack:
            raise ConnectionError("Synthetic lost acknowledgement after real image commit")

    monkeypatch.setattr(db_session, "commit", committing)
    if lost_ack:
        with pytest.raises(ConnectionError):
            await invoke_image_mutation(operation, context, db_session)
    else:
        await invoke_image_mutation(operation, context, db_session)

    references = set()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with factory() as observer:
        for model, columns in [
            (
                PassportImageCropModel,
                ["source_storage_key", "edit_source_storage_key", "derived_storage_key"],
            ),
            (
                PassportVisaAiImageModel,
                ["original_source_storage_key", "input_storage_key", "generated_storage_key"],
            ),
            (PassportImageLibraryItemModel, ["original_source_storage_key", "storage_key"]),
        ]:
            rows = (
                await observer.scalars(
                    select(model).where(
                        model.submission_id == context.submission.id,
                    )
                )
            ).all()
            if model is PassportImageCropModel and operation != "generate":
                assert len(rows) == 1
            for row in rows:
                references.update(key for name in columns if (key := getattr(row, name)))
    assert references <= context.storage.objects.keys(), (
        "Committed private images lost stored bytes"
    )
    assert not references.intersection(context.storage.deleted)
