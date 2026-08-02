"""Celery entry point for bounded Group Companion push delivery."""

from __future__ import annotations

from celery.utils.log import get_task_logger

from app.application.mobile.notification_service import dispatch_mobile_push_batch
from app.application.mobile.push_provider import MobilePushProvider, get_mobile_push_provider
from app.core.config.settings import get_settings
from app.infrastructure.celery_async_runtime import celery_async_runtime
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.mobile_push import MOBILE_PUSH_DISPATCH_TASK
from app.infrastructure.processing.celery_app import celery_app

logger = get_task_logger(__name__)


@celery_app.task(
    bind=True,
    name=MOBILE_PUSH_DISPATCH_TASK,
    queue="passport_ocr",
    max_retries=0,
)  # type: ignore[untyped-decorator]
def dispatch_mobile_push_notifications(self: object) -> int:
    del self
    settings = get_settings()
    provider = get_mobile_push_provider(settings.mobile)
    if not settings.mobile.enabled or not provider.enabled:
        return 0
    try:
        return celery_async_runtime.run(
            _dispatch_mobile_push(provider=provider, limit=settings.mobile.push_batch_size)
        )
    except Exception as exc:
        # The transaction rolls back, leaving the durable queue retryable on
        # the next beat.  Logs contain only the exception type, never tokens,
        # notification bodies, tenant IDs, or passenger IDs.
        logger.error(
            "mobile_push_dispatch_failed",
            extra={"error_type": type(exc).__name__},
        )
        return 0


async def _dispatch_mobile_push(*, provider: MobilePushProvider, limit: int) -> int:
    async with AsyncSessionFactory() as session:
        try:
            delivered = await dispatch_mobile_push_batch(
                session,
                provider=provider,
                limit=limit,
            )
            await session.commit()
            return delivered
        except Exception:
            await session.rollback()
            raise


__all__ = ["dispatch_mobile_push_notifications"]
