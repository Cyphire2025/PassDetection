"""Broker-loss recovery and eventual provider-reference deletion watchdog."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import and_, func, or_, select

from app.application.my_photos.errors import MyPhotosUnavailable
from app.application.my_photos.providers import ReferenceDeletionRequest
from app.core.config.settings import Settings, get_settings
from app.infrastructure.database.my_photos_models import (
    MyPhotoEnrollmentModel,
    MyPhotoJobModel,
    MyPhotoSearchRunModel,
)
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.my_photos.audit import record_my_photos_audit
from app.infrastructure.my_photos.providers import (
    MyPhotosProviderBundle,
    build_provider_bundle,
)
from app.infrastructure.my_photos.telemetry import my_photos_metrics

DispatchKind = Literal["search", "index", "media"]
DeletionKind = Literal["current", "superseded"]


@dataclass(frozen=True, slots=True)
class DurableDispatch:
    job_id: uuid.UUID
    kind: DispatchKind
    search_run_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class ProviderDeletionBatchResult:
    claimed: int
    completed: int
    retrying: int
    terminal_failed: int


@dataclass(frozen=True, slots=True)
class _DeletionClaim:
    enrollment_id: uuid.UUID
    kind: DeletionKind
    agency_id: uuid.UUID
    group_id: uuid.UUID
    passenger_identity_id: uuid.UUID
    provider_reference: str
    deletion_identity: str
    attempt_count: int


@dataclass(frozen=True, slots=True)
class _DeletionOutcome:
    claim: _DeletionClaim
    complete: bool
    error_code: str | None


async def recoverable_dispatches(
    *,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> tuple[DurableDispatch, ...]:
    """Return a bounded set of due/expired durable jobs; leases make duplicates safe."""

    resolved = settings or get_settings()
    due_at = now or datetime.now(tz=UTC)
    await _terminalize_requested_cancellations(resolved, due_at)
    async with AsyncSessionFactory() as session:
        depth_rows = list(
            (
                await session.execute(
                    select(MyPhotoJobModel.job_type, func.count(MyPhotoJobModel.id))
                    .where(MyPhotoJobModel.status.in_(("queued", "running", "retrying")))
                    .group_by(MyPhotoJobModel.job_type)
                )
            ).tuples()
        )
        jobs = list(
            (
                await session.execute(
                    select(MyPhotoJobModel)
                    .where(
                        or_(
                            and_(
                                MyPhotoJobModel.status.in_(("queued", "retrying")),
                                or_(
                                    MyPhotoJobModel.next_attempt_at.is_(None),
                                    MyPhotoJobModel.next_attempt_at <= due_at,
                                ),
                            ),
                            and_(
                                MyPhotoJobModel.status == "running",
                                MyPhotoJobModel.lease_expires_at.is_not(None),
                                MyPhotoJobModel.lease_expires_at <= due_at,
                            ),
                        ),
                    )
                    .order_by(MyPhotoJobModel.created_at, MyPhotoJobModel.id)
                    .limit(resolved.my_photos.recovery_batch_size)
                )
            ).scalars()
        )
    depths = {str(job_type): int(count) for job_type, count in depth_rows}
    my_photos_metrics.queue_depth("search", depths.get("search_passenger", 0))
    my_photos_metrics.queue_depth(
        "index", depths.get("index_gallery", 0) + depths.get("refresh_searches", 0)
    )
    my_photos_metrics.queue_depth(
        "media", depths.get("generate_variants", 0) + depths.get("prepare_media", 0)
    )
    dispatches: list[DurableDispatch] = []
    for job in jobs:
        if job.job_type == "search_passenger" and job.search_run_id is not None:
            dispatches.append(DurableDispatch(job.id, "search", job.search_run_id))
        elif job.job_type in {"index_gallery", "refresh_searches"}:
            dispatches.append(DurableDispatch(job.id, "index"))
        elif job.job_type in {"generate_variants", "prepare_media"}:
            dispatches.append(DurableDispatch(job.id, "media"))
    return tuple(dispatches)


async def _terminalize_requested_cancellations(settings: Settings, now: datetime) -> int:
    """Finalize a bounded cancellation batch, including expired worker leases."""

    async with AsyncSessionFactory() as session:
        jobs = list(
            (
                await session.execute(
                    select(MyPhotoJobModel)
                    .where(
                        MyPhotoJobModel.status.in_(("queued", "running", "retrying")),
                        MyPhotoJobModel.cancellation_requested_at.is_not(None),
                    )
                    .order_by(
                        MyPhotoJobModel.cancellation_requested_at,
                        MyPhotoJobModel.id,
                    )
                    .with_for_update(skip_locked=True)
                    .limit(settings.my_photos.recovery_batch_size)
                )
            ).scalars()
        )
        if not jobs:
            return 0
        search_ids = tuple(job.search_run_id for job in jobs if job.search_run_id is not None)
        searches = (
            {
                row.id: row
                for row in (
                    (
                        await session.execute(
                            select(MyPhotoSearchRunModel)
                            .where(MyPhotoSearchRunModel.id.in_(search_ids))
                            .with_for_update()
                        )
                    )
                    .scalars()
                    .all()
                )
            }
            if search_ids
            else {}
        )
        for job in jobs:
            job.status = "cancelled"
            job.completed_at = now
            job.heartbeat_at = now
            job.lease_owner = None
            job.lease_expires_at = None
            job.next_attempt_at = None
            job.stable_error_code = "CANCELLED_BY_REQUEST"
            if job.search_run_id is not None:
                search = searches.get(job.search_run_id)
                if search is not None and search.status not in {"complete", "failed", "cancelled"}:
                    search.status = "cancelled"
                    search.completed_at = now
                    search.heartbeat_at = now
                    search.lease_owner = None
                    search.lease_expires_at = None
                    search.stable_error_code = "CANCELLED_BY_REQUEST"
            await record_my_photos_audit(
                session,
                action="my_photos_job_cancelled",
                agency_id=job.agency_id,
                group_id=job.group_id,
                outcome=job.job_type,
            )
            my_photos_metrics.job("cancelled")
        await session.commit()
        return len(jobs)


async def execute_provider_deletion_batch(
    *,
    settings: Settings | None = None,
    providers: MyPhotosProviderBundle | None = None,
) -> ProviderDeletionBatchResult:
    """Claim, call, and finalize a bounded deletion batch without holding provider locks."""

    resolved = settings or get_settings()
    bundle = providers or build_provider_bundle(resolved)
    claims = await _claim_provider_deletions(resolved)
    if not claims:
        return ProviderDeletionBatchResult(0, 0, 0, 0)
    semaphore = asyncio.Semaphore(resolved.my_photos.provider_deletion_concurrency)

    async def delete_one(claim: _DeletionClaim) -> _DeletionOutcome:
        try:
            async with semaphore:
                async with asyncio.timeout(resolved.my_photos.liveness_provider_timeout_seconds):
                    result = await bundle.liveness.delete_reference(
                        ReferenceDeletionRequest(
                            tenant_scope=str(claim.agency_id),
                            group_scope=str(claim.group_id),
                            passenger_scope=str(claim.passenger_identity_id),
                            provider_reference=claim.provider_reference,
                            deletion_identity=claim.deletion_identity,
                        )
                    )
            if result.outcome not in {"deleted", "not_found"}:
                return _DeletionOutcome(claim, False, "PROVIDER_DELETION_RESULT_INVALID")
            return _DeletionOutcome(claim, True, None)
        except MyPhotosUnavailable as exc:
            return _DeletionOutcome(claim, False, _stable_error(exc.code))
        except TimeoutError:
            return _DeletionOutcome(claim, False, "PROVIDER_DELETION_TIMEOUT")
        except Exception:
            return _DeletionOutcome(claim, False, "PROVIDER_DELETION_UNAVAILABLE")

    outcomes = await asyncio.gather(*(delete_one(claim) for claim in claims))
    return await _finalize_provider_deletions(outcomes, resolved)


async def _claim_provider_deletions(settings: Settings) -> tuple[_DeletionClaim, ...]:
    now = datetime.now(tz=UTC)
    async with AsyncSessionFactory() as session:
        enrollments = list(
            (
                await session.execute(
                    select(MyPhotoEnrollmentModel)
                    .where(
                        or_(
                            and_(
                                MyPhotoEnrollmentModel.status == "deleted",
                                MyPhotoEnrollmentModel.provider_deletion_attempt_count
                                < settings.my_photos.provider_deletion_max_attempts,
                                or_(
                                    MyPhotoEnrollmentModel.provider_deletion_next_attempt_at.is_(
                                        None
                                    ),
                                    MyPhotoEnrollmentModel.provider_deletion_next_attempt_at <= now,
                                ),
                                MyPhotoEnrollmentModel.provider_deletion_status.in_(
                                    ("pending", "failed")
                                ),
                                MyPhotoEnrollmentModel.provider_reference_handle.is_not(None),
                                MyPhotoEnrollmentModel.deletion_idempotency_key.is_not(None),
                            ),
                            and_(
                                MyPhotoEnrollmentModel.superseded_deletion_attempt_count
                                < settings.my_photos.provider_deletion_max_attempts,
                                or_(
                                    MyPhotoEnrollmentModel.superseded_deletion_next_attempt_at.is_(
                                        None
                                    ),
                                    MyPhotoEnrollmentModel.superseded_deletion_next_attempt_at
                                    <= now,
                                ),
                                MyPhotoEnrollmentModel.superseded_reference_deletion_status.in_(
                                    ("pending", "failed")
                                ),
                                MyPhotoEnrollmentModel.superseded_provider_reference_handle.is_not(
                                    None
                                ),
                            ),
                        ),
                    )
                    .order_by(
                        MyPhotoEnrollmentModel.updated_at,
                        MyPhotoEnrollmentModel.id,
                    )
                    .with_for_update(skip_locked=True)
                    .limit(settings.my_photos.provider_deletion_batch_size)
                )
            ).scalars()
        )
        claims: list[_DeletionClaim] = []
        for enrollment in enrollments:
            if (
                enrollment.superseded_reference_deletion_status in {"pending", "failed"}
                and enrollment.superseded_provider_reference_handle is not None
                and enrollment.superseded_deletion_attempt_count
                < settings.my_photos.provider_deletion_max_attempts
                and _due(enrollment.superseded_deletion_next_attempt_at, now)
            ):
                kind: DeletionKind = "superseded"
                provider_reference = enrollment.superseded_provider_reference_handle
                deletion_identity = (
                    f"supersede:{enrollment.id}:{max(enrollment.reference_version - 1, 0)}"
                )
                enrollment.superseded_reference_deletion_status = "pending"
                enrollment.superseded_deletion_attempt_count += 1
                enrollment.superseded_deletion_last_attempt_at = now
                enrollment.superseded_deletion_next_attempt_at = now + timedelta(
                    seconds=settings.my_photos.provider_deletion_claim_seconds
                )
                attempt_count = enrollment.superseded_deletion_attempt_count
            elif (
                enrollment.status == "deleted"
                and enrollment.provider_deletion_status in {"pending", "failed"}
                and enrollment.provider_reference_handle is not None
                and enrollment.deletion_idempotency_key is not None
                and enrollment.provider_deletion_attempt_count
                < settings.my_photos.provider_deletion_max_attempts
                and _due(enrollment.provider_deletion_next_attempt_at, now)
            ):
                kind = "current"
                provider_reference = enrollment.provider_reference_handle
                deletion_identity = enrollment.deletion_idempotency_key
                enrollment.provider_deletion_status = "pending"
                enrollment.provider_deletion_attempt_count += 1
                enrollment.provider_deletion_last_attempt_at = now
                enrollment.provider_deletion_next_attempt_at = now + timedelta(
                    seconds=settings.my_photos.provider_deletion_claim_seconds
                )
                attempt_count = enrollment.provider_deletion_attempt_count
            else:
                continue
            claims.append(
                _DeletionClaim(
                    enrollment_id=enrollment.id,
                    kind=kind,
                    agency_id=enrollment.agency_id,
                    group_id=enrollment.group_id,
                    passenger_identity_id=enrollment.passenger_identity_id,
                    provider_reference=provider_reference,
                    deletion_identity=deletion_identity,
                    attempt_count=attempt_count,
                )
            )
        await session.commit()
        return tuple(claims)


async def _finalize_provider_deletions(
    outcomes: tuple[_DeletionOutcome, ...] | list[_DeletionOutcome],
    settings: Settings,
) -> ProviderDeletionBatchResult:
    completed = 0
    retrying = 0
    terminal_failed = 0
    if not outcomes:
        return ProviderDeletionBatchResult(0, 0, 0, 0)
    ids = tuple(outcome.claim.enrollment_id for outcome in outcomes)
    async with AsyncSessionFactory() as session:
        rows = {
            row.id: row
            for row in (
                (
                    await session.execute(
                        select(MyPhotoEnrollmentModel)
                        .where(MyPhotoEnrollmentModel.id.in_(ids))
                        .with_for_update()
                    )
                )
                .scalars()
                .all()
            )
        }
        now = datetime.now(tz=UTC)
        for outcome in outcomes:
            enrollment = rows.get(outcome.claim.enrollment_id)
            if enrollment is None or not _reference_unchanged(enrollment, outcome.claim):
                continue
            if outcome.complete:
                _complete_reference(enrollment, outcome.claim.kind, now)
                completed += 1
            elif outcome.claim.attempt_count >= settings.my_photos.provider_deletion_max_attempts:
                _fail_reference(enrollment, outcome.claim.kind, outcome.error_code)
                _set_next_attempt(enrollment, outcome.claim.kind, None)
                terminal_failed += 1
            else:
                _pending_reference(enrollment, outcome.claim.kind, outcome.error_code)
                _set_next_attempt(
                    enrollment,
                    outcome.claim.kind,
                    now + timedelta(seconds=_deletion_retry_delay(outcome.claim, settings)),
                )
                retrying += 1
            await record_my_photos_audit(
                session,
                action="my_photos_provider_deletion",
                agency_id=enrollment.agency_id,
                group_id=enrollment.group_id,
                outcome=(
                    f"{outcome.claim.kind}_complete"
                    if outcome.complete
                    else f"{outcome.claim.kind}_failed"
                    if outcome.claim.attempt_count
                    >= settings.my_photos.provider_deletion_max_attempts
                    else f"{outcome.claim.kind}_pending"
                ),
            )
        await session.commit()
    return ProviderDeletionBatchResult(len(outcomes), completed, retrying, terminal_failed)


def _reference_unchanged(enrollment: MyPhotoEnrollmentModel, claim: _DeletionClaim) -> bool:
    if claim.kind == "superseded":
        return bool(enrollment.superseded_provider_reference_handle == claim.provider_reference)
    return bool(
        enrollment.status == "deleted"
        and enrollment.provider_reference_handle == claim.provider_reference
        and enrollment.deletion_idempotency_key == claim.deletion_identity
    )


def _complete_reference(
    enrollment: MyPhotoEnrollmentModel, kind: DeletionKind, now: datetime
) -> None:
    if kind == "superseded":
        enrollment.superseded_provider_reference_handle = None
        enrollment.superseded_reference_deletion_status = "complete"
        enrollment.superseded_reference_deletion_error_code = None
        enrollment.superseded_reference_deletion_completed_at = now
        enrollment.superseded_deletion_attempt_count = 0
        enrollment.superseded_deletion_next_attempt_at = None
    else:
        enrollment.provider_name = None
        enrollment.provider_reference_handle = None
        enrollment.provider_deletion_status = "complete"
        enrollment.provider_deletion_error_code = None
        enrollment.provider_deletion_completed_at = now
        enrollment.provider_deletion_next_attempt_at = None


def _pending_reference(
    enrollment: MyPhotoEnrollmentModel,
    kind: DeletionKind,
    error_code: str | None,
) -> None:
    if kind == "superseded":
        enrollment.superseded_reference_deletion_status = "pending"
        enrollment.superseded_reference_deletion_error_code = error_code
    else:
        enrollment.provider_deletion_status = "pending"
        enrollment.provider_deletion_error_code = error_code


def _fail_reference(
    enrollment: MyPhotoEnrollmentModel,
    kind: DeletionKind,
    error_code: str | None,
) -> None:
    stable = error_code or "PROVIDER_DELETION_UNAVAILABLE"
    if kind == "superseded":
        enrollment.superseded_reference_deletion_status = "failed"
        enrollment.superseded_reference_deletion_error_code = stable
    else:
        enrollment.provider_deletion_status = "failed"
        enrollment.provider_deletion_error_code = stable


def _deletion_retry_delay(claim: _DeletionClaim, settings: Settings) -> int:
    base = min(
        settings.my_photos.job_retry_max_seconds,
        settings.my_photos.job_retry_base_seconds * (2 ** min(max(claim.attempt_count - 1, 0), 8)),
    )
    digest = hashlib.sha256(
        f"{claim.enrollment_id}:{claim.kind}:{claim.attempt_count}".encode("ascii")
    ).digest()
    jitter = int.from_bytes(digest[:2], "big") % max(1, base // 2 + 1)
    return int(min(settings.my_photos.job_retry_max_seconds, base + jitter))


def _set_next_attempt(
    enrollment: MyPhotoEnrollmentModel,
    kind: DeletionKind,
    value: datetime | None,
) -> None:
    if kind == "superseded":
        enrollment.superseded_deletion_next_attempt_at = value
    else:
        enrollment.provider_deletion_next_attempt_at = value


def _due(value: datetime | None, now: datetime) -> bool:
    if value is None:
        return True
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return normalized <= now


def _stable_error(value: str) -> str:
    normalized = "".join(
        character if character.isascii() and (character.isalnum() or character == "_") else "_"
        for character in value.upper()
    )
    return normalized[:64] or "PROVIDER_DELETION_UNAVAILABLE"


__all__ = [
    "DurableDispatch",
    "ProviderDeletionBatchResult",
    "execute_provider_deletion_batch",
    "recoverable_dispatches",
]
