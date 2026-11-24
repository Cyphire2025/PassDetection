"""Finish owned native image writes before request-failure compensation."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions.exceptions import StorageError
from app.infrastructure.documents.storage_transfers import (
    finish_cleanup_despite_cancellation,
    run_bounded_storage_operations,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.routes.passport_routes.image_support import (
    _delete_crop_derivative_best_effort,
)


async def write_passport_image_objects(
    storage: MinioStorageRepository,
    objects: Sequence[tuple[bytes, str, str]],
    *,
    submission_id: uuid.UUID,
) -> None:
    """Retain sequential writes and compensate only their unique request keys."""

    async def upload() -> None:
        for content, key, content_type in objects:
            await storage.upload_file(content, key, content_type)

    async def cleanup() -> None:
        for _, key, _ in objects:
            await _delete_crop_derivative_best_effort(storage, key, submission_id=submission_id)

    try:
        await run_bounded_storage_operations([upload], concurrency=1)
    except BaseException as exc:
        await finish_cleanup_despite_cancellation(cleanup())
        if isinstance(exc, StorageError):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=exc.message,
            ) from exc
        raise


async def compensate_passport_image_failure(
    session: AsyncSession,
    storage: MinioStorageRepository,
    keys: Sequence[str],
    *,
    submission_id: uuid.UUID,
    commit_attempted: bool,
) -> None:
    """Roll back and finish owned cleanup, retaining uncertain committed objects."""

    async def compensate() -> None:
        try:
            await session.rollback()
        finally:
            if not commit_attempted:
                for key in keys:
                    await _delete_crop_derivative_best_effort(
                        storage,
                        key,
                        submission_id=submission_id,
                    )

    await finish_cleanup_despite_cancellation(compensate())
