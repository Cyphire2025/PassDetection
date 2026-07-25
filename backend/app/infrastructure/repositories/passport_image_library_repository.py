"""Persistence for original, manual, and AI-generated image variants."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.value_objects.passport_image_crop import PassportImageType
from app.domain.value_objects.passport_image_library import (
    PassportImageLibraryItem,
    PassportImageLibrarySource,
)
from app.infrastructure.database.passport_image_library_model import (
    PassportImageLibraryItemModel,
)


class PassportImageLibraryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_value(model: PassportImageLibraryItemModel) -> PassportImageLibraryItem:
        return PassportImageLibraryItem(
            id=model.id,
            submission_id=model.submission_id,
            image_type=PassportImageType(model.image_type),
            source=PassportImageLibrarySource(model.source),
            storage_key=model.storage_key,
            original_source_storage_key=model.original_source_storage_key,
            content_sha256=model.content_sha256,
            prompt=model.prompt,
            prompt_sha256=model.prompt_sha256,
            model=model.model,
            created_by_user_id=model.created_by_user_id,
            created_at=model.created_at,
        )

    async def create(
        self,
        *,
        submission_id: uuid.UUID,
        image_type: PassportImageType,
        source: PassportImageLibrarySource,
        storage_key: str,
        original_source_storage_key: str,
        content_sha256: str | None,
        prompt: str | None,
        prompt_sha256: str | None,
        model: str | None,
        created_by_user_id: uuid.UUID | None,
        item_id: uuid.UUID | None = None,
        created_at: datetime | None = None,
    ) -> PassportImageLibraryItem:
        row = PassportImageLibraryItemModel(
            id=item_id or uuid.uuid4(),
            submission_id=submission_id,
            image_type=image_type.value,
            source=source.value,
            storage_key=storage_key,
            original_source_storage_key=original_source_storage_key,
            content_sha256=content_sha256,
            prompt=prompt,
            prompt_sha256=prompt_sha256,
            model=model,
            created_by_user_id=created_by_user_id,
            created_at=created_at or datetime.now(tz=UTC),
        )
        self._session.add(row)
        await self._session.flush()
        return self._to_value(row)

    async def ensure_original(
        self,
        *,
        submission_id: uuid.UUID,
        image_type: PassportImageType,
        storage_key: str,
        created_at: datetime | None,
    ) -> tuple[PassportImageLibraryItem, bool]:
        existing = await self.get_by_storage_key(
            submission_id=submission_id,
            image_type=image_type,
            storage_key=storage_key,
        )
        if existing is not None:
            return existing, False
        try:
            async with self._session.begin_nested():
                created = await self.create(
                    submission_id=submission_id,
                    image_type=image_type,
                    source=PassportImageLibrarySource.ORIGINAL,
                    storage_key=storage_key,
                    original_source_storage_key=storage_key,
                    content_sha256=None,
                    prompt=None,
                    prompt_sha256=None,
                    model=None,
                    created_by_user_id=None,
                    created_at=created_at,
                )
            return created, True
        except IntegrityError:
            # A concurrent first library open or upload can insert the same
            # original between the SELECT and INSERT. Resolve that race inside
            # a savepoint without rolling back the caller's outer transaction.
            existing = await self.get_by_storage_key(
                submission_id=submission_id,
                image_type=image_type,
                storage_key=storage_key,
            )
            if existing is None:
                raise
            return existing, False

    async def create_manual(
        self,
        *,
        submission_id: uuid.UUID,
        image_type: PassportImageType,
        storage_key: str,
        original_source_storage_key: str,
        content_sha256: str,
        created_by_user_id: uuid.UUID,
    ) -> PassportImageLibraryItem:
        return await self.create(
            submission_id=submission_id,
            image_type=image_type,
            source=PassportImageLibrarySource.MANUAL,
            storage_key=storage_key,
            original_source_storage_key=original_source_storage_key,
            content_sha256=content_sha256,
            prompt=None,
            prompt_sha256=None,
            model=None,
            created_by_user_id=created_by_user_id,
        )

    async def create_ai(
        self,
        *,
        submission_id: uuid.UUID,
        image_type: PassportImageType,
        storage_key: str,
        original_source_storage_key: str,
        content_sha256: str,
        prompt: str,
        prompt_sha256: str,
        model: str,
        created_by_user_id: uuid.UUID | None,
        item_id: uuid.UUID | None = None,
        created_at: datetime | None = None,
    ) -> PassportImageLibraryItem:
        return await self.create(
            submission_id=submission_id,
            image_type=image_type,
            source=PassportImageLibrarySource.AI_GENERATED,
            storage_key=storage_key,
            original_source_storage_key=original_source_storage_key,
            content_sha256=content_sha256,
            prompt=prompt,
            prompt_sha256=prompt_sha256,
            model=model,
            created_by_user_id=created_by_user_id,
            item_id=item_id,
            created_at=created_at,
        )

    async def list_for_image(
        self,
        submission_id: uuid.UUID,
        image_type: PassportImageType,
    ) -> list[PassportImageLibraryItem]:
        result = await self._session.execute(
            select(PassportImageLibraryItemModel)
            .where(
                PassportImageLibraryItemModel.submission_id == submission_id,
                PassportImageLibraryItemModel.image_type == image_type.value,
            )
            .order_by(
                PassportImageLibraryItemModel.created_at.desc(),
                PassportImageLibraryItemModel.id.desc(),
            )
        )
        return [self._to_value(row) for row in result.scalars().all()]

    async def get_for_image(
        self,
        *,
        submission_id: uuid.UUID,
        image_type: PassportImageType,
        item_id: uuid.UUID,
    ) -> PassportImageLibraryItem | None:
        result = await self._session.execute(
            select(PassportImageLibraryItemModel).where(
                PassportImageLibraryItemModel.id == item_id,
                PassportImageLibraryItemModel.submission_id == submission_id,
                PassportImageLibraryItemModel.image_type == image_type.value,
            )
        )
        row = result.scalar_one_or_none()
        return self._to_value(row) if row else None

    async def get_by_storage_key(
        self,
        *,
        submission_id: uuid.UUID,
        image_type: PassportImageType,
        storage_key: str,
    ) -> PassportImageLibraryItem | None:
        result = await self._session.execute(
            select(PassportImageLibraryItemModel).where(
                PassportImageLibraryItemModel.submission_id == submission_id,
                PassportImageLibraryItemModel.image_type == image_type.value,
                PassportImageLibraryItemModel.storage_key == storage_key,
            )
        )
        row = result.scalar_one_or_none()
        return self._to_value(row) if row else None

    async def contains_storage_key(self, storage_key: str) -> bool:
        result = await self._session.execute(
            select(PassportImageLibraryItemModel.id)
            .where(PassportImageLibraryItemModel.storage_key == storage_key)
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def referenced_storage_keys(self, storage_keys: list[str]) -> set[str]:
        unique_keys = list(dict.fromkeys(key for key in storage_keys if key))
        if not unique_keys:
            return set()
        result = await self._session.execute(
            select(PassportImageLibraryItemModel.storage_key).where(
                PassportImageLibraryItemModel.storage_key.in_(unique_keys)
            )
        )
        return set(result.scalars().all())
