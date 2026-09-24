"""Bounded ECR lanes with durable leases and ECR-only request pacing."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from redis.asyncio import Redis
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.domain.exceptions.exceptions import StorageError
from app.infrastructure.ai.gemini_ecr_service import EcrClassification, GeminiEcrService
from app.infrastructure.database.ecr_models import EcrBatchModel, EcrItemModel
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.ecr import dispatch_ecr_batch
from app.infrastructure.storage.minio_repository import MinioStorageRepository

logger = get_logger(__name__)
LEASE_SECONDS = 120
HEARTBEAT_SECONDS = 30
ITEMS_PER_DRAIN = 32
RATE_LIMIT_KEY = "ecr:provider-request-spacing:v1"

# Redis TIME avoids worker clock skew. No future reservations are made: a
# cancelled lane cannot leave a long backlog of unused permits behind it.
RATE_LIMIT_SCRIPT = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
local next_allowed = tonumber(redis.call('GET', KEYS[1]) or '0')
if next_allowed > now then return next_allowed - now end
local interval = tonumber(ARGV[1])
redis.call('SET', KEYS[1], now + interval, 'PX', math.max(1000, interval * 2))
return 0
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _lease_is_active(expires_at: datetime | None) -> bool:
    if expires_at is None:
        return False
    # SQLite test databases omit offsets; PostgreSQL timestamps retain them.
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at > _now()


class LeaseLost(RuntimeError):
    """Another worker has acquired this batch; this execution must stop."""


class RateLimitUnavailable(RuntimeError):
    """Pause ECR work when its shared request pacing cannot be coordinated."""


@dataclass(frozen=True, slots=True)
class WorkItem:
    id: uuid.UUID
    object_key: str | None
    content_type: str


class ProviderPacer:
    def __init__(self, client: Any, requests_per_minute: int) -> None:
        self.client = client
        self.interval_ms = max(1, (60_000 + requests_per_minute - 1) // requests_per_minute)

    async def acquire(self) -> None:
        while True:
            try:
                delay_ms = int(
                    await self.client.eval(RATE_LIMIT_SCRIPT, 1, RATE_LIMIT_KEY, self.interval_ms)
                )
            except Exception as exc:
                raise RateLimitUnavailable(
                    "ECR request pacing is temporarily unavailable."
                ) from exc
            if delay_ms <= 0:
                return
            await asyncio.sleep(min(delay_ms / 1000.0, 60.0))


class BatchStore:
    """All item mutations fence on a locked batch ownership token.

    Sessions live only for short database transactions. In particular no DB
    connection is held while downloading an image or awaiting Gemini.
    """

    async def claim(self, batch_id: uuid.UUID) -> uuid.UUID | None:
        async with AsyncSessionFactory() as session:
            batch = await session.scalar(
                select(EcrBatchModel).where(EcrBatchModel.id == batch_id).with_for_update()
            )
            now = _now()
            if batch is None or batch.status not in {"queued", "processing"}:
                return None
            if batch.status == "processing" and _lease_is_active(batch.lease_expires_at):
                return None
            token = uuid.uuid4()
            batch.status = "processing"
            batch.lease_token = token
            batch.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
            batch.updated_at = now
            # Only work interrupted before its durable result is reset. Already
            # completed rows are never sent again during crash recovery.
            await session.execute(
                update(EcrItemModel)
                .where(EcrItemModel.batch_id == batch_id, EcrItemModel.status == "processing")
                .values(status="queued", updated_at=now)
            )
            await session.commit()
            return token

    async def _owned(
        self, session: AsyncSession, batch_id: uuid.UUID, token: uuid.UUID
    ) -> EcrBatchModel:
        batch = await session.scalar(
            select(EcrBatchModel).where(EcrBatchModel.id == batch_id).with_for_update()
        )
        if (
            batch is None
            or batch.status != "processing"
            or batch.lease_token != token
            or not _lease_is_active(batch.lease_expires_at)
        ):
            raise LeaseLost("ECR processing lease changed or expired.")
        return batch

    async def renew(self, batch_id: uuid.UUID, token: uuid.UUID) -> None:
        async with AsyncSessionFactory() as session:
            batch = await self._owned(session, batch_id, token)
            batch.lease_expires_at = _now() + timedelta(seconds=LEASE_SECONDS)
            batch.updated_at = _now()
            await session.commit()

    async def next_item(self, batch_id: uuid.UUID, token: uuid.UUID) -> WorkItem | None:
        async with AsyncSessionFactory() as session:
            await self._owned(session, batch_id, token)
            item = await session.scalar(
                select(EcrItemModel)
                .where(EcrItemModel.batch_id == batch_id, EcrItemModel.status == "queued")
                .order_by(EcrItemModel.created_at, EcrItemModel.id)
                .limit(1)
                .with_for_update()
            )
            if item is None:
                return None
            item.status = "processing"
            item.attempts += 1
            item.updated_at = _now()
            work = WorkItem(item.id, item.object_key, item.content_type)
            await session.commit()
            return work

    async def save_result(
        self, batch_id: uuid.UUID, token: uuid.UUID, item_id: uuid.UUID, result: EcrClassification
    ) -> None:
        async with AsyncSessionFactory() as session:
            await self._owned(session, batch_id, token)
            await session.execute(
                update(EcrItemModel)
                .where(
                    EcrItemModel.id == item_id,
                    EcrItemModel.batch_id == batch_id,
                    EcrItemModel.status == "processing",
                )
                .values(
                    status="failed" if result.status == "ERROR" else "completed",
                    result=(
                        "NEEDS_REVIEW"
                        if result.status == "REVIEW"
                        else None
                        if result.status == "ERROR"
                        else result.status
                    ),
                    reason=result.reason,
                    model=result.model,
                    input_tokens=EcrItemModel.input_tokens + result.input_tokens,
                    output_tokens=EcrItemModel.output_tokens
                    + result.output_tokens
                    + result.thinking_tokens,
                    attempts=EcrItemModel.attempts + max(0, result.attempts - 1),
                    updated_at=_now(),
                )
            )
            await session.commit()

    async def fail_item(
        self, batch_id: uuid.UUID, token: uuid.UUID, item_id: uuid.UUID, reason: str
    ) -> None:
        async with AsyncSessionFactory() as session:
            await self._owned(session, batch_id, token)
            await session.execute(
                update(EcrItemModel)
                .where(EcrItemModel.id == item_id, EcrItemModel.batch_id == batch_id)
                .values(status="failed", result=None, reason=reason, updated_at=_now())
            )
            await session.commit()

    async def finish(self, batch_id: uuid.UUID, token: uuid.UUID) -> bool:
        """Release a finished drain; return true only when the whole batch is done."""
        async with AsyncSessionFactory() as session:
            batch = await self._owned(session, batch_id, token)
            rows = await session.execute(
                select(EcrItemModel.status, func.count())
                .where(EcrItemModel.batch_id == batch_id)
                .group_by(EcrItemModel.status)
            )
            counts = {status: count for status, count in rows.all()}
            if counts.get("processing"):
                raise RuntimeError("ECR drain still has active rows.")
            completed = not counts.get("queued")
            batch.status = (
                "queued"
                if not completed
                else "completed_with_errors"
                if counts.get("failed")
                else "completed"
            )
            batch.lease_token = None
            batch.lease_expires_at = None
            batch.updated_at = _now()
            await session.commit()
            return completed

    async def release(self, batch_id: uuid.UUID, token: uuid.UUID) -> None:
        async with AsyncSessionFactory() as session:
            # An expired lease is safe to release only while its token still
            # matches. A takeover changes it in the same locked transaction.
            batch = await session.scalar(
                select(EcrBatchModel).where(EcrBatchModel.id == batch_id).with_for_update()
            )
            if batch is None or batch.status != "processing" or batch.lease_token != token:
                return
            batch.status = "queued"
            batch.lease_token = None
            batch.lease_expires_at = None
            batch.updated_at = _now()
            await session.execute(
                update(EcrItemModel)
                .where(EcrItemModel.batch_id == batch_id, EcrItemModel.status == "processing")
                .values(status="queued", updated_at=_now())
            )
            await session.commit()


async def _run_lanes(
    batch_id: uuid.UUID,
    token: uuid.UUID,
    *,
    store: BatchStore,
    storage: MinioStorageRepository,
    classifier: GeminiEcrService,
    concurrency: int,
    max_image_bytes: int,
    max_items: int = ITEMS_PER_DRAIN,
) -> None:
    # Each next() runs before the lane's first await, so these shared slots cap
    # claims across all lanes without holding a lock during storage/provider I/O.
    slots = iter(range(max_items))

    async def lane() -> None:
        for _ in slots:
            item = await store.next_item(batch_id, token)
            if item is None:
                return
            if not item.object_key:
                await store.fail_item(batch_id, token, item.id, "image_expired")
                continue
            try:
                # A bounded range avoids an unexpectedly enlarged stored object
                # exhausting a lane's memory before integrity validation.
                metadata = await storage.stat_file(item.object_key)
                if metadata.size_bytes < 1 or metadata.size_bytes > max_image_bytes:
                    await store.fail_item(batch_id, token, item.id, "image_too_large")
                    continue
                content = await storage.get_file_range(
                    item.object_key, start=0, end=metadata.size_bytes - 1
                )
                if (
                    metadata.checksum_sha256
                    and hashlib.sha256(content).hexdigest() != metadata.checksum_sha256
                ):
                    await store.fail_item(batch_id, token, item.id, "image_integrity_failed")
                    continue
                result = await classifier.classify(content, item.content_type)
            except (LeaseLost, RateLimitUnavailable):
                raise
            except StorageError:
                await store.fail_item(batch_id, token, item.id, "image_unavailable")
                continue
            except Exception as exc:
                logger.warning("ecr_item_failed", error_type=type(exc).__name__)
                await store.fail_item(batch_id, token, item.id, "processing_error")
                continue
            await store.save_result(batch_id, token, item.id, result)

    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            await store.renew(batch_id, token)

    # TaskGroup cancels every sibling on lease loss or infrastructure failure.
    # A heartbeat failure must not leave provider lanes running without ownership.
    async with asyncio.TaskGroup() as group:
        lease_task = group.create_task(heartbeat())
        lanes = [group.create_task(lane()) for _ in range(concurrency)]
        try:
            await asyncio.gather(*lanes)
        finally:
            lease_task.cancel()


async def process_batch(batch_id: uuid.UUID) -> str:
    settings = get_settings()
    store = BatchStore()
    token = await store.claim(batch_id)
    if token is None:
        return "not_claimed"
    redis = Redis.from_url(
        settings.redis.broker_url,
        socket_connect_timeout=3,
        socket_timeout=3,
        decode_responses=True,
    )
    try:
        pacer = ProviderPacer(redis, settings.ecr_requests_per_minute)

        async def before_attempt() -> None:
            await pacer.acquire()
            # Admission can wait; ownership must still hold when HTTP starts,
            # including every retry made by the classifier.
            await store.renew(batch_id, token)

        async with httpx.AsyncClient() as client:
            classifier = GeminiEcrService(
                settings=settings, http_client=client, before_attempt=before_attempt
            )
            await _run_lanes(
                batch_id,
                token,
                store=store,
                storage=MinioStorageRepository(),
                classifier=classifier,
                concurrency=settings.ecr_max_concurrency,
                max_image_bytes=settings.ecr_image_max_bytes,
            )
        if await store.finish(batch_id, token):
            return "completed"
        # Commit the queued state before publishing a fresh FIFO task. This
        # yields the single ECR worker to passport checks/other waiting batches.
        # Beat recovery also finds this state if publication or the process fails.
        await dispatch_ecr_batch(batch_id)
        return "continued"
    except BaseException:
        # Abrupt process death is recovered by the expiring DB lease. Ordinary
        # failures release promptly so broker/beat retries can resume sooner.
        with suppress(Exception):
            await store.release(batch_id, token)
        raise
    finally:
        await redis.aclose()


async def recover_batches() -> int:
    now = _now()
    async with AsyncSessionFactory() as session:
        ids = list(
            (
                await session.scalars(
                    select(EcrBatchModel.id)
                    .where(
                        or_(
                            (EcrBatchModel.status == "queued")
                            & (EcrBatchModel.updated_at < now - timedelta(seconds=30)),
                            (EcrBatchModel.status == "processing")
                            & (
                                EcrBatchModel.lease_expires_at.is_(None)
                                | (EcrBatchModel.lease_expires_at <= now)
                            ),
                        )
                    )
                    .order_by(EcrBatchModel.created_at)
                    .limit(100)
                )
            ).all()
        )
    dispatched = 0
    for batch_id in ids:
        await dispatch_ecr_batch(batch_id)
        dispatched += 1
    return dispatched


async def apply_retention() -> int:
    """Delete only expired ECR-owned source images; preserve result rows."""
    cutoff = _now() - timedelta(days=get_settings().ecr_retention_days)
    storage = MinioStorageRepository()
    removed = 0
    # One batch is locked per page to serialize cleanup against user retries.
    # S3 deletion is idempotent if process death precedes the metadata commit.
    async with AsyncSessionFactory() as session:
        batch_ids = list(
            (
                await session.scalars(
                    select(EcrBatchModel.id)
                    .where(
                        EcrBatchModel.status.in_(
                            ["uploading", "completed", "completed_with_errors"]
                        ),
                        EcrBatchModel.created_at < cutoff,
                        select(EcrItemModel.id)
                        .where(
                            EcrItemModel.batch_id == EcrBatchModel.id,
                            EcrItemModel.object_key.is_not(None),
                            EcrItemModel.created_at < cutoff,
                        )
                        .exists(),
                    )
                    .order_by(EcrBatchModel.created_at)
                    .limit(25)
                )
            ).all()
        )
    for batch_id in batch_ids:
        async with AsyncSessionFactory() as session:
            batch = await session.scalar(
                select(EcrBatchModel)
                .where(EcrBatchModel.id == batch_id)
                .with_for_update(skip_locked=True)
            )
            if batch is None or batch.status not in {
                "uploading",
                "completed",
                "completed_with_errors",
            }:
                continue
            items = list(
                (
                    await session.scalars(
                        select(EcrItemModel)
                        .where(
                            EcrItemModel.batch_id == batch_id,
                            EcrItemModel.object_key.is_not(None),
                            EcrItemModel.created_at < cutoff,
                        )
                        .limit(1000)
                    )
                ).all()
            )
            prefix = f"ecr-checks/{batch.agency_id}/{batch.id}/"
            owned = [
                item for item in items if item.object_key and item.object_key.startswith(prefix)
            ]
            if len(owned) != len(items):
                logger.error("ecr_retention_invalid_namespace", batch_id=str(batch_id))
            if not owned:
                continue
            await storage.delete_files([str(item.object_key) for item in owned])
            for item in owned:
                item.object_key = None
                item.updated_at = _now()
            await session.commit()
            removed += len(owned)
    return removed + await _remove_orphan_images(storage, cutoff)


async def _remove_orphan_images(storage: MinioStorageRepository, cutoff: datetime) -> int:
    """Sweep abandoned uploads without ever entering another storage namespace.

    A Redis cursor makes the hourly bounded scan advance even while the ECR
    namespace contains many live source images. Upload keys are UUID-derived;
    new uploads cannot reuse seven-day-old keys while reconciliation runs.
    """
    redis = Redis.from_url(
        get_settings().redis.broker_url,
        socket_connect_timeout=3,
        socket_timeout=3,
        decode_responses=True,
    )
    cursor_key = "ecr:retention-scan-cursor:v1"
    removed = 0
    try:
        cursor = await redis.get(cursor_key)
        for _ in range(10):
            objects = await storage.list_files(prefix="ecr-checks/", limit=500, start_after=cursor)
            candidates = [
                key
                for key, modified in objects
                if key.startswith("ecr-checks/")
                and modified is not None
                and (modified.replace(tzinfo=timezone.utc) if modified.tzinfo is None else modified)
                < cutoff
            ]
            if candidates:
                async with AsyncSessionFactory() as session:
                    referenced = set(
                        (
                            await session.scalars(
                                select(EcrItemModel.object_key).where(
                                    EcrItemModel.object_key.in_(candidates)
                                )
                            )
                        ).all()
                    )
                orphans = [key for key in candidates if key not in referenced]
                removed += await storage.delete_files(orphans)
            if len(objects) < 500:
                await redis.delete(cursor_key)
                break
            cursor = objects[-1][0]
            await redis.set(cursor_key, cursor, ex=86_400)
    finally:
        await redis.aclose()
    return removed
