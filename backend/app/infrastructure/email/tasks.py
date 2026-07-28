"""Celery entry points for scheduled, server-side email monitoring."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from celery.utils.log import get_task_logger
from redis import Redis
from sqlalchemy import delete, or_, select, update

from app.core.config.settings import get_settings
from app.infrastructure.celery_async_runtime import celery_async_runtime
from app.infrastructure.database.email_models import (
    EmailArtifactModel,
    EmailConnectionModel,
    EmailMessageModel,
    EmailOAuthStateModel,
)
from app.infrastructure.database.models import DistributedDocumentModel
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.email.readiness import EMAIL_SCHEDULER_HEARTBEAT_KEY
from app.infrastructure.email.sync_service import run_connection_sync
from app.infrastructure.processing.celery_app import celery_app
from app.infrastructure.storage.minio_repository import MinioStorageRepository

logger = get_task_logger(__name__)

EMAIL_INTEGRATION_QUEUE = "email_integrations"
EMAIL_SYNC_TASK = "email.sync_connection"
EMAIL_DISPATCH_TASK = "email.dispatch_due_connections"
EMAIL_RETENTION_TASK = "email.apply_retention"
EMAIL_SCHEDULER_HEARTBEAT_TASK = "email.scheduler_heartbeat"
_EMAIL_STORAGE_PREFIXES = (
    "email-integrations/",
    "email-integrations-canonical/",
)
_EMAIL_STORAGE_RECONCILE_PAGE_SIZE = 1_000


@celery_app.task(
    bind=True,
    name=EMAIL_SYNC_TASK,
    queue=EMAIL_INTEGRATION_QUEUE,
    max_retries=0,
)  # type: ignore[untyped-decorator]
def sync_email_connection(
    self: object,
    *,
    connection_id: str,
    provider_message_id: str | None = None,
) -> None:
    del self
    try:
        parsed_id = uuid.UUID(connection_id)
    except ValueError:
        logger.warning("email_sync_task_invalid_connection_id")
        return
    try:
        celery_async_runtime.run(
            run_connection_sync(
                parsed_id,
                provider_message_id=provider_message_id,
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
    connection_ids = celery_async_runtime.run(_claim_due_dispatches())
    published = 0
    for connection_id in connection_ids:
        try:
            sync_email_connection.apply_async(
                kwargs={"connection_id": str(connection_id)},
                queue=EMAIL_INTEGRATION_QUEUE,
            )
            published += 1
        except Exception as exc:
            logger.error(
                "email_sync_dispatch_failed",
                extra={
                    "connection_id": str(connection_id),
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
        settings.redis.url,
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
        client.close()  # type: ignore[no-untyped-call]


async def _claim_due_dispatches() -> list[uuid.UUID]:
    settings = get_settings()
    now = datetime.now(tz=UTC)
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(EmailConnectionModel)
            .where(
                EmailConnectionModel.status.in_({"active", "failing"}),
                EmailConnectionModel.next_sync_at.is_not(None),
                EmailConnectionModel.next_sync_at <= now,
                or_(
                    EmailConnectionModel.sync_lease_expires_at.is_(None),
                    EmailConnectionModel.sync_lease_expires_at <= now,
                ),
            )
            .order_by(EmailConnectionModel.next_sync_at.asc())
            .limit(100)
            .with_for_update(skip_locked=True)
        )
        connections = list(result.scalars().all())
        for connection in connections:
            connection.sync_state = "queued"
            connection.next_sync_at = now + timedelta(seconds=settings.email_sync_interval_seconds)
        await session.commit()
        return [connection.id for connection in connections]


async def _apply_email_retention() -> int:
    settings = get_settings()
    now = datetime.now(tz=UTC)
    content_cutoff = now - timedelta(days=settings.email_content_retention_days)
    oauth_cutoff = now - timedelta(days=1)
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(EmailArtifactModel)
            .where(
                EmailArtifactModel.storage_key.is_not(None),
                EmailArtifactModel.storage_key.like("email-integrations/%"),
                EmailArtifactModel.processing_status.in_({"completed", "duplicate", "ignored"}),
                EmailArtifactModel.updated_at < content_cutoff,
            )
            .order_by(EmailArtifactModel.updated_at.asc())
            .limit(500)
            .with_for_update(skip_locked=True)
        )
        artifacts = list(result.scalars().all())
        keys = [
            artifact.storage_key
            for artifact in artifacts
            if artifact.storage_key and artifact.storage_key.startswith("email-integrations/")
        ]
        for artifact in artifacts:
            artifact.storage_key = None

        scrubbed = await session.execute(
            update(EmailMessageModel)
            .where(
                EmailMessageModel.received_at < content_cutoff,
                EmailMessageModel.body_excerpt.is_not(None),
                EmailMessageModel.body_excerpt != "",
            )
            .values(body_excerpt="", updated_at=now)
        )
        await session.execute(
            delete(EmailOAuthStateModel).where(
                EmailOAuthStateModel.created_at < oauth_cutoff,
                or_(
                    EmailOAuthStateModel.consumed_at.is_not(None),
                    EmailOAuthStateModel.expires_at < now,
                ),
            )
        )
        await session.commit()
        scrubbed_count = int(getattr(scrubbed, "rowcount", 0) or 0)

    # Clear durable references before deleting. If object deletion fails, the
    # reconciler below (and the next daily run) can safely retry without
    # leaving database rows pointing at missing files.
    storage = MinioStorageRepository()
    if keys:
        try:
            await storage.delete_files(keys)
        except Exception as exc:
            logger.error(
                "email_retention_storage_delete_failed",
                extra={"error_type": type(exc).__name__},
            )
    orphaned_count = 0
    try:
        orphaned_count = await _reconcile_orphaned_email_storage(
            storage=storage,
            now=now,
        )
    except Exception as exc:
        logger.error(
            "email_storage_reconciliation_failed",
            extra={"error_type": type(exc).__name__},
        )
    return len(keys) + scrubbed_count + orphaned_count


async def _reconcile_orphaned_email_storage(
    *,
    storage: MinioStorageRepository,
    now: datetime,
) -> int:
    """Delete aged email-owned objects with no durable database reference."""

    settings = get_settings()
    cutoff = now - timedelta(hours=settings.email_storage_orphan_grace_hours)
    deleted_count = 0
    for prefix in _EMAIL_STORAGE_PREFIXES:
        start_after: str | None = None
        while True:
            objects = await storage.list_files(
                prefix=prefix,
                limit=_EMAIL_STORAGE_RECONCILE_PAGE_SIZE,
                start_after=start_after,
            )
            if not objects:
                break
            candidate_keys = list(
                dict.fromkeys(
                    key
                    for key, modified_at in objects
                    if _storage_object_is_older_than(modified_at, cutoff=cutoff)
                )
            )
            if candidate_keys:
                deleted_count += await _delete_unreferenced_email_storage_keys(
                    storage=storage,
                    candidate_keys=candidate_keys,
                )
            next_start_after = objects[-1][0]
            if len(objects) < _EMAIL_STORAGE_RECONCILE_PAGE_SIZE or next_start_after == start_after:
                break
            start_after = next_start_after
    return deleted_count


async def _delete_unreferenced_email_storage_keys(
    *,
    storage: MinioStorageRepository,
    candidate_keys: list[str],
) -> int:
    if not candidate_keys:
        return 0

    async with AsyncSessionFactory() as session:
        artifact_keys = set(
            (
                await session.execute(
                    select(EmailArtifactModel.storage_key).where(
                        EmailArtifactModel.storage_key.in_(candidate_keys)
                    )
                )
            )
            .scalars()
            .all()
        )
        document_keys = set(
            (
                await session.execute(
                    select(DistributedDocumentModel.storage_key).where(
                        DistributedDocumentModel.storage_key.in_(candidate_keys)
                    )
                )
            )
            .scalars()
            .all()
        )
    referenced_keys = artifact_keys | document_keys
    orphaned_keys = [key for key in candidate_keys if key not in referenced_keys]
    if not orphaned_keys:
        return 0
    return await storage.delete_files(orphaned_keys)


def _storage_object_is_older_than(
    modified_at: datetime | None,
    *,
    cutoff: datetime,
) -> bool:
    if modified_at is None:
        return False
    normalized = modified_at if modified_at.tzinfo is not None else modified_at.replace(tzinfo=UTC)
    return normalized <= cutoff
