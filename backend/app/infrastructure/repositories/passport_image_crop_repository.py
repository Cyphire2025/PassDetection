"""Persistence for non-destructive passport image crop metadata."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.value_objects.passport_image_crop import (
    PassportImageCrop,
    PassportImageType,
)
from app.infrastructure.database.models import PassportImageCropModel, PassportVisaAiImageModel


class PassportImageCropRevisionConflict(ValueError):
    def __init__(self, current_revision: int) -> None:
        super().__init__("The image crop changed. Refresh it and try again.")
        self.current_revision = current_revision


class PassportImageCropRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_value(model: PassportImageCropModel) -> PassportImageCrop:
        return PassportImageCrop(
            submission_id=model.submission_id,
            image_type=PassportImageType(model.image_type),
            source_storage_key=model.source_storage_key,
            edit_source_storage_key=model.edit_source_storage_key,
            derived_storage_key=model.derived_storage_key,
            active=model.active,
            x=model.crop_x,
            y=model.crop_y,
            width=model.crop_width,
            height=model.crop_height,
            rotation_degrees=model.rotation_degrees,
            sharpness=model.sharpness,
            sharpness_algorithm_version=model.sharpness_algorithm_version,
            source_width=model.source_width,
            source_height=model.source_height,
            revision=model.revision,
            updated_by_user_id=model.updated_by_user_id,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    async def get(
        self,
        submission_id: uuid.UUID,
        image_type: PassportImageType,
        *,
        for_update: bool = False,
    ) -> PassportImageCrop | None:
        stmt = select(PassportImageCropModel).where(
            PassportImageCropModel.submission_id == submission_id,
            PassportImageCropModel.image_type == image_type.value,
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._to_value(model) if model else None

    async def list_for_submissions(
        self,
        submission_ids: list[uuid.UUID] | set[uuid.UUID],
    ) -> dict[uuid.UUID, dict[PassportImageType, PassportImageCrop]]:
        if not submission_ids:
            return {}
        result = await self._session.execute(
            select(PassportImageCropModel).where(
                PassportImageCropModel.submission_id.in_(set(submission_ids))
            )
        )
        values: dict[uuid.UUID, dict[PassportImageType, PassportImageCrop]] = {}
        for model in result.scalars().all():
            crop = self._to_value(model)
            values.setdefault(crop.submission_id, {})[crop.image_type] = crop
        return values

    async def upsert(
        self,
        *,
        submission_id: uuid.UUID,
        image_type: PassportImageType,
        source_storage_key: str,
        edit_source_storage_key: str | None,
        derived_storage_key: str,
        x: float,
        y: float,
        width: float,
        height: float,
        rotation_degrees: int,
        sharpness: float,
        source_width: int,
        source_height: int,
        updated_by_user_id: uuid.UUID,
        expected_revision: int | None,
        sharpness_algorithm_version: int = 2,
    ) -> tuple[PassportImageCrop, str | None, str | None]:
        result = await self._session.execute(
            select(PassportImageCropModel)
            .where(
                PassportImageCropModel.submission_id == submission_id,
                PassportImageCropModel.image_type == image_type.value,
            )
            .with_for_update()
        )
        model = result.scalar_one_or_none()
        current_revision = model.revision if model else 0
        if expected_revision is not None and expected_revision != current_revision:
            raise PassportImageCropRevisionConflict(current_revision)

        previous_derived_key = model.derived_storage_key if model else None
        previous_edit_source_key = model.edit_source_storage_key if model else None
        now = datetime.now(tz=UTC)
        if model is None:
            model = PassportImageCropModel(
                submission_id=submission_id,
                image_type=image_type.value,
                source_storage_key=source_storage_key,
                edit_source_storage_key=edit_source_storage_key,
                derived_storage_key=derived_storage_key,
                active=True,
                crop_x=x,
                crop_y=y,
                crop_width=width,
                crop_height=height,
                rotation_degrees=rotation_degrees,
                sharpness=sharpness,
                sharpness_algorithm_version=sharpness_algorithm_version,
                source_width=source_width,
                source_height=source_height,
                revision=1,
                updated_by_user_id=updated_by_user_id,
                created_at=now,
                updated_at=now,
            )
            self._session.add(model)
        else:
            model.source_storage_key = source_storage_key
            model.edit_source_storage_key = edit_source_storage_key
            model.derived_storage_key = derived_storage_key
            model.active = True
            model.crop_x = x
            model.crop_y = y
            model.crop_width = width
            model.crop_height = height
            model.rotation_degrees = rotation_degrees
            model.sharpness = sharpness
            model.sharpness_algorithm_version = sharpness_algorithm_version
            model.source_width = source_width
            model.source_height = source_height
            model.revision += 1
            model.updated_by_user_id = updated_by_user_id
            model.updated_at = now
        await self._session.flush()
        return self._to_value(model), previous_derived_key, previous_edit_source_key

    async def reset(
        self,
        *,
        submission_id: uuid.UUID,
        image_type: PassportImageType,
        updated_by_user_id: uuid.UUID,
        expected_revision: int | None,
    ) -> tuple[PassportImageCrop | None, str | None, str | None]:
        result = await self._session.execute(
            select(PassportImageCropModel)
            .where(
                PassportImageCropModel.submission_id == submission_id,
                PassportImageCropModel.image_type == image_type.value,
            )
            .with_for_update()
        )
        model = result.scalar_one_or_none()
        current_revision = model.revision if model else 0
        if expected_revision is not None and expected_revision != current_revision:
            raise PassportImageCropRevisionConflict(current_revision)
        if model is None:
            return None, None, None
        if not model.active and not model.derived_storage_key and not model.edit_source_storage_key:
            return self._to_value(model), None, None

        previous_derived_key = model.derived_storage_key
        previous_edit_source_key = model.edit_source_storage_key
        model.active = False
        model.derived_storage_key = None
        model.edit_source_storage_key = None
        model.sharpness = 1.0
        model.sharpness_algorithm_version = 1
        model.revision += 1
        model.updated_by_user_id = updated_by_user_id
        model.updated_at = datetime.now(tz=UTC)
        await self._session.flush()
        return self._to_value(model), previous_derived_key, previous_edit_source_key

    async def derived_storage_keys(
        self,
        submission_ids: list[uuid.UUID] | set[uuid.UUID],
    ) -> list[str]:
        if not submission_ids:
            return []
        result = await self._session.execute(
            select(PassportImageCropModel.derived_storage_key).where(
                PassportImageCropModel.submission_id.in_(set(submission_ids)),
                PassportImageCropModel.derived_storage_key.is_not(None),
            )
        )
        return list(dict.fromkeys(key for key in result.scalars().all() if key))

    async def edit_storage_keys(
        self,
        submission_ids: list[uuid.UUID] | set[uuid.UUID],
    ) -> list[str]:
        if not submission_ids:
            return []
        result = await self._session.execute(
            select(PassportImageCropModel.edit_source_storage_key).where(
                PassportImageCropModel.submission_id.in_(set(submission_ids)),
                PassportImageCropModel.edit_source_storage_key.is_not(None),
            )
        )
        active_keys = [key for key in result.scalars().all() if key]
        library_result = await self._session.execute(
            select(PassportVisaAiImageModel.generated_storage_key).where(
                PassportVisaAiImageModel.submission_id.in_(set(submission_ids)),
            )
        )
        return list(
            dict.fromkeys(
                [
                    *active_keys,
                    *(key for key in library_result.scalars().all() if key),
                ]
            )
        )
