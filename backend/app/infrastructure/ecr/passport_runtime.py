"""Opt-in passport ECR work on the existing bounded Documents ECR worker."""

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
from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.domain.exceptions.exceptions import StorageError
from app.infrastructure.ai.gemini_ecr_service import EcrClassification, GeminiEcrService
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    PassportSubmissionModel,
)
from app.infrastructure.database.passport_ecr_models import PassportEcrCheckModel
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.ecr import dispatch_passport_ecr_checks
from app.infrastructure.ecr.runtime import (
    HEARTBEAT_SECONDS,
    LEASE_SECONDS,
    ProviderPacer,
    RateLimitUnavailable,
    _lease_is_active,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository

logger = get_logger(__name__)
MAX_PASSPORT_DRAIN = 32
MAX_RECOVERY_PAGE = 100
MAX_JOB_ATTEMPTS = 3
_RETRYABLE = {
    "rate_limited",
    "timeout",
    "provider_unavailable",
    "network_error",
    "image_unavailable",
    "source_changed",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _provider_limit() -> int:
    return min(5, max(1, get_settings().ecr_gemini_max_attempts))


def _enabled(group: ClientGroupModel, agency: AgencyModel) -> bool:
    config = group.upload_configuration or {}
    return (
        agency.is_active
        and group.deleted_at is None
        and config.get("passport_enabled", True) is True
        and config.get("passport_ecr_enabled", False) is True
    )


def _source(submission: PassportSubmissionModel) -> str | None:
    # Deliberately no fallback to front, covers, photos or generated/cropped pages.
    key = submission.passport_back_s3_key
    return key if key and not key.startswith("drafts/") else None


async def _scope(session: AsyncSession, submission_id: uuid.UUID, *, lock: bool = False) -> Any:
    query = (
        select(PassportSubmissionModel, ClientGroupModel, AgencyModel)
        .join(ClientGroupModel, ClientGroupModel.id == PassportSubmissionModel.group_id)
        .join(AgencyModel, AgencyModel.id == PassportSubmissionModel.agency_id)
        .where(
            PassportSubmissionModel.id == submission_id,
            ClientGroupModel.agency_id == PassportSubmissionModel.agency_id,
        )
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update(of=PassportSubmissionModel).execution_options(
            populate_existing=True
        )
    return (await session.execute(query)).one_or_none()


def _reset(job: PassportEcrCheckModel, source_key: str) -> None:
    job.generation = uuid.uuid4()
    job.source_storage_key = source_key
    job.source_sha256 = None
    job.status, job.result, job.reason, job.model = "queued", None, None, None
    job.attempts = job.provider_attempts = job.input_tokens = job.output_tokens = 0
    job.lease_token = job.lease_expires_at = None
    job.next_attempt_at = job.updated_at = _now()


def _disable(job: PassportEcrCheckModel) -> None:
    job.status, job.result, job.reason = "disabled", None, "ecr_not_enabled_or_source_unavailable"
    job.lease_token = job.lease_expires_at = None
    job.updated_at = _now()


async def stage_passport_ecr_check(session: AsyncSession, submission_id: uuid.UUID) -> bool:
    """Stage with the submission transaction; never contact Gemini or publish here."""
    scope = await _scope(session, submission_id, lock=True)
    if scope is None:
        return False
    submission, group, agency = scope
    job = await session.scalar(
        select(PassportEcrCheckModel)
        .where(PassportEcrCheckModel.submission_id == submission_id)
        .with_for_update()
    )
    source_key = _source(submission)
    if not _enabled(group, agency) or not source_key or submission.client_reviewed_at is None:
        if job is not None:
            _disable(job)
        return False
    if job is None:
        job = PassportEcrCheckModel(submission_id=submission_id, source_storage_key=source_key)
        session.add(job)
        await session.flush()
    elif job.source_storage_key != source_key or job.status == "disabled":
        _reset(job, source_key)
        await session.flush()
    return job.status == "queued"


async def passport_ecr_results(
    session: AsyncSession,
    submission_ids: list[uuid.UUID],
    *,
    agency_id: uuid.UUID,
    expected_source_keys: dict[uuid.UUID, str | None] | None = None,
) -> dict[uuid.UUID, str]:
    """Return current export labels for authorized IDs, with fresh source/opt-in gates."""
    if not submission_ids:
        return {}
    rows = await session.execute(
        select(PassportSubmissionModel, ClientGroupModel, AgencyModel, PassportEcrCheckModel)
        .join(ClientGroupModel, ClientGroupModel.id == PassportSubmissionModel.group_id)
        .join(AgencyModel, AgencyModel.id == PassportSubmissionModel.agency_id)
        .outerjoin(
            PassportEcrCheckModel, PassportEcrCheckModel.submission_id == PassportSubmissionModel.id
        )
        .where(
            PassportSubmissionModel.id.in_(submission_ids),
            PassportSubmissionModel.agency_id == agency_id,
            ClientGroupModel.agency_id == agency_id,
        )
        .execution_options(populate_existing=True)
    )
    results = {}
    for submission, group, agency, job in rows:
        if not _enabled(group, agency):
            label = "NOT_ENABLED"
        elif not _source(submission):
            label = "NO_BACK"
        elif (
            (
                expected_source_keys is not None
                and expected_source_keys.get(submission.id) != _source(submission)
            )
            or submission.client_reviewed_at is None
            or job is None
            or job.source_storage_key != _source(submission)
        ):
            label = "PENDING"
        elif job.status == "completed" and job.result in {"ECR", "NA", "NEEDS_REVIEW"}:
            label = "REVIEW" if job.result == "NEEDS_REVIEW" else job.result
        elif job.status == "failed":
            label = "ERROR"
        else:
            label = "PENDING"
        results[submission.id] = label
    return results


class PassportEcrStale(RuntimeError):
    """Opt-in, source identity or execution ownership changed."""


class PassportEcrBudgetExhausted(RuntimeError):
    """The durable provider budget has already been consumed for this source."""


@dataclass(frozen=True, slots=True)
class PassportClaim:
    submission_id: uuid.UUID
    generation: uuid.UUID
    token: uuid.UUID
    source_key: str


async def _claim(submission_id: uuid.UUID) -> PassportClaim | None:
    async with AsyncSessionFactory() as session:
        await stage_passport_ecr_check(session, submission_id)
        job = await session.get(PassportEcrCheckModel, submission_id)
        if job is None or job.status not in {"queued", "processing"}:
            await session.commit()
            return None
        if job.status == "processing" and _lease_is_active(job.lease_expires_at):
            return None
        due = job.next_attempt_at
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        if due > _now():
            return None
        if job.attempts >= MAX_JOB_ATTEMPTS or job.provider_attempts >= _provider_limit():
            job.status, job.result, job.reason = "failed", None, "attempt_limit_reached"
            job.lease_token = job.lease_expires_at = None
            job.updated_at = _now()
            await session.commit()
            return None
        job.status = "processing"
        job.lease_token = uuid.uuid4()
        job.lease_expires_at = _now() + timedelta(seconds=LEASE_SECONDS)
        job.attempts += 1
        job.updated_at = _now()
        claim = PassportClaim(
            submission_id, job.generation, job.lease_token, job.source_storage_key
        )
        await session.commit()
        return claim


async def _owned(session: AsyncSession, claim: PassportClaim) -> PassportEcrCheckModel:
    scope = await _scope(session, claim.submission_id, lock=True)
    job = await session.scalar(
        select(PassportEcrCheckModel)
        .where(PassportEcrCheckModel.submission_id == claim.submission_id)
        .with_for_update()
    )
    if (
        scope is None
        or job is None
        or job.generation != claim.generation
        or job.lease_token != claim.token
        or job.status != "processing"
        or not _lease_is_active(job.lease_expires_at)
    ):
        raise PassportEcrStale("Passport ECR ownership changed")
    submission, group, agency = scope
    source_key = _source(submission)
    if not _enabled(group, agency) or not source_key or submission.client_reviewed_at is None:
        _disable(job)
        await session.commit()
        raise PassportEcrStale("Passport ECR is no longer enabled")
    if source_key != claim.source_key:
        _reset(job, source_key)
        await session.commit()
        raise PassportEcrStale("Passport ECR back page changed")
    return job


async def _renew(claim: PassportClaim) -> None:
    async with AsyncSessionFactory() as session:
        job = await _owned(session, claim)
        job.lease_expires_at = _now() + timedelta(seconds=LEASE_SECONDS)
        job.updated_at = _now()
        await session.commit()


async def _admit_provider_attempt(claim: PassportClaim) -> None:
    async with AsyncSessionFactory() as session:
        job = await _owned(session, claim)
        if job.provider_attempts >= _provider_limit():
            raise PassportEcrBudgetExhausted("Passport ECR attempt limit reached")
        # Commit before HTTP: even a killed worker cannot reuse a consumed slot.
        job.provider_attempts += 1
        job.lease_expires_at = _now() + timedelta(seconds=LEASE_SECONDS)
        job.updated_at = _now()
        await session.commit()


async def _save(claim: PassportClaim, result: EcrClassification, digest: str | None) -> None:
    async with AsyncSessionFactory() as session:
        job = await _owned(session, claim)
        job.input_tokens += result.input_tokens
        job.output_tokens += result.output_tokens + result.thinking_tokens
        job.reason, job.model, job.source_sha256 = result.reason, result.model, digest
        job.result = (
            "NEEDS_REVIEW"
            if result.status == "REVIEW"
            else result.status
            if result.status in {"ECR", "NA"}
            else None
        )
        retry = (
            result.status == "ERROR"
            and result.reason in _RETRYABLE
            and job.attempts < MAX_JOB_ATTEMPTS
            and job.provider_attempts < _provider_limit()
        )
        job.status = "queued" if retry else "failed" if result.status == "ERROR" else "completed"
        job.next_attempt_at = _now() + timedelta(seconds=60 if retry else 0)
        job.lease_token = job.lease_expires_at = None
        job.updated_at = _now()
        await session.commit()


async def _release(claim: PassportClaim, *, refund_attempt: bool = False) -> None:
    async with AsyncSessionFactory() as session:
        job = await session.scalar(
            select(PassportEcrCheckModel)
            .where(PassportEcrCheckModel.submission_id == claim.submission_id)
            .with_for_update()
        )
        if (
            job
            and job.generation == claim.generation
            and job.lease_token == claim.token
            and job.status == "processing"
        ):
            if refund_attempt:
                # Infrastructure outages/cancellation did not produce an image
                # verdict. Provider admission remains charged independently.
                job.attempts = max(0, job.attempts - 1)
            exhausted = (
                job.attempts >= MAX_JOB_ATTEMPTS or job.provider_attempts >= _provider_limit()
            )
            job.status = "failed" if exhausted else "queued"
            if exhausted:
                job.reason, job.result = "attempt_limit_reached", None
            job.lease_token = job.lease_expires_at = None
            job.next_attempt_at = _now() + timedelta(seconds=30)
            job.updated_at = _now()
            await session.commit()


async def _release_settled(claim: PassportClaim) -> None:
    """Finish the short cleanup transaction even if sibling failures cancel us."""
    work = asyncio.create_task(_release(claim, refund_attempt=True))
    try:
        await asyncio.shield(work)
    except asyncio.CancelledError:
        while not work.done():
            try:
                await asyncio.shield(work)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        with suppress(Exception):
            work.result()
        raise


async def _process_one(
    claim: PassportClaim,
    *,
    storage: MinioStorageRepository,
    client: httpx.AsyncClient,
    pacer: ProviderPacer,
) -> None:
    async def before_attempt() -> None:
        await pacer.acquire()
        # Recheck after quota waiting, before every actual provider call/retry.
        await _admit_provider_attempt(claim)

    async def execute() -> None:
        await _renew(claim)
        metadata = await storage.stat_file(claim.source_key)
        if not 0 < metadata.size_bytes <= get_settings().ecr_image_max_bytes:
            await _save(claim, EcrClassification("ERROR", "image_too_large", ""), None)
            return
        content = await storage.get_file_range(
            claim.source_key, start=0, end=metadata.size_bytes - 1
        )
        digest = hashlib.sha256(content).hexdigest()
        if metadata.checksum_sha256 and metadata.checksum_sha256 != digest:
            await _save(claim, EcrClassification("ERROR", "image_integrity_failed", ""), None)
            return
        classifier = GeminiEcrService(http_client=client, before_attempt=before_attempt)
        result = await classifier.classify(content, "image/jpeg")
        # Detect an overwrite of the same object key while Gemini was reading.
        latest = await storage.stat_file(claim.source_key)
        if latest.size_bytes != metadata.size_bytes or (
            latest.checksum_sha256 and latest.checksum_sha256 != digest
        ):
            result = EcrClassification(
                "ERROR",
                "source_changed",
                result.model,
                result.input_tokens,
                result.output_tokens,
                result.thinking_tokens,
                result.attempts,
            )
        await _save(claim, result, digest)

    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            await _renew(claim)

    try:
        async with asyncio.TaskGroup() as tasks:
            lease = tasks.create_task(heartbeat())
            work = tasks.create_task(execute())
            try:
                await work
            finally:
                lease.cancel()
    except* PassportEcrStale:
        pass
    except* PassportEcrBudgetExhausted:
        with suppress(PassportEcrStale):
            await _save(claim, EcrClassification("ERROR", "attempt_limit_reached", ""), None)
    except* StorageError:
        with suppress(PassportEcrStale):
            await _save(claim, EcrClassification("ERROR", "image_unavailable", ""), None)
    except* (RateLimitUnavailable, SQLAlchemyError):
        # Stop the drain safely on infrastructure failure. The finally block
        # refunds the job attempt; admission already committed cannot be reused.
        raise
    except* Exception:
        # A poison image must not cancel healthy neighboring image lanes.
        with suppress(PassportEcrStale):
            await _save(claim, EcrClassification("ERROR", "processing_failed", ""), None)
    finally:
        # On an unexpected failure only the still-owning execution can release.
        with suppress(Exception):
            await _release_settled(claim)


async def process_passport_checks() -> int:
    """Drain a bounded page; the same single ECR worker also serves document batches."""
    now = _now()
    async with AsyncSessionFactory() as session:
        ids = list(
            (
                await session.scalars(
                    select(PassportEcrCheckModel.submission_id)
                    .where(
                        PassportEcrCheckModel.next_attempt_at <= now,
                        or_(
                            PassportEcrCheckModel.status == "queued",
                            (PassportEcrCheckModel.status == "processing")
                            & or_(
                                PassportEcrCheckModel.lease_expires_at <= now,
                                PassportEcrCheckModel.lease_expires_at.is_(None),
                            ),
                        ),
                    )
                    .order_by(
                        PassportEcrCheckModel.next_attempt_at, PassportEcrCheckModel.created_at
                    )
                    .limit(MAX_PASSPORT_DRAIN)
                )
            ).all()
        )
    if not ids:
        return 0
    settings = get_settings()
    redis = Redis.from_url(
        settings.redis.broker_url, socket_connect_timeout=3, socket_timeout=3, decode_responses=True
    )
    pending = iter(ids)
    storage = MinioStorageRepository()
    pacer = ProviderPacer(redis, settings.ecr_requests_per_minute)
    try:
        async with httpx.AsyncClient() as client:

            async def lane() -> None:
                for submission_id in pending:
                    # A sibling's infrastructure failure may cancel this lane
                    # just as its claim commits. Finish that short transaction
                    # before releasing, so no admitted claim is orphaned.
                    claim_task = asyncio.create_task(_claim(submission_id))
                    try:
                        claim = await asyncio.shield(claim_task)
                    except asyncio.CancelledError:
                        while not claim_task.done():
                            try:
                                await asyncio.shield(claim_task)
                            except asyncio.CancelledError:
                                continue
                            except Exception:
                                break
                        with suppress(Exception):
                            interrupted = claim_task.result()
                            if interrupted is not None:
                                await _release_settled(interrupted)
                        raise
                    if claim is not None:
                        await _process_one(claim, storage=storage, client=client, pacer=pacer)

            async with asyncio.TaskGroup() as tasks:
                for _ in range(min(settings.ecr_max_concurrency, len(ids))):
                    tasks.create_task(lane())
        return len(ids)
    finally:
        await redis.aclose()


async def recover_passport_checks() -> int:
    """Backfill newly enabled/finalized/changed sources and wake stale queued jobs."""
    async with AsyncSessionFactory() as session:
        source = PassportSubmissionModel.passport_back_s3_key
        ids = list(
            (
                await session.scalars(
                    select(PassportSubmissionModel.id)
                    .join(ClientGroupModel, ClientGroupModel.id == PassportSubmissionModel.group_id)
                    .join(AgencyModel, AgencyModel.id == PassportSubmissionModel.agency_id)
                    .outerjoin(
                        PassportEcrCheckModel,
                        PassportEcrCheckModel.submission_id == PassportSubmissionModel.id,
                    )
                    .where(
                        AgencyModel.is_active.is_(True),
                        ClientGroupModel.deleted_at.is_(None),
                        ClientGroupModel.agency_id == PassportSubmissionModel.agency_id,
                        ClientGroupModel.upload_configuration["passport_enabled"]
                        .as_boolean()
                        .is_not(False),
                        ClientGroupModel.upload_configuration["passport_ecr_enabled"]
                        .as_boolean()
                        .is_(True),
                        PassportSubmissionModel.client_reviewed_at.is_not(None),
                        source.is_not(None),
                        source != "",
                        source.not_like("drafts/%"),
                        or_(
                            PassportEcrCheckModel.submission_id.is_(None),
                            PassportEcrCheckModel.source_storage_key != source,
                            PassportEcrCheckModel.status == "disabled",
                        ),
                    )
                    .order_by(PassportSubmissionModel.created_at, PassportSubmissionModel.id)
                    .limit(MAX_RECOVERY_PAGE)
                )
            ).all()
        )
    for submission_id in ids:
        async with AsyncSessionFactory() as session:
            await stage_passport_ecr_check(session, submission_id)
            await session.commit()
    async with AsyncSessionFactory() as session:
        queued = await session.scalar(
            select(PassportEcrCheckModel.submission_id)
            .where(
                PassportEcrCheckModel.next_attempt_at <= _now(),
                or_(
                    PassportEcrCheckModel.status == "queued",
                    (PassportEcrCheckModel.status == "processing")
                    & or_(
                        PassportEcrCheckModel.lease_expires_at <= _now(),
                        PassportEcrCheckModel.lease_expires_at.is_(None),
                    ),
                ),
            )
            .limit(1)
        )
    if queued is not None:
        await dispatch_passport_ecr_checks()
    return len(ids)
