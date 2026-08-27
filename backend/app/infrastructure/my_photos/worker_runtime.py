"""Lease-based My Photos search worker with no database lock across provider I/O."""

from __future__ import annotations

import asyncio
import hashlib
import math
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import and_, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.my_photos.errors import MyPhotosUnavailable
from app.application.my_photos.providers import (
    FaceSearchRequest,
    FaceSearchResult,
    ProviderFaceMatch,
)
from app.core.config.settings import Settings, get_settings
from app.infrastructure.database.gc_mobile_models import MobilePassengerIdentityModel
from app.infrastructure.database.my_photos_models import (
    MyPhotoEnrollmentModel,
    MyPhotoFaceOccurrenceModel,
    MyPhotoGalleryModel,
    MyPhotoJobModel,
    MyPhotoMatchModel,
    MyPhotoMediaAssetModel,
    MyPhotoSearchRunModel,
)
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.my_photos.audit import record_my_photos_audit
from app.infrastructure.my_photos.providers import MyPhotosProviderBundle, build_provider_bundle
from app.infrastructure.my_photos.telemetry import my_photos_metrics

WorkerState = Literal[
    "succeeded", "retrying", "failed", "cancelled", "lease_busy", "lease_lost", "noop"
]


@dataclass(frozen=True, slots=True)
class SearchJobExecutionResult:
    state: WorkerState
    retry_after_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class _SearchClaim:
    search_run_id: uuid.UUID
    job_id: uuid.UUID
    lease_owner: str
    agency_id: uuid.UUID
    group_id: uuid.UUID
    passenger_identity_id: uuid.UUID
    enrollment_id: uuid.UUID
    gallery_id: uuid.UUID
    gallery_revision: int
    face_index_version: int
    enrollment_version: int
    collection_reference: str
    reference_face_handle: str
    total_face_count: int
    attempt_count: int
    max_attempts: int


async def execute_search_job(
    search_run_id: uuid.UUID,
    *,
    settings: Settings | None = None,
    providers: MyPhotosProviderBundle | None = None,
    lease_owner: str | None = None,
) -> SearchJobExecutionResult:
    """Claim, invoke, and conditionally finalize one pre-indexed collection search."""

    resolved_settings = settings or get_settings()
    resolved_providers = providers or build_provider_bundle(resolved_settings)
    owner = lease_owner or f"my-photos-search:{uuid.uuid4().hex}"
    claim_or_result = await _claim_search(search_run_id, owner, resolved_settings)
    if isinstance(claim_or_result, SearchJobExecutionResult):
        return claim_or_result
    claim = claim_or_result

    started = time.perf_counter()
    try:
        async with asyncio.timeout(
            resolved_settings.my_photos.face_search_provider_timeout_seconds
        ):
            provider_result = await resolved_providers.face_search.search(
                FaceSearchRequest(
                    tenant_scope=str(claim.agency_id),
                    group_scope=str(claim.group_id),
                    collection_reference=claim.collection_reference,
                    reference_face_handle=claim.reference_face_handle,
                    maximum_results=resolved_settings.my_photos.maximum_search_results,
                )
            )
    except MyPhotosUnavailable as exc:
        category = "throttled" if "THROTTLED" in exc.code else "unavailable"
        my_photos_metrics.provider(category)  # type: ignore[arg-type]
        outcome = await _retry_or_fail(
            claim,
            error_code=_stable_error_code(exc.code),
            settings=resolved_settings,
        )
        my_photos_metrics.search_finished(
            outcome="retrying" if outcome.state == "retrying" else "failed",
            duration_ms=(time.perf_counter() - started) * 1_000,
        )
        return outcome
    except Exception:
        # Provider adapters must sanitize their own errors. This boundary still
        # persists a stable retry category without logging payloads or references.
        my_photos_metrics.provider("unavailable")
        outcome = await _retry_or_fail(
            claim,
            error_code="PROVIDER_UNAVAILABLE",
            settings=resolved_settings,
        )
        my_photos_metrics.search_finished(
            outcome="retrying" if outcome.state == "retrying" else "failed",
            duration_ms=(time.perf_counter() - started) * 1_000,
        )
        return outcome

    try:
        validated_result = _validated_provider_result(
            provider_result,
            maximum_results=resolved_settings.my_photos.maximum_search_results,
        )
    except ValueError:
        outcome = await _terminal_claim_failure(claim, "PROVIDER_RESULT_INVALID")
        my_photos_metrics.search_finished(
            outcome="failed",
            duration_ms=(time.perf_counter() - started) * 1_000,
        )
        return outcome

    try:
        outcome = await _finalize_search(claim, validated_result, resolved_settings)
    except Exception:
        # A crash after provider success is safe to redeliver: no matches are
        # published until the final transaction commits, and publication is
        # protected by the passenger lock plus active-match uniqueness.
        outcome = await _retry_or_fail(
            claim,
            error_code="SEARCH_FINALIZE_FAILED",
            settings=resolved_settings,
        )
    metric_outcome = "complete" if outcome.state == "succeeded" else outcome.state
    my_photos_metrics.search_finished(
        outcome=metric_outcome,
        duration_ms=(time.perf_counter() - started) * 1_000,
    )
    return outcome


