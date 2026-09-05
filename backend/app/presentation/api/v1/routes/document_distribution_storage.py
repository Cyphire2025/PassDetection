"""Document distribution: storage."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from functools import wraps

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import DocumentWhatsAppDeliveryModel
from app.infrastructure.documents.storage_cleanup import persist_storage_cleanup_job
from app.infrastructure.documents.storage_transfers import finish_cleanup_despite_cancellation
from app.infrastructure.documents.verification_staging import cleanup_staged_storage_keys
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.routes.document_distribution_shared import (
    _REQUEST_STAGING_CLEANUP_KEYS,
    _RETRYABLE_STAGING_HTTP_STATUSES,
    DOCUMENT_DELIVERY_ACCEPTED_STATUSES,
    _UploadParameters,
    _UploadResult,
    logger,
)


class _ConcurrentDocumentChunkReplay(Exception):
    """Internal control flow after an exact chunk wins a persistence race."""


async def _cleanup_distribution_storage_keys(
    storage_keys: list[str],
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    document_type: str,
) -> None:
    """Best-effort pre-commit compensation that preserves the root failure."""

    if not storage_keys:
        return
    try:
        await MinioStorageRepository().delete_files(storage_keys)
    except Exception:
        logger.warning(
            "document_distribution_storage_cleanup_deferred",
            group_id=str(group_id),
            document_type=document_type,
            object_count=len(storage_keys),
        )
        try:
            await persist_storage_cleanup_job(
                agency_id=agency_id,
                source="document_distribution_compensation",
                context_id=f"{group_id}:{document_type}",
                storage_keys=storage_keys,
            )
        except Exception as exc:
            logger.error(
                "document_distribution_cleanup_tracking_failed",
                group_id=str(group_id),
                document_type=document_type,
                object_count=len(storage_keys),
                error_type=type(exc).__name__,
            )


async def _released_document_passenger_ids(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    document_ids: list[uuid.UUID],
) -> tuple[uuid.UUID, ...]:
    """Return passengers whose selected documents are currently mobile-visible."""

    if not document_ids:
        return ()
    result = await session.execute(
        select(DocumentWhatsAppDeliveryModel.passenger_id).where(
            DocumentWhatsAppDeliveryModel.distributed_document_id.in_(document_ids),
            DocumentWhatsAppDeliveryModel.agency_id == agency_id,
            DocumentWhatsAppDeliveryModel.group_id == group_id,
            DocumentWhatsAppDeliveryModel.passenger_id.is_not(None),
            DocumentWhatsAppDeliveryModel.status.in_(DOCUMENT_DELIVERY_ACCEPTED_STATUSES),
        )
    )
    return tuple(
        sorted(
            {passenger_id for passenger_id in result.scalars() if passenger_id is not None},
            key=str,
        )
    )


def _remember_request_staging_keys(storage_keys: list[str] | tuple[str, ...]) -> None:
    remembered = _REQUEST_STAGING_CLEANUP_KEYS.get()
    if remembered is not None:
        remembered.extend(storage_keys)


async def _cleanup_remembered_request_staging() -> None:
    remembered = _REQUEST_STAGING_CLEANUP_KEYS.get()
    if not remembered:
        return
    keys = list(dict.fromkeys(remembered))
    await cleanup_staged_storage_keys(keys)
    remembered.clear()


def _with_staging_cleanup(
    handler: Callable[_UploadParameters, Awaitable[_UploadResult]],
) -> Callable[_UploadParameters, Awaitable[_UploadResult]]:
    """Clean staged objects after commit or terminal request rejection only."""

    @wraps(handler)
    async def wrapped(
        *args: _UploadParameters.args,
        **kwargs: _UploadParameters.kwargs,
    ) -> _UploadResult:
        cleanup_keys: list[str] = []
        context_token = _REQUEST_STAGING_CLEANUP_KEYS.set(cleanup_keys)
        try:
            result = await handler(*args, **kwargs)
        except HTTPException as exc:
            if (
                status.HTTP_400_BAD_REQUEST
                <= exc.status_code
                < status.HTTP_500_INTERNAL_SERVER_ERROR
                and exc.status_code not in _RETRYABLE_STAGING_HTTP_STATUSES
            ):
                await finish_cleanup_despite_cancellation(_cleanup_remembered_request_staging())
            raise
        else:
            await finish_cleanup_despite_cancellation(_cleanup_remembered_request_staging())
            return result
        finally:
            _REQUEST_STAGING_CLEANUP_KEYS.reset(context_token)

    return wrapped
