"""Celery tasks for queued WhatsApp broadcasts."""

from __future__ import annotations

from celery.utils.log import get_task_logger

from app.application.use_cases.whatsapp.message_templates import WhatsAppMessageType
from app.infrastructure.celery_async_runtime import celery_async_runtime
from app.infrastructure.processing.celery_app import celery_app
from app.infrastructure.whatsapp.document_delivery_runtime import (
    mark_document_batch_failed,
    run_document_whatsapp_broadcast,
)
from app.infrastructure.whatsapp.qr_delivery_runtime import (
    mark_qr_batch_failed,
    run_qr_whatsapp_broadcast,
)
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
    header_image_id: str | None = None,
    passport_intro: str | None = None,
) -> None:
    try:
        celery_async_runtime.run(
            run_whatsapp_broadcast(
                batch_id=batch_id,
                message_type=message_type,
                message_content=message_content,
                passport_intro=passport_intro,
                passport_link=passport_link,
                header_image_id=header_image_id,
            )
        )
    except Exception as exc:
        logger.error(
            "whatsapp_broadcast_task_failed batch_id=%s error_type=%s",
            batch_id,
            type(exc).__name__,
        )
        if self.request.retries >= self.max_retries:
            celery_async_runtime.run(
                mark_whatsapp_batch_failed(
                    batch_id=batch_id,
                    error_message=(
                        "WHATSAPP_WORKER_FAILED: WhatsApp delivery worker failed "
                        "after bounded retries"
                    ),
                )
            )
            raise
        raise self.retry(exc=exc) from exc


@celery_app.task(
    bind=True,
    name="whatsapp.process_document_broadcast",
    queue="whatsapp",
    max_retries=2,
    default_retry_delay=10,
)
def process_document_whatsapp_broadcast(
    self,  # type: ignore[no-untyped-def]
    *,
    send_batch_id: str,
) -> None:
    try:
        celery_async_runtime.run(
            run_document_whatsapp_broadcast(send_batch_id=send_batch_id)
        )
    except Exception as exc:
        logger.error(
            "document_whatsapp_task_failed send_batch_id=%s error_type=%s",
            send_batch_id,
            type(exc).__name__,
        )
        if self.request.retries >= self.max_retries:
            celery_async_runtime.run(
                mark_document_batch_failed(
                    send_batch_id=send_batch_id,
                    error_message=(
                        "WHATSAPP_WORKER_FAILED: Document delivery worker failed "
                        "after bounded retries"
                    ),
                )
            )
            raise
        raise self.retry(exc=exc) from exc


@celery_app.task(
    bind=True,
    name="whatsapp.process_qr_broadcast",
    queue="whatsapp",
    max_retries=2,
    default_retry_delay=10,
)
def process_qr_whatsapp_broadcast(
    self,  # type: ignore[no-untyped-def]
    *,
    send_batch_id: str,
) -> None:
    try:
        celery_async_runtime.run(
            run_qr_whatsapp_broadcast(send_batch_id=send_batch_id)
        )
    except Exception as exc:
        logger.error(
            "qr_whatsapp_task_failed send_batch_id=%s error_type=%s",
            send_batch_id,
            type(exc).__name__,
        )
        if self.request.retries >= self.max_retries:
            celery_async_runtime.run(
                mark_qr_batch_failed(
                    send_batch_id=send_batch_id,
                    error_message=(
                        "WHATSAPP_WORKER_FAILED: QR delivery worker failed "
                        "after bounded retries"
                    ),
                )
            )
            raise
        raise self.retry(exc=exc) from exc
