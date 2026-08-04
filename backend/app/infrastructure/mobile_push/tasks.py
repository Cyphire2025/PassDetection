"""Celery entry point for bounded Group Companion push delivery."""

from __future__ import annotations

from datetime import timedelta

from celery.utils.log import get_task_logger

from app.application.mobile.notification_service import (
    dispatch_mobile_push_batch,
    reconcile_mobile_push_receipts,
)
from app.application.mobile.notification_service import (
    schedule_trip_countdown_notifications as reconcile_trip_countdown_notifications,
)
from app.application.mobile.push_provider import MobilePushProvider, get_mobile_push_provider
from app.core.config.settings import get_settings
from app.infrastructure.celery_async_runtime import celery_async_runtime
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.mobile_push import (
    MOBILE_PUSH_COUNTDOWN_TASK,
    MOBILE_PUSH_DISPATCH_TASK,
    MOBILE_PUSH_RECEIPT_TASK,
)
from app.infrastructure.processing.celery_app import celery_app

logger = get_task_logger(__name__)


@celery_app.task(
    bind=True,
    name=MOBILE_PUSH_COUNTDOWN_TASK,
    queue="passport_ocr",
    max_retries=0,
)  # type: ignore[untyped-decorator]
def schedule_mobile_trip_countdowns(self: object) -> int:
    del self
    settings = get_settings()
    provider = get_mobile_push_provider(settings.mobile)
    if not settings.mobile.enabled or not provider.enabled:
        return 0
    try:
        return int(
            celery_async_runtime.run(
                _schedule_mobile_trip_countdowns(
                    timezone_name=settings.mobile.push_countdown_timezone,
                    send_hour=settings.mobile.push_countdown_send_hour,
                )
            )
        )
    except Exception as exc:
        logger.error(
            "mobile_push_countdown_schedule_failed",
            extra={"error_type": type(exc).__name__},
        )
        return 0


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
        return int(
            celery_async_runtime.run(
                _dispatch_mobile_push(
                    provider=provider,
                    limit=settings.mobile.push_batch_size,
                    max_send_attempts=settings.mobile.push_max_send_attempts,
                    retry_base_seconds=settings.mobile.push_retry_base_seconds,
                    receipt_initial_delay_seconds=(
                        settings.mobile.push_receipt_initial_delay_seconds
                    ),
                )
            )
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


@celery_app.task(
    bind=True,
    name=MOBILE_PUSH_RECEIPT_TASK,
    queue="passport_ocr",
    max_retries=0,
)  # type: ignore[untyped-decorator]
def reconcile_mobile_push_delivery_receipts(self: object) -> int:
    del self
    settings = get_settings()
    provider = get_mobile_push_provider(settings.mobile)
    if not settings.mobile.enabled or not provider.enabled:
        return 0
    try:
        return int(
            celery_async_runtime.run(
                _reconcile_mobile_push_receipts(
                    provider=provider,
                    limit=settings.mobile.push_receipt_batch_size,
                    max_attempts=settings.mobile.push_receipt_max_attempts,
                    max_age=timedelta(
                        hours=settings.mobile.push_receipt_max_age_hours
                    ),
                    retry_base_seconds=settings.mobile.push_retry_base_seconds,
                )
            )
        )
    except Exception as exc:
        logger.error(
            "mobile_push_receipt_reconciliation_failed",
            extra={"error_type": type(exc).__name__},
        )
        return 0


async def _dispatch_mobile_push(
    *,
    provider: MobilePushProvider,
    limit: int,
    max_send_attempts: int,
    retry_base_seconds: int,
    receipt_initial_delay_seconds: int,
) -> int:
    async with AsyncSessionFactory() as session:
        try:
            delivered = await dispatch_mobile_push_batch(
                session,
                provider=provider,
                limit=limit,
                max_send_attempts=max_send_attempts,
                retry_base_seconds=retry_base_seconds,
                receipt_initial_delay_seconds=receipt_initial_delay_seconds,
            )
            await session.commit()
            return delivered
        except Exception:
            await session.rollback()
            raise


async def _schedule_mobile_trip_countdowns(
    *,
    timezone_name: str,
    send_hour: int,
) -> int:
    async with AsyncSessionFactory() as session:
        try:
            counts = await reconcile_trip_countdown_notifications(
                session,
                timezone_name=timezone_name,
                send_hour=send_hour,
            )
            await session.commit()
            return counts.inserted + counts.cancelled
        except Exception:
            await session.rollback()
            raise


async def _reconcile_mobile_push_receipts(
    *,
    provider: MobilePushProvider,
    limit: int,
    max_attempts: int,
    max_age: timedelta,
    retry_base_seconds: int,
) -> int:
    async with AsyncSessionFactory() as session:
        try:
            delivered = await reconcile_mobile_push_receipts(
                session,
                provider=provider,
                limit=limit,
                max_attempts=max_attempts,
                max_age=max_age,
                retry_base_seconds=retry_base_seconds,
            )
            await session.commit()
            return delivered
        except Exception:
            await session.rollback()
            raise


__all__ = [
    "dispatch_mobile_push_notifications",
    "reconcile_mobile_push_delivery_receipts",
    "schedule_mobile_trip_countdowns",
]
