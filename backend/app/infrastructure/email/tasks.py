"""Celery entry points for scheduled, server-side email monitoring."""

from __future__ import annotations

import uuid
from dataclasses import dataclass as dataclass
from datetime import UTC as UTC
from datetime import datetime as datetime
from datetime import timedelta as timedelta

from celery.utils.log import get_task_logger as get_task_logger
from redis import Redis as Redis
from sqlalchemy import delete as delete
from sqlalchemy import or_ as or_
from sqlalchemy import select as select
from sqlalchemy import update as update

from app.core.config.settings import get_settings as get_settings
from app.infrastructure.celery_async_runtime import celery_async_runtime as celery_async_runtime
from app.infrastructure.database.email_ai_models import (
    EmailActionProposalModel as EmailActionProposalModel,
)
from app.infrastructure.database.email_ai_models import EmailAiAnalysisModel as EmailAiAnalysisModel
from app.infrastructure.database.email_ai_models import EmailAiFeedbackModel as EmailAiFeedbackModel
from app.infrastructure.database.email_ai_models import (
    EmailDetectedDeadlineModel as EmailDetectedDeadlineModel,
)
from app.infrastructure.database.email_ai_models import EmailReplyDraftModel as EmailReplyDraftModel
from app.infrastructure.database.email_models import EmailArtifactModel as EmailArtifactModel
from app.infrastructure.database.email_models import EmailConnectionModel as EmailConnectionModel
from app.infrastructure.database.email_models import EmailMessageModel as EmailMessageModel
from app.infrastructure.database.email_models import EmailOAuthStateModel as EmailOAuthStateModel
from app.infrastructure.database.models import DistributedDocumentModel as DistributedDocumentModel
from app.infrastructure.database.models import NotificationModel as NotificationModel
from app.infrastructure.database.session import AsyncSessionFactory as AsyncSessionFactory
from app.infrastructure.email.readiness import (
    EMAIL_SCHEDULER_HEARTBEAT_KEY as EMAIL_SCHEDULER_HEARTBEAT_KEY,
)
from app.infrastructure.email.storage_reconciliation import (
    _EMAIL_STORAGE_PREFIXES as _EMAIL_STORAGE_PREFIXES,
)
from app.infrastructure.email.storage_reconciliation import (
    _EMAIL_STORAGE_RECONCILE_PAGE_SIZE as _EMAIL_STORAGE_RECONCILE_PAGE_SIZE,
)
from app.infrastructure.email.storage_reconciliation import (
    _delete_unreferenced_email_storage_keys as _delete_unreferenced_email_storage_keys,
)
from app.infrastructure.email.storage_reconciliation import (
    _reconcile_orphaned_email_storage as _reconcile_orphaned_email_storage,
)
from app.infrastructure.email.storage_reconciliation import (
    _storage_object_is_older_than as _storage_object_is_older_than,
)
from app.infrastructure.email.sync_service import run_connection_sync as run_connection_sync
from app.infrastructure.email.task_dispatch import (
    EmailSyncTaskEnvelope as EmailSyncTaskEnvelope,
)
from app.infrastructure.email.task_dispatch import (
    _claim_due_dispatches as _claim_due_dispatches,
)
from app.infrastructure.email.task_retention import _apply_email_retention as _apply_email_retention
from app.infrastructure.processing.celery_app import celery_app as celery_app
from app.infrastructure.storage.minio_repository import (
    MinioStorageRepository as MinioStorageRepository,
)

logger = get_task_logger(__name__)

EMAIL_INTEGRATION_QUEUE = "email_integrations"
EMAIL_SYNC_TASK = "email.sync_connection"
EMAIL_DISPATCH_TASK = "email.dispatch_due_connections"
EMAIL_RETENTION_TASK = "email.apply_retention"
EMAIL_SCHEDULER_HEARTBEAT_TASK = "email.scheduler_heartbeat"

# Celery's task decorator is dynamically typed in the installed Celery release.
# The four narrow suppressions below cover only that third-party decorator boundary;
# every task body and callable signature remains strictly type checked.


