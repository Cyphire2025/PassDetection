"""Non-destructive coordinator assignment expiry, independent of retention jobs."""

from __future__ import annotations

from celery.utils.log import get_task_logger

from app.infrastructure.celery_async_runtime import celery_async_runtime
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.processing.celery_app import celery_app
from app.infrastructure.repositories.coordinator_assignment_lifecycle import (
    expire_coordinator_assignments,
)

logger = get_task_logger(__name__)
COORDINATOR_ASSIGNMENT_EXPIRY_TASK = "coordinators.expire_trip_assignments"


@celery_app.task(  # type: ignore[untyped-decorator]
    name=COORDINATOR_ASSIGNMENT_EXPIRY_TASK,
    queue="passport_ocr",
    max_retries=0,
)
def expire_trip_coordinator_assignments() -> dict[str, int]:
    """Expire one bounded page; the next minute safely resumes remaining work."""

    try:
        return celery_async_runtime.run(_expire_and_commit())
    except Exception as exc:
        logger.error("coordinator_assignment_expiry_failed error_type=%s", type(exc).__name__)
        raise


async def _expire_and_commit() -> dict[str, int]:
    async with AsyncSessionFactory() as session:
        try:
            result = await expire_coordinator_assignments(session)
            await session.commit()
            return result.as_dict()
        except Exception:
            await session.rollback()
            raise
