"""Complete owned import compensation before reporting an uncertain save outcome."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import NoReturn

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.documents.passport_import_compensation import (
    reconcile_failed_passport_import,
)
from app.infrastructure.documents.storage_transfers import finish_cleanup_despite_cancellation


async def compensate_failed_document_import(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    import_id: uuid.UUID,
    uploaded_keys: Sequence[str],
    commit_attempted: bool,
    error: BaseException,
) -> NoReturn:
    """Retain unknown committed references and propagate request cancellation."""

    async def compensate() -> None:
        try:
            await session.rollback()
        finally:
            await reconcile_failed_passport_import(
                agency_id=agency_id,
                import_id=import_id,
                uploaded_keys=uploaded_keys,
                commit_attempted=commit_attempted,
            )

    await finish_cleanup_despite_cancellation(compensate())
    if not isinstance(error, Exception):
        raise error
    _raise_http_import_failure(error)


def _raise_http_import_failure(error: Exception) -> NoReturn:
    if isinstance(error, HTTPException):
        raise error
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=(
            "The import result could not be confirmed. Refresh the group "
            "before retrying; saved documents have been preserved."
        ),
    ) from error