@celery_app.task(
    bind=True,
    name=EMAIL_SYNC_TASK,
    queue=EMAIL_INTEGRATION_QUEUE,
    max_retries=0,
)  # type: ignore[untyped-decorator]
def sync_email_connection(
    self: object,
    *,
    connection_id: str | uuid.UUID,
    agency_id: str | uuid.UUID | None = None,
    owner_user_id: str | uuid.UUID | None = None,
    provider_account_id: str | None = None,
    sync_generation: int | str | None = None,
    provider_message_id: str | None = None,
) -> None:
    del self
    try:
        if agency_id is None or owner_user_id is None or sync_generation is None:
            raise ValueError("Invalid email sync envelope")
        parsed_id = (
            connection_id if isinstance(connection_id, uuid.UUID) else uuid.UUID(connection_id)
        )
        parsed_agency_id = agency_id if isinstance(agency_id, uuid.UUID) else uuid.UUID(agency_id)
        parsed_owner_user_id = (
            owner_user_id if isinstance(owner_user_id, uuid.UUID) else uuid.UUID(owner_user_id)
        )
        parsed_generation = int(sync_generation)
        if (
            not isinstance(provider_account_id, str)
            or not provider_account_id.strip()
            or parsed_generation < 0
        ):
            raise ValueError("Invalid email sync envelope")
    except (AttributeError, TypeError, ValueError):
        logger.warning("email_sync_task_invalid_envelope")
        return
    try:
        celery_async_runtime.run(
            run_connection_sync(
                parsed_id,
                provider_message_id=provider_message_id,
                agency_id=parsed_agency_id,
                owner_user_id=parsed_owner_user_id,
                provider_account_id=provider_account_id,
                sync_generation=parsed_generation,
            )
        )
    except Exception as exc:
        # The durable connection row records a safe failure and next retry
        # time. Beat will redeliver it without relying on broker retry state.
        logger.error(
            "email_sync_task_failed",
            extra={
                "connection_id": connection_id,
                "error_type": type(exc).__name__,
            },
        )


@celery_app.task(
    bind=True,
    name=EMAIL_DISPATCH_TASK,
    queue=EMAIL_INTEGRATION_QUEUE,
    max_retries=0,
)  # type: ignore[untyped-decorator]
def dispatch_due_email_connections(self: object) -> int:
    del self
    settings = get_settings()
    if not (settings.email_integrations_enabled and settings.email_sync_enabled):
        return 0
    envelopes = celery_async_runtime.run(_claim_due_dispatches())
    published = 0
    for envelope in envelopes:
        try:
            task_kwargs = envelope.task_kwargs()
            sync_email_connection.apply_async(
                kwargs=task_kwargs,
                queue=EMAIL_INTEGRATION_QUEUE,
            )
            published += 1
        except Exception as exc:
            logger.error(
                "email_sync_dispatch_failed",
                extra={
                    "connection_id": str(envelope.connection_id),
                    "error_type": type(exc).__name__,
                },
            )
    return published


@celery_app.task(
    bind=True,
    name=EMAIL_RETENTION_TASK,
    queue=EMAIL_INTEGRATION_QUEUE,
    max_retries=0,
)  # type: ignore[untyped-decorator]
def apply_email_retention(self: object) -> int:
    del self
    try:
        return celery_async_runtime.run(_apply_email_retention())
    except Exception as exc:
        logger.error(
            "email_retention_task_failed",
            extra={"error_type": type(exc).__name__},
        )
        return 0


@celery_app.task(
    bind=True,
    name=EMAIL_SCHEDULER_HEARTBEAT_TASK,
    queue=EMAIL_INTEGRATION_QUEUE,
    max_retries=0,
)  # type: ignore[untyped-decorator]
def record_email_scheduler_heartbeat(self: object) -> None:
    del self
    settings = get_settings()
    client = Redis.from_url(
        settings.redis.broker_url,
        socket_connect_timeout=settings.processing_worker_ping_timeout_seconds,
        socket_timeout=settings.processing_worker_ping_timeout_seconds,
        decode_responses=True,
    )
    try:
        client.setex(
            EMAIL_SCHEDULER_HEARTBEAT_KEY,
            180,
            datetime.now(tz=UTC).isoformat(),
        )
    except Exception as exc:
        logger.error(
            "email_scheduler_heartbeat_failed",
            extra={"error_type": type(exc).__name__},
        )
    finally:
        client.close()  # type: ignore[no-untyped-call]  # redis 5.0.7 omits this annotation
