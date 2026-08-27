"""Celery entry point for operational policy enforcement."""

from __future__ import annotations

from datetime import UTC, datetime

from celery.utils.log import get_task_logger
from redis import Redis

from app.core.config.settings import get_settings
from app.infrastructure.celery_async_runtime import celery_async_runtime
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.operational_retention import apply_operational_retention
from app.infrastructure.platform_lifecycle import apply_platform_lifecycle_policies
from app.infrastructure.processing.celery_app import celery_app

logger = get_task_logger(__name__)
PLATFORM_LIFECYCLE_TASK = "platform.apply_lifecycle_policies"
PLATFORM_SCHEDULER_HEARTBEAT_TASK = "platform.scheduler_heartbeat"
PLATFORM_SCHEDULER_HEARTBEAT_KEY = (
    "passdetection:platform:scheduler-heartbeat:v1"
)


@celery_app.task(  # type: ignore[untyped-decorator]
    name=PLATFORM_SCHEDULER_HEARTBEAT_TASK,
    queue="passport_ocr",
    max_retries=0,
)
def record_platform_scheduler_heartbeat() -> None:
    """Publish expiring proof that Beat and the lifecycle worker are alive."""

    settings = get_settings()
    timeout = min(settings.processing_worker_ping_timeout_seconds, 1.0)
    client = Redis.from_url(
        settings.redis.broker_url,
        socket_connect_timeout=timeout,
        socket_timeout=timeout,
        decode_responses=True,
    )
    try:
        client.setex(
            PLATFORM_SCHEDULER_HEARTBEAT_KEY,
            90,
            datetime.now(tz=UTC).isoformat(),
        )
    except Exception as exc:
        logger.error(
            "platform_scheduler_heartbeat_failed error_type=%s",
            type(exc).__name__,
        )
    finally:
        client.close()


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
            operational = await apply_operational_retention(session)
            await session.commit()
            return {**result.as_dict(), **operational.as_dict()}
        except Exception:
            await session.rollback()
            raise
