"""Reconcile failed passport imports without deleting committed documents."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging.logger import get_logger
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.documents.storage_cleanup import stage_storage_cleanup_jobs
from app.infrastructure.repositories.passport_image_library_repository import (
    PassportImageLibraryRepository,
)

logger = get_logger(__name__)


async def reconcile_failed_passport_import(
    *,
    agency_id: uuid.UUID,
    import_id: uuid.UUID,
    uploaded_keys: Sequence[str],
    commit_attempted: bool,
    session_factory: async_sessionmaker[AsyncSession] = AsyncSessionFactory,
) -> bool:
    """Persist retryable cleanup only after fresh committed-reference inspection.

    A connection exception cannot tell us whether PostgreSQL committed. Never
    use the failed session, or delete objects directly in an exception handler.
    Unique import keys cannot be claimed by another concurrent import. If the
    database remains unavailable, retention is safer than deleting uncertain
    data; the failure event identifies the import for operational recovery.
    """
    keys = list(dict.fromkeys(uploaded_keys))
    if not keys:
        return True
    try:
        async with session_factory() as session:
            async with session.begin():
                columns = (
                    PassportSubmissionModel.image_s3_key,
                    PassportSubmissionModel.passport_photo_s3_key,
                    PassportSubmissionModel.passport_back_s3_key,
                )
                rows = await session.execute(
                    select(*columns).where(or_(*(column.in_(keys) for column in columns)))
                )
                referenced = {key for row in rows for key in row if key in keys}
                referenced.update(
                    await PassportImageLibraryRepository(session).referenced_storage_keys(keys)
                )
                stage_storage_cleanup_jobs(
                    session,
                    agency_id=agency_id,
                    source="passport_submission_delete",
                    context_id=f"passport-import-compensation:{import_id}",
                    storage_keys=[key for key in keys if key not in referenced],
                )
        return True
    except Exception as exc:
        logger.error(
            "passport_import_compensation_deferred",
            import_id=str(import_id),
            agency_id=str(agency_id),
            object_count=len(keys),
            commit_attempted=commit_attempted,
            error_type=type(exc).__name__,
        )
        return False
