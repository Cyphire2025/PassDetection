"""Celery entry points for durable workforce identity housekeeping."""

from __future__ import annotations

from celery.utils.log import get_task_logger

from app.infrastructure.celery_async_runtime import celery_async_runtime
from app.infrastructure.processing.celery_app import celery_app
from app.infrastructure.security.identity_notifications import (
    deliver_due_identity_notifications,
)
from app.infrastructure.security.identity_retention import (
    IdentityRetentionResult,
    apply_identity_retention,
)

logger = get_task_logger(__name__)


@celery_app.task(  # type: ignore[untyped-decorator]  # Celery exposes an untyped decorator.
    name="identity.deliver_recovery_notifications",
    queue="passport_ocr",
)
def deliver_recovery_notifications() -> int:
    try:
        return celery_async_runtime.run(deliver_due_identity_notifications())
    except Exception as exc:
        logger.error(
            "identity_recovery_delivery_task_failed error_type=%s",
            type(exc).__name__,
        )
        raise


@celery_app.task(  # type: ignore[untyped-decorator]  # Celery exposes an untyped decorator.
    name="identity.apply_retention",
    queue="passport_ocr",
)
def apply_identity_record_retention() -> dict[str, int]:
    try:
        result: IdentityRetentionResult = celery_async_runtime.run(apply_identity_retention())
        return {
            "action_tokens": result.action_tokens,
            "auth_challenges": result.auth_challenges,
            "recovery_codes": result.recovery_codes,
            "notification_outbox": result.notification_outbox,
            "total": result.total,
        }
    except Exception as exc:
        logger.error(
            "identity_retention_task_failed error_type=%s",
            type(exc).__name__,
        )
        raise


__all__ = ["apply_identity_record_retention", "deliver_recovery_notifications"]
