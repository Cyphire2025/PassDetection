"""Finish rollback and owned-object compensation before returning the root failure."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence

import anyio
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.documents.storage_transfers import finish_cleanup_despite_cancellation
from app.presentation.api.v1.routes.document_distribution_storage import (
    _cleanup_distribution_storage_keys,
)


async def compensate_uncommitted_document_upload(
    session: AsyncSession,
    *,
    storage_keys: Sequence[str],
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    document_type: str,
) -> None:
    """Called only before commit is attempted; the caller re-raises its failure."""
    owned_keys = tuple(storage_keys)

    async def rollback_and_cleanup() -> None:
        # Preserve transaction-before-storage order and ordinary failure
        # precedence. Post-commit ambiguous outcomes never enter this path.
        await session.rollback()
        await _cleanup_distribution_storage_keys(
            list(owned_keys),
            agency_id=agency_id,
            group_id=group_id,
            document_type=document_type,
        )

    with anyio.CancelScope(shield=True):
        cleanup_task = asyncio.create_task(rollback_and_cleanup())
        try:
            await finish_cleanup_despite_cancellation(cleanup_task)
        except asyncio.CancelledError:
            if cleanup_task.cancelled():
                raise  # A cleanup-worker cancellation retains its precedence.
            # Additional request cancellation cannot replace the caller's
            # original failure after its owned cleanup has completed.
