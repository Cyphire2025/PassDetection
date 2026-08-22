"""Celery entry point for operational policy enforcement."""

from __future__ import annotations

from celery.utils.log import get_task_logger

from app.infrastructure.celery_async_runtime import celery_async_runtime
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.platform_lifecycle import apply_platform_lifecycle_policies
from app.infrastructure.processing.celery_app import celery_app

logger = get_task_logger(__name__)
PLATFORM_LIFECYCLE_TASK = "platform.apply_lifecycle_policies"


@celery_app.task(  # type: ignore[untyped-decorator]
    name=PLATFORM_LIFECYCLE_TASK,
    queue="passport_ocr",
    max_retries=0,
)
def enforce_platform_lifecycle_policies() -> dict[str, int]:
    """Apply one bounded page; Celery Beat safely resumes on the next run."""

    try:
        return celery_async_runtime.run(_apply_and_commit())
    except Exception as exc:
        logger.error(
            "platform_lifecycle_policy_task_failed error_type=%s",
            type(exc).__name__,
        )
        raise


async def _apply_and_commit() -> dict[str, int]:
    async with AsyncSessionFactory() as session:
        try:
            result = await apply_platform_lifecycle_policies(session)
            await session.commit()
            return result.as_dict()
        except Exception:
            await session.rollback()
            raise
