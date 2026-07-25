from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.value_objects.passport_image_crop import PassportImageType
from app.domain.value_objects.passport_image_library import PassportImageLibrarySource
from app.infrastructure.repositories.passport_image_library_repository import (
    PassportImageLibraryRepository,
)
from app.infrastructure.repositories.passport_visa_ai_image_repository import (
    PassportVisaAiImageRepository,
)


def _load_migration():
    migration_path = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "0055_passport_image_library.py"
    )
    spec = importlib.util.spec_from_file_location(
        "passport_image_library_migration",
        migration_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"alembic": SimpleNamespace(op=MagicMock())}):
        spec.loader.exec_module(module)
    return module


def test_common_library_migration_follows_concurrent_head_and_is_additive() -> None:
    migration = _load_migration()
    assert migration.revision == "0055_image_library"
    assert migration.down_revision == "0054_custom_details"

    operation_proxy = MagicMock()
    with patch.object(migration, "op", operation_proxy):
        migration.upgrade()

    operation_proxy.create_table.assert_called_once()
    assert operation_proxy.create_index.call_count == 3
    assert operation_proxy.execute.call_count == 5
    rendered_sql = "\n".join(
        str(call.args[0]) for call in operation_proxy.execute.call_args_list
    )
    assert "legacy-ai-edit" in rendered_sql
    assert "edit_source_storage_key" in rendered_sql
    operation_proxy.drop_table.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_original_is_idempotent(db_session: AsyncSession) -> None:
    repository = PassportImageLibraryRepository(db_session)
    submission_id = uuid.uuid4()

    first, first_created = await repository.ensure_original(
        submission_id=submission_id,
        image_type=PassportImageType.PASSPORT_FRONT,
        storage_key="original/front.jpg",
        created_at=None,
    )
    second, second_created = await repository.ensure_original(
        submission_id=submission_id,
        image_type=PassportImageType.PASSPORT_FRONT,
        storage_key="original/front.jpg",
        created_at=None,
    )

    assert first_created is True
    assert second_created is False
    assert second.id == first.id
    assert second.source is PassportImageLibrarySource.ORIGINAL


@pytest.mark.asyncio
async def test_legacy_visa_ai_create_is_mirrored_into_common_library(
    db_session: AsyncSession,
) -> None:
    submission_id = uuid.uuid4()
    generated_key = f"passport-ai-library/{submission_id}/generated.jpg"

    legacy = await PassportVisaAiImageRepository(db_session).create(
        submission_id=submission_id,
        original_source_storage_key="original/visa.jpg",
        input_storage_key="original/visa.jpg",
        generated_storage_key=generated_key,
        prompt="Use a plain white background",
        prompt_sha256="a" * 64,
        content_sha256="b" * 64,
        model="gemini-image-edit",
        created_by_user_id=None,
    )
    items = await PassportImageLibraryRepository(db_session).list_for_image(
        submission_id,
        PassportImageType.VISA_PHOTO,
    )

    assert len(items) == 1
    assert items[0].id == legacy.id
    assert items[0].source is PassportImageLibrarySource.AI_GENERATED
    assert items[0].storage_key == generated_key
    assert items[0].prompt == legacy.prompt
