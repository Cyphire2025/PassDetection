"""Celery tasks for queued WhatsApp broadcasts."""

from __future__ import annotations

import asyncio

from celery.utils.log import get_task_logger

from app.application.use_cases.whatsapp.message_templates import WhatsAppMessageType
from app.infrastructure.processing.celery_app import celery_app
from app.infrastructure.whatsapp.worker_runtime import (
    mark_whatsapp_batch_failed,
    run_whatsapp_broadcast,
)

logger = get_task_logger(__name__)


@celery_app.task(
    bind=True,
    name="whatsapp.process_broadcast",
    queue="whatsapp",
    max_retries=2,
    default_retry_delay=10,
)
def process_whatsapp_broadcast(
    self,  # type: ignore[no-untyped-def]
    *,
    batch_id: str,
    message_type: WhatsAppMessageType,
    message_content: str,
    passport_link: str | None,
) -> None:
    try:
        asyncio.run(
            run_whatsapp_broadcast(
                batch_id=batch_id,
                message_type=message_type,
                message_content=message_content,
                passport_link=passport_link,
            )
        )
    except Exception as exc:
        logger.exception("whatsapp_broadcast_task_failed batch_id=%s", batch_id)
        if self.request.retries >= self.max_retries:
            asyncio.run(
                mark_whatsapp_batch_failed(
                    batch_id=batch_id,
                    error_message=f"WhatsApp worker failed after retries: {exc}",
                )
            )
            raise
        raise self.retry(exc=exc) from exc