async def _claim_search(
    search_run_id: uuid.UUID,
    lease_owner: str,
    settings: Settings,
) -> _SearchClaim | SearchJobExecutionResult:
    async with AsyncSessionFactory() as session:
        scope = (
            await session.execute(
                select(
                    MyPhotoSearchRunModel.passenger_identity_id,
                    MyPhotoSearchRunModel.agency_id,
                    MyPhotoSearchRunModel.group_id,
                ).where(MyPhotoSearchRunModel.id == search_run_id)
            )
        ).one_or_none()
        if scope is None:
            return SearchJobExecutionResult(state="noop")
        await session.execute(
            select(MobilePassengerIdentityModel.id)
            .where(
                MobilePassengerIdentityModel.id == scope.passenger_identity_id,
                MobilePassengerIdentityModel.agency_id == scope.agency_id,
                MobilePassengerIdentityModel.group_id == scope.group_id,
            )
            .with_for_update()
        )
        search = (
            await session.execute(
                select(MyPhotoSearchRunModel)
                .where(MyPhotoSearchRunModel.id == search_run_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if search is None or search.status in {"complete", "cancelled", "failed"}:
            return SearchJobExecutionResult(state="noop")
        job = (
            await session.execute(
                select(MyPhotoJobModel)
                .where(
                    MyPhotoJobModel.search_run_id == search.id,
                    MyPhotoJobModel.job_type == "search_passenger",
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if job is None:
            search.status = "failed"
            search.stable_error_code = "SEARCH_JOB_MISSING"
            search.completed_at = datetime.now(tz=UTC)
            await _audit_search(session, search, "failed", settings)
            await session.commit()
            my_photos_metrics.job("failed")
            return SearchJobExecutionResult(state="failed")

        now = datetime.now(tz=UTC)
        if job.cancellation_requested_at is not None:
            search.status = "cancelled"
            search.completed_at = now
            search.lease_owner = None
            search.lease_expires_at = None
            job.status = "cancelled"
            job.completed_at = now
            job.lease_owner = None
            job.lease_expires_at = None
            await session.commit()
            my_photos_metrics.job("cancelled")
            return SearchJobExecutionResult(state="cancelled")
        if job.next_attempt_at is not None and _utc(job.next_attempt_at) > now:
            retry_after = max(1, int((_utc(job.next_attempt_at) - now).total_seconds()))
            return SearchJobExecutionResult("retrying", retry_after)
        if (
            search.lease_owner is not None
            and search.lease_expires_at is not None
            and _utc(search.lease_expires_at) > now
        ):
            my_photos_metrics.job("lease_busy")
            retry_after = max(
                1,
                math.ceil((_utc(search.lease_expires_at) - now).total_seconds()),
            )
            return SearchJobExecutionResult(state="lease_busy", retry_after_seconds=retry_after)
        if search.attempt_count >= search.max_attempts or job.attempt_count >= job.max_attempts:
            _mark_terminal_failure(search, job, now, "SEARCH_RETRY_EXHAUSTED")
            await _audit_search(session, search, "failed", settings)
            await session.commit()
            my_photos_metrics.job("failed")
            return SearchJobExecutionResult(state="failed")

        enrollment = (
            await session.execute(
                select(MyPhotoEnrollmentModel).where(
                    MyPhotoEnrollmentModel.id == search.enrollment_id,
                    MyPhotoEnrollmentModel.passenger_identity_id == search.passenger_identity_id,
                    MyPhotoEnrollmentModel.agency_id == search.agency_id,
                    MyPhotoEnrollmentModel.group_id == search.group_id,
                    MyPhotoEnrollmentModel.reference_version == search.enrollment_version,
                    MyPhotoEnrollmentModel.status == "enrolled",
                )
            )
        ).scalar_one_or_none()
        gallery = (
            await session.execute(
                select(MyPhotoGalleryModel).where(
                    MyPhotoGalleryModel.id == search.gallery_id,
                    MyPhotoGalleryModel.agency_id == search.agency_id,
                    MyPhotoGalleryModel.group_id == search.group_id,
                    MyPhotoGalleryModel.feature_enabled.is_(True),
                    MyPhotoGalleryModel.status == "ready",
                    MyPhotoGalleryModel.published_revision == search.gallery_revision,
                    MyPhotoGalleryModel.face_index_version == search.face_index_version,
                )
            )
        ).scalar_one_or_none()
        if (
            enrollment is None
            or gallery is None
            or enrollment.provider_reference_handle is None
            or gallery.provider_collection_reference is None
            or _gallery_window_closed(gallery, now)
        ):
            _mark_terminal_failure(search, job, now, "SEARCH_SCOPE_STALE")
            await _audit_search(session, search, "failed", settings)
            await session.commit()
            my_photos_metrics.job("failed")
            return SearchJobExecutionResult(state="failed")

        redelivery = search.attempt_count > 0 or job.attempt_count > 0
        if redelivery:
            my_photos_metrics.idempotent_redelivery("search")
        lease_expires_at = now + timedelta(seconds=settings.my_photos.job_lease_seconds)
        search.status = "searching"
        search.started_at = search.started_at or now
        search.attempt_count += 1
        search.lease_owner = lease_owner
        search.lease_expires_at = lease_expires_at
        search.heartbeat_at = now
        search.stable_error_code = None
        job.status = "running"
        job.attempt_count += 1
        job.started_at = job.started_at or now
        job.lease_owner = lease_owner
        job.lease_expires_at = lease_expires_at
        job.heartbeat_at = now
        job.next_attempt_at = None
        job.stable_error_code = None
        job.error_detail = None
        await session.commit()
        my_photos_metrics.job("redelivered" if redelivery else "claimed")
        return _SearchClaim(
            search_run_id=search.id,
            job_id=job.id,
            lease_owner=lease_owner,
            agency_id=search.agency_id,
            group_id=search.group_id,
            passenger_identity_id=search.passenger_identity_id,
            enrollment_id=search.enrollment_id,
            gallery_id=search.gallery_id,
            gallery_revision=search.gallery_revision,
            face_index_version=search.face_index_version,
            enrollment_version=search.enrollment_version,
            collection_reference=gallery.provider_collection_reference,
            reference_face_handle=enrollment.provider_reference_handle,
            total_face_count=search.total_face_count,
            attempt_count=search.attempt_count,
            max_attempts=min(search.max_attempts, job.max_attempts),
        )


async def _retry_or_fail(
    claim: _SearchClaim,
    *,
    error_code: str,
    settings: Settings,
) -> SearchJobExecutionResult:
    async with AsyncSessionFactory() as session:
        search, job = await _locked_claim_rows(session, claim)
        if search is None or job is None:
            my_photos_metrics.job("lease_lost")
            return SearchJobExecutionResult(state="lease_lost", retry_after_seconds=1)
        now = datetime.now(tz=UTC)
        if claim.attempt_count >= claim.max_attempts:
            _mark_terminal_failure(search, job, now, error_code)
            await _audit_search(session, search, "failed", settings)
            await session.commit()
            my_photos_metrics.job("failed")
            return SearchJobExecutionResult(state="failed")
        retry_after = _retry_delay(claim, settings)
        search.status = "queued"
        search.stable_error_code = error_code
        search.lease_owner = None
        search.lease_expires_at = None
        search.heartbeat_at = now
        job.status = "retrying"
        job.stable_error_code = error_code
        job.error_detail = "Search provider returned a retry-safe stable category."
        job.next_attempt_at = now + timedelta(seconds=retry_after)
        job.lease_owner = None
        job.lease_expires_at = None
        job.heartbeat_at = now
        await session.commit()
        my_photos_metrics.job("retrying")
        return SearchJobExecutionResult("retrying", retry_after)


async def _terminal_claim_failure(
    claim: _SearchClaim,
    error_code: str,
) -> SearchJobExecutionResult:
    async with AsyncSessionFactory() as session:
        search, job = await _locked_claim_rows(session, claim)
        if search is None or job is None:
            my_photos_metrics.job("lease_lost")
            return SearchJobExecutionResult(state="lease_lost", retry_after_seconds=1)
        _mark_terminal_failure(search, job, datetime.now(tz=UTC), error_code)
        await session.commit()
        my_photos_metrics.job("failed")
        return SearchJobExecutionResult(state="failed")


async def _finalize_search(
    claim: _SearchClaim,
    result: FaceSearchResult,
    settings: Settings,
) -> SearchJobExecutionResult:
    async with AsyncSessionFactory() as session:
        await session.execute(
            select(MobilePassengerIdentityModel.id)
            .where(
                MobilePassengerIdentityModel.id == claim.passenger_identity_id,
                MobilePassengerIdentityModel.agency_id == claim.agency_id,
                MobilePassengerIdentityModel.group_id == claim.group_id,
            )
            .with_for_update()
        )
        search, job = await _locked_claim_rows(session, claim)
        now = datetime.now(tz=UTC)
        if search is None or job is None:
            my_photos_metrics.job("lease_lost")
            return SearchJobExecutionResult(state="lease_lost", retry_after_seconds=1)
        if search.lease_expires_at is None or _utc(search.lease_expires_at) <= now:
            my_photos_metrics.job("lease_lost")
            return SearchJobExecutionResult(state="lease_lost", retry_after_seconds=1)

        enrollment = (
            await session.execute(
                select(MyPhotoEnrollmentModel).where(
                    MyPhotoEnrollmentModel.id == claim.enrollment_id,
                    MyPhotoEnrollmentModel.passenger_identity_id == claim.passenger_identity_id,
                    MyPhotoEnrollmentModel.reference_version == claim.enrollment_version,
                    MyPhotoEnrollmentModel.status == "enrolled",
                )
            )
        ).scalar_one_or_none()
        gallery = (
            await session.execute(
                select(MyPhotoGalleryModel).where(
                    MyPhotoGalleryModel.id == claim.gallery_id,
                    MyPhotoGalleryModel.feature_enabled.is_(True),
                    MyPhotoGalleryModel.published_revision == claim.gallery_revision,
                    MyPhotoGalleryModel.face_index_version == claim.face_index_version,
                    MyPhotoGalleryModel.status == "ready",
                )
            )
        ).scalar_one_or_none()
        if enrollment is None or gallery is None or _gallery_window_closed(gallery, now):
            _mark_terminal_failure(search, job, now, "SEARCH_SCOPE_STALE")
            await _audit_search(session, search, "failed", settings)
            await session.commit()
            my_photos_metrics.job("failed")
            return SearchJobExecutionResult(state="failed")

        provider_matches = {
            match.provider_face_reference: match
            for match in result.matches[: settings.my_photos.maximum_search_results]
        }
        rows: list[tuple[MyPhotoFaceOccurrenceModel, MyPhotoMediaAssetModel]] = []
        if provider_matches:
            rows = list(
                (
                    await session.execute(
                        select(MyPhotoFaceOccurrenceModel, MyPhotoMediaAssetModel)
                        .join(
                            MyPhotoMediaAssetModel,
                            and_(
                                MyPhotoMediaAssetModel.id
                                == MyPhotoFaceOccurrenceModel.media_asset_id,
                                MyPhotoMediaAssetModel.agency_id
                                == MyPhotoFaceOccurrenceModel.agency_id,
                                MyPhotoMediaAssetModel.group_id
                                == MyPhotoFaceOccurrenceModel.group_id,
                            ),
                        )
                        .where(
                            MyPhotoFaceOccurrenceModel.agency_id == claim.agency_id,
                            MyPhotoFaceOccurrenceModel.group_id == claim.group_id,
                            MyPhotoFaceOccurrenceModel.index_version <= claim.face_index_version,
                            MyPhotoFaceOccurrenceModel.active.is_(True),
                            MyPhotoFaceOccurrenceModel.provider_face_reference.in_(
                                tuple(provider_matches)
                            ),
                            MyPhotoMediaAssetModel.gallery_id == claim.gallery_id,
                            MyPhotoMediaAssetModel.published_revision <= claim.gallery_revision,
                        )
                    )
                )
                .tuples()
                .all()
            )
        rows.sort(
            key=lambda row: (
                -provider_matches[row[0].provider_face_reference].similarity,
                row[1].sort_rank,
                row[1].id.hex,
            )
        )
        # Passenger feedback is a durable match-quality signal. Carry it to
        # the new version for the same immutable asset while retaining the old
        # row as inactive audit history; do not reuse mutation idempotency keys.
        prior_feedback = dict(
            (
                await session.execute(
                    select(MyPhotoMatchModel.media_asset_id, MyPhotoMatchModel.feedback).where(
                        MyPhotoMatchModel.passenger_identity_id == claim.passenger_identity_id,
                        MyPhotoMatchModel.group_id == claim.group_id,
                        MyPhotoMatchModel.active.is_(True),
                        MyPhotoMatchModel.feedback.in_(("this_is_me", "not_me")),
                    )
                )
            )
            .tuples()
            .all()
        )
        await session.execute(
            update(MyPhotoMatchModel)
            .where(
                MyPhotoMatchModel.passenger_identity_id == claim.passenger_identity_id,
                MyPhotoMatchModel.group_id == claim.group_id,
                MyPhotoMatchModel.active.is_(True),
            )
            .values(active=False, superseded_at=now, updated_at=now)
        )
        match_rows: list[dict[str, object]] = []
        seen_assets: set[uuid.UUID] = set()
        best_count = 0
        possible_count = 0
        config = settings.my_photos
        for face, asset in rows:
            provider_match = provider_matches[face.provider_face_reference]
            if (
                asset.id in seen_assets
                or provider_match.similarity < config.possible_match_threshold
            ):
                continue
            seen_assets.add(asset.id)
            tier = (
                "best" if provider_match.similarity >= config.best_match_threshold else "possible"
            )
            best_count += int(tier == "best")
            possible_count += int(tier == "possible")
            match_rows.append(
                {
                    "id": uuid.uuid4(),
                    "search_run_id": search.id,
                    "passenger_identity_id": claim.passenger_identity_id,
                    "media_asset_id": asset.id,
                    "face_occurrence_id": face.id,
                    "agency_id": claim.agency_id,
                    "group_id": claim.group_id,
                    "gallery_revision": claim.gallery_revision,
                    "similarity": provider_match.similarity,
                    "display_tier": tier,
                    "match_config_version": config.match_config_version,
                    "feedback": prior_feedback.get(asset.id, "none"),
                    "active": True,
                    "sort_rank": asset.sort_rank,
                    "created_at": now,
                    "updated_at": now,
                }
            )
        if match_rows:
            await session.execute(insert(MyPhotoMatchModel), match_rows)
        search.status = "complete"
        search.processed_face_count = search.total_face_count
        search.matched_asset_count = len(match_rows)
        search.best_match_count = best_count
        search.possible_match_count = possible_count
        search.checkpoint_cursor = f"complete:{len(match_rows)}"
        search.completed_at = now
        search.heartbeat_at = now
        search.lease_owner = None
        search.lease_expires_at = None
        search.stable_error_code = None
        job.status = "succeeded"
        job.processed_count = job.total_count
        job.succeeded_count = job.total_count
        job.failed_count = 0
        job.checkpoint_cursor = search.checkpoint_cursor
        job.completed_at = now
        job.heartbeat_at = now
        job.lease_owner = None
        job.lease_expires_at = None
        await _audit_search(session, search, "complete", settings)
        await session.commit()
        my_photos_metrics.job("succeeded")
        return SearchJobExecutionResult(state="succeeded")


async def _locked_claim_rows(
    session: AsyncSession, claim: _SearchClaim
) -> tuple[MyPhotoSearchRunModel | None, MyPhotoJobModel | None]:
    search = (
        await session.execute(
            select(MyPhotoSearchRunModel)
            .where(
                MyPhotoSearchRunModel.id == claim.search_run_id,
                MyPhotoSearchRunModel.status == "searching",
                MyPhotoSearchRunModel.lease_owner == claim.lease_owner,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    job = (
        await session.execute(
            select(MyPhotoJobModel)
            .where(
                MyPhotoJobModel.id == claim.job_id,
                MyPhotoJobModel.status == "running",
                MyPhotoJobModel.lease_owner == claim.lease_owner,
                MyPhotoJobModel.cancellation_requested_at.is_(None),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    return search, job


def _validated_provider_result(
    result: FaceSearchResult,
    *,
    maximum_results: int,
) -> FaceSearchResult:
    model_version = result.provider_model_version
    if (
        not isinstance(model_version, str)
        or not 1 <= len(model_version) <= 64
        or model_version != model_version.strip()
        or any(ord(character) < 32 for character in model_version)
    ):
        raise ValueError("provider model version is invalid")
    if not isinstance(result.matches, tuple) or len(result.matches) > maximum_results:
        raise ValueError("provider result count is invalid")

    # Provider redelivery may repeat a face reference. Coalesce it
    # deterministically to the highest bounded similarity instead of allowing
    # duplicate application match rows or last-write-wins behavior.
    unique: dict[str, float] = {}
    for match in result.matches:
        reference = match.provider_face_reference
        similarity = match.similarity
        if (
            not isinstance(reference, str)
            or not 1 <= len(reference) <= 512
            or reference != reference.strip()
            or any(ord(character) < 32 for character in reference)
            or isinstance(similarity, bool)
            or not isinstance(similarity, (int, float))
            or not math.isfinite(float(similarity))
            or not 0.0 <= float(similarity) <= 100.0
        ):
            raise ValueError("provider face match is invalid")
        unique[reference] = max(unique.get(reference, 0.0), float(similarity))

    normalized = tuple(
        ProviderFaceMatch(provider_face_reference=reference, similarity=similarity)
        for reference, similarity in sorted(unique.items())
    )
    return FaceSearchResult(
        matches=normalized,
        provider_model_version=model_version,
    )


def _mark_terminal_failure(
    search: MyPhotoSearchRunModel,
    job: MyPhotoJobModel,
    now: datetime,
    error_code: str,
) -> None:
    stable = _stable_error_code(error_code)
    search.status = "failed"
    search.stable_error_code = stable
    search.completed_at = now
    search.lease_owner = None
    search.lease_expires_at = None
    job.status = "failed"
    job.stable_error_code = stable
    job.error_detail = "Search stopped with a stable, privacy-safe category."
    job.completed_at = now
    job.lease_owner = None
    job.lease_expires_at = None


def _retry_delay(claim: _SearchClaim, settings: Settings) -> int:
    base = min(
        settings.my_photos.job_retry_max_seconds,
        settings.my_photos.job_retry_base_seconds * (2 ** min(claim.attempt_count - 1, 8)),
    )
    digest = hashlib.sha256(f"{claim.search_run_id}:{claim.attempt_count}".encode("ascii")).digest()
    jitter = int.from_bytes(digest[:2], "big") % max(1, base // 2 + 1)
    return int(min(settings.my_photos.job_retry_max_seconds, base + jitter))


def _stable_error_code(value: str) -> str:
    normalized = "".join(
        char if char.isascii() and (char.isalnum() or char == "_") else "_"
        for char in value.upper()
    ).strip("_")
    return (normalized or "SEARCH_FAILED")[:64]


def _gallery_window_closed(gallery: MyPhotoGalleryModel, now: datetime) -> bool:
    return bool(
        (gallery.availability_starts_at is not None and now < _utc(gallery.availability_starts_at))
        or (gallery.availability_ends_at is not None and now >= _utc(gallery.availability_ends_at))
    )


async def _audit_search(
    session: AsyncSession,
    search: MyPhotoSearchRunModel,
    outcome: str,
    settings: Settings,
) -> None:
    await record_my_photos_audit(
        session,
        action="my_photos_search_finished",
        agency_id=search.agency_id,
        group_id=search.group_id,
        outcome=outcome,
        gallery_revision=search.gallery_revision,
        configuration_version=settings.my_photos.match_config_version,
    )


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


__all__ = ["SearchJobExecutionResult", "execute_search_job"]
