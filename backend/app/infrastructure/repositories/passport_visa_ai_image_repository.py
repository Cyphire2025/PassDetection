"""Persistence for durable, verified Visa-photo AI generations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.value_objects.passport_visa_ai_image import PassportVisaAiImage
from app.infrastructure.database.models import PassportVisaAiImageModel


class PassportVisaAiImageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_value(model: PassportVisaAiImageModel) -> PassportVisaAiImage:
        return PassportVisaAiImage(
            id=model.id,
            submission_id=model.submission_id,
            original_source_storage_key=model.original_source_storage_key,
            input_storage_key=model.input_storage_key,
            generated_storage_key=model.generated_storage_key,
            prompt=model.prompt,
            prompt_sha256=model.prompt_sha256,
            content_sha256=model.content_sha256,
            model=model.model,
            created_by_user_id=model.created_by_user_id,
            created_at=model.created_at,
        )

    async def create(
        self,
        *,
        submission_id: uuid.UUID,
        original_source_storage_key: str,
        input_storage_key: str,
        generated_storage_key: str,
        prompt: str,
        prompt_sha256: str,
        content_sha256: str,
        model: str,
        created_by_user_id: uuid.UUID | None,
    ) -> PassportVisaAiImage:
        row = PassportVisaAiImageModel(
            submission_id=submission_id,
            original_source_storage_key=original_source_storage_key,
            input_storage_key=input_storage_key,
            generated_storage_key=generated_storage_key,
            prompt=prompt,
            prompt_sha256=prompt_sha256,
            content_sha256=content_sha256,
            model=model,
            created_by_user_id=created_by_user_id,
            created_at=datetime.now(tz=UTC),
        )
        self._session.add(row)
        await self._session.flush()
        return self._to_value(row)

    async def get_by_storage_key(
        self,
        storage_key: str,
    ) -> PassportVisaAiImage | None:
        result = await self._session.execute(
            select(PassportVisaAiImageModel).where(
                PassportVisaAiImageModel.generated_storage_key == storage_key
            )
        )
        row = result.scalar_one_or_none()
        return self._to_value(row) if row else None

    async def list_for_submission(
        self,
        submission_id: uuid.UUID,
    ) -> list[PassportVisaAiImage]:
        result = await self._session.execute(
            select(PassportVisaAiImageModel)
            .where(PassportVisaAiImageModel.submission_id == submission_id)
            .order_by(
                PassportVisaAiImageModel.created_at.desc(),
                PassportVisaAiImageModel.id.desc(),
            )
        )
        return [self._to_value(row) for row in result.scalars().all()]

    async def get_for_submission(
        self,
        submission_id: uuid.UUID,
        generation_id: uuid.UUID,
    ) -> PassportVisaAiImage | None:
        result = await self._session.execute(
            select(PassportVisaAiImageModel).where(
                PassportVisaAiImageModel.id == generation_id,
                PassportVisaAiImageModel.submission_id == submission_id,
            )
        )
        row = result.scalar_one_or_none()
        return self._to_value(row) if row else None

    async def contains_storage_key(self, storage_key: str) -> bool:
        result = await self._session.execute(
            select(PassportVisaAiImageModel.id)
            .where(PassportVisaAiImageModel.generated_storage_key == storage_key)
            .limit(1)
        )
        return result.scalar_one_or_none() is not None
