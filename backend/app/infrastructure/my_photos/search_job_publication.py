"""Revision-bound match publication and feedback carry-forward transaction."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, insert, select, update

from app.application.my_photos.providers import FaceSearchResult
from app.core.config.settings import Settings
from app.infrastructure.database.gc_mobile_models import MobilePassengerIdentityModel
from app.infrastructure.database.my_photos_models import (
    MyPhotoEnrollmentModel,
    MyPhotoFaceOccurrenceModel,
    MyPhotoGalleryModel,
    MyPhotoMatchModel,
    MyPhotoMediaAssetModel,
)
from app.infrastructure.my_photos.search_job_contracts import (
    SearchJobExecutionResult,
    SearchWorkerContext,
    _SearchClaim,
)
from app.infrastructure.my_photos.search_job_lifecycle import _audit_search, _mark_terminal_failure
from app.infrastructure.my_photos.search_job_policy import _gallery_window_closed, _utc
from app.infrastructure.my_photos.search_job_queries import _locked_claim_rows
from app.infrastructure.my_photos.telemetry import my_photos_metrics


async def _finalize_search(
    ctx: SearchWorkerContext,
    claim: _SearchClaim,
    result: FaceSearchResult,
    settings: Settings,
) -> SearchJobExecutionResult:
    async with ctx.session_factory() as session:
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
