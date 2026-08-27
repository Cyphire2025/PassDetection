"""Authorized My Photos application service and explicit state transitions."""

from __future__ import annotations

import asyncio
import hashlib
import math
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.my_photos.cursor import GalleryCursor, GalleryCursorCodec
from app.application.my_photos.errors import (
    MyPhotosConflict,
    MyPhotosInvalidCursor,
    MyPhotosRateLimited,
    MyPhotosUnavailable,
)
from app.application.my_photos.providers import (
    DeliveryResolution,
    LivenessResult,
    LivenessSessionRequest,
    ReferenceDeletionRequest,
)
from app.application.my_photos.states import (
    MatchFilter,
)
from app.application.security.mobile_access_policy import AuthorizedMobileTrip
from app.core.config.settings import Settings, get_settings
from app.core.security.mobile_jwt import MobileAccessClaims
from app.domain.exceptions.exceptions import AuthorizationError, EntityNotFoundError
from app.infrastructure.database.gc_mobile_models import MobilePassengerIdentityModel
from app.infrastructure.database.my_photos_models import (
    MyPhotoEnrollmentModel,
    MyPhotoFaceOccurrenceModel,
    MyPhotoGalleryModel,
    MyPhotoJobModel,
    MyPhotoLivenessSessionModel,
    MyPhotoMatchModel,
    MyPhotoMediaAssetModel,
    MyPhotoSearchRunModel,
)
from app.infrastructure.my_photos.audit import record_my_photos_audit
from app.infrastructure.my_photos.delivery_service import MyPhotosDeliveryService
from app.infrastructure.my_photos.liveness_validation import (
    _as_utc,
    _liveness_processing,
    _provider_claim_active,
    _validated_liveness_result,
    _validated_liveness_session_handle,
)
from app.infrastructure.my_photos.providers import MyPhotosProviderBundle, build_provider_bundle
from app.infrastructure.my_photos.summary_projector import MyPhotosSummaryProjector
from app.infrastructure.my_photos.telemetry import my_photos_metrics
from app.presentation.api.v1.schemas.my_photos_schemas import (
    MyPhotosConsentRequest,
    MyPhotosDeleteEnrollmentRequest,
    MyPhotosDeleteEnrollmentResponse,
    MyPhotosDownloadAuthorizationRequest,
    MyPhotosDownloadAuthorizationResponse,
    MyPhotosDownloadPlanResponse,
    MyPhotosFeedbackRequest,
    MyPhotosFeedbackResponse,
    MyPhotosLivenessCompleteRequest,
    MyPhotosLivenessCompleteResponse,
    MyPhotosLivenessSessionResponse,
    MyPhotosLivenessStartRequest,
    MyPhotosPhotoPageResponse,
    MyPhotosPrepareRequest,
    MyPhotosPrepareResponse,
    MyPhotosSearchResponse,
    MyPhotosSearchRunResponse,
    MyPhotosSummaryResponse,
)


class MyPhotosService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        settings: Settings | None = None,
        providers: MyPhotosProviderBundle | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._providers = providers or build_provider_bundle(self._settings)
        self._cursor = GalleryCursorCodec(self._settings.app_secret_key)
        self._delivery = MyPhotosDeliveryService(
            session,
            settings=self._settings,
            providers=self._providers,
            require_passenger=self._require_passenger,
            ready_gallery=self._ready_gallery,
            lock_passenger_identity=self._lock_passenger_identity,
        )
        self._summary = MyPhotosSummaryProjector(
            session,
            settings=self._settings,
            providers=self._providers,
            gallery_window_state=self._gallery_window_state,
            search_response=self._search_response,
        )

    async def summary(
        self, *, claims: MobileAccessClaims, trip: AuthorizedMobileTrip
    ) -> MyPhotosSummaryResponse:
        identity = self._require_passenger(claims, trip)
        gallery = await self._gallery(claims.agency_id, trip.group.id)
        enrollment = await self._enrollment(identity.id, trip.group.id)
        search = await self._latest_search(identity.id, trip.group.id)
        return await self._summary.build(
            group_name=trip.group.name,
            group_id=trip.group.id,
            gallery=gallery,
            enrollment=enrollment,
            search=search,
            passenger_identity_id=identity.id,
        )

    async def accept_consent(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        request: MyPhotosConsentRequest,
    ) -> MyPhotosSummaryResponse:
        identity = self._require_passenger(claims, trip)
        gallery = await self._ready_gallery(claims.agency_id, trip.group.id)
        self._require_face_providers()
        await self._lock_passenger_identity(identity.id, claims.agency_id, trip.group.id)
        config = self._settings.my_photos
        if request.consent_version != config.consent_version:
            raise MyPhotosConflict(
                "MY_PHOTOS_CONSENT_VERSION_REQUIRED",
                "The Face Scan consent text changed. Review the current consent before continuing.",
            )
        now = datetime.now(tz=UTC)
        enrollment = await self._enrollment(identity.id, trip.group.id, for_update=True)
        consent_changed = False
        if enrollment is None:
            enrollment = MyPhotoEnrollmentModel(
                passenger_identity_id=identity.id,
                passenger_submission_id=identity.passenger_submission_id,
                gc_group_access_id=trip.access.id,
                agency_id=claims.agency_id,
                group_id=trip.group.id,
                consent_version=request.consent_version,
                consented_at=now,
                consent_idempotency_key=request.idempotency_key,
                status="ready",
                max_attempts=config.maximum_liveness_attempts,
            )
            self._session.add(enrollment)
            consent_changed = True
        elif enrollment.consent_idempotency_key == request.idempotency_key:
            if enrollment.consent_version != request.consent_version:
                raise MyPhotosConflict(
                    "MY_PHOTOS_IDEMPOTENCY_CONFLICT",
                    "This request key was already used for different consent data.",
                )
        else:
            consent_changed = True
            enrollment.consent_version = request.consent_version
            enrollment.consented_at = now
            enrollment.consent_idempotency_key = request.idempotency_key
            if enrollment.status in {"revoked", "deleted"}:
                if enrollment.provider_deletion_status in {
                    "pending",
                    "failed",
                } or enrollment.superseded_reference_deletion_status in {"pending", "failed"}:
                    raise MyPhotosConflict(
                        "MY_PHOTOS_PROVIDER_DELETION_PENDING",
                        "Face Scan deletion is still being completed. Try again later.",
                    )
                if enrollment.attempt_count >= enrollment.max_attempts and (
                    enrollment.cooldown_until is None or _as_utc(enrollment.cooldown_until) > now
                ):
                    enrollment.status = "cooldown"
                    enrollment.cooldown_until = enrollment.cooldown_until or (
                        now + timedelta(seconds=config.liveness_cooldown_seconds)
                    )
                else:
                    enrollment.status = "ready"
                    if (
                        enrollment.cooldown_until is not None
                        and _as_utc(enrollment.cooldown_until) <= now
                    ):
                        enrollment.attempt_count = 0
                        enrollment.cooldown_until = None
                enrollment.revoked_at = None
                enrollment.deleted_at = None
                enrollment.deletion_idempotency_key = None
                enrollment.deletion_scope = None
                enrollment.provider_reference_handle = None
                enrollment.provider_name = None
                enrollment.reference_version = 0
                enrollment.provider_deletion_status = "not_required"
                enrollment.provider_deletion_error_code = None
                enrollment.provider_deletion_requested_at = None
                enrollment.provider_deletion_completed_at = None
                enrollment.provider_deletion_attempt_count = 0
                enrollment.provider_deletion_next_attempt_at = None
                enrollment.provider_deletion_last_attempt_at = None
                enrollment.superseded_provider_reference_handle = None
                enrollment.superseded_reference_deletion_status = "not_required"
                enrollment.superseded_reference_deletion_error_code = None
                enrollment.superseded_reference_deletion_requested_at = None
                enrollment.superseded_reference_deletion_completed_at = None
                enrollment.superseded_deletion_attempt_count = 0
                enrollment.superseded_deletion_next_attempt_at = None
                enrollment.superseded_deletion_last_attempt_at = None
        await self._session.flush()
        if consent_changed:
            await record_my_photos_audit(
                self._session,
                action="my_photos_consent_accepted",
                agency_id=claims.agency_id,
                group_id=trip.group.id,
                outcome="accepted",
                configuration_version=request.consent_version,
            )
        search = await self._latest_search(identity.id, trip.group.id)
        return await self._summary.build(
            group_name=trip.group.name,
            group_id=trip.group.id,
            gallery=gallery,
            enrollment=enrollment,
            search=search,
            passenger_identity_id=identity.id,
        )

    async def start_liveness(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        request: MyPhotosLivenessStartRequest,
    ) -> MyPhotosLivenessSessionResponse:
        identity = self._require_passenger(claims, trip)
        await self._ready_gallery(claims.agency_id, trip.group.id)
        self._require_face_providers()
        await self._lock_passenger_identity(identity.id, claims.agency_id, trip.group.id)
        enrollment = await self._required_current_enrollment(identity.id, trip.group.id)
        if enrollment.superseded_reference_deletion_status in {"pending", "failed"}:
            raise MyPhotosConflict(
                "MY_PHOTOS_REFERENCE_CLEANUP_PENDING",
                "The previous Face Scan reference is still being deleted. Try again later.",
            )
        now = datetime.now(tz=UTC)
        if enrollment.cooldown_until is not None:
            if _as_utc(enrollment.cooldown_until) > now:
                if enrollment.provider_reference_handle is None:
                    enrollment.status = "cooldown"
                raise MyPhotosRateLimited(
                    math.ceil((_as_utc(enrollment.cooldown_until) - now).total_seconds())
                )
            enrollment.attempt_count = 0
            enrollment.cooldown_until = None
            enrollment.status = (
                "enrolled" if enrollment.provider_reference_handle is not None else "ready"
            )
        active_session = (
            await self._session.execute(
                select(MyPhotoLivenessSessionModel)
                .where(
                    MyPhotoLivenessSessionModel.enrollment_id == enrollment.id,
                    MyPhotoLivenessSessionModel.status.in_(("creating", "created", "running")),
                )
                .order_by(
                    MyPhotoLivenessSessionModel.created_at.desc(),
                    MyPhotoLivenessSessionModel.id.desc(),
                )
                .limit(1)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if active_session is not None and _as_utc(active_session.expires_at) <= now:
            active_session.status = "expired"
            active_session.stable_error_code = "SESSION_EXPIRED"
            active_session.result_retryable = True
            active_session.consumed_at = now
            active_session.provider_claim_token = None
            active_session.provider_claim_expires_at = None
            active_session.native_launch_handle = None
            active_session = None
            if enrollment.attempt_count >= enrollment.max_attempts:
                if enrollment.provider_reference_handle is None:
                    enrollment.status = "cooldown"
                enrollment.cooldown_until = now + timedelta(
                    seconds=self._settings.my_photos.liveness_cooldown_seconds
                )
                raise MyPhotosRateLimited(self._settings.my_photos.liveness_cooldown_seconds)
            enrollment.status = "ready"
        if active_session is not None and active_session.idempotency_key != request.idempotency_key:
            raise MyPhotosRateLimited(
                max(
                    1,
                    math.ceil((_as_utc(active_session.expires_at) - now).total_seconds()),
                ),
                "Another Face Scan session is already active.",
                code="MY_PHOTOS_ACTIVE_SESSION_EXISTS",
            )
        existing = (
            await self._session.execute(
                select(MyPhotoLivenessSessionModel)
                .where(
                    MyPhotoLivenessSessionModel.enrollment_id == enrollment.id,
                    MyPhotoLivenessSessionModel.idempotency_key == request.idempotency_key,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        claim_token = uuid.uuid4().hex
        if existing is not None:
            if existing.challenge_mode != request.challenge_mode:
                raise MyPhotosConflict(
                    "MY_PHOTOS_IDEMPOTENCY_CONFLICT",
                    "This request key was already used for a different Face Scan mode.",
                )
            if existing.status == "created":
                return self._liveness_session_response(existing, enrollment)
            if existing.status != "creating":
                raise MyPhotosConflict(
                    "MY_PHOTOS_SESSION_ALREADY_USED",
                    "Use a new request key to start another Face Scan.",
                )
            if _provider_claim_active(existing, now):
                raise _liveness_processing(existing, now)
            liveness = existing
        else:
            if enrollment.attempt_count >= enrollment.max_attempts:
                if enrollment.provider_reference_handle is None:
                    enrollment.status = "cooldown"
                enrollment.cooldown_until = now + timedelta(
                    seconds=self._settings.my_photos.liveness_cooldown_seconds
                )
                raise MyPhotosRateLimited(self._settings.my_photos.liveness_cooldown_seconds)
            liveness = MyPhotoLivenessSessionModel(
                id=uuid.uuid4(),
                enrollment_id=enrollment.id,
                agency_id=claims.agency_id,
                group_id=trip.group.id,
                idempotency_key=request.idempotency_key,
                challenge_mode=request.challenge_mode,
                status="creating",
                provider_name=self._providers.provider_name,
                provider_session_reference=None,
                provider_claim_token=claim_token,
                provider_claim_expires_at=now
                + timedelta(seconds=self._settings.my_photos.liveness_provider_claim_seconds),
                expires_at=now
                + timedelta(seconds=self._settings.my_photos.liveness_session_ttl_seconds),
            )
            self._session.add(liveness)
            enrollment.attempt_count += 1
            enrollment.status = "session_pending"
            await self._session.flush()
        if existing is not None:
            liveness.provider_claim_token = claim_token
            liveness.provider_claim_expires_at = now + timedelta(
                seconds=self._settings.my_photos.liveness_provider_claim_seconds
            )

        # Commit the durable single-use reservation before calling a remote
        # liveness provider. Retrying the same idempotency key resumes this
        # logical session; a new passenger retry receives a new session ID.
        await self._session.commit()
        try:
            async with asyncio.timeout(self._settings.my_photos.liveness_provider_timeout_seconds):
                raw_provider_handle = await self._providers.liveness.create_session(
                    LivenessSessionRequest(
                        session_identity=str(liveness.id),
                        tenant_scope=str(claims.agency_id),
                        group_scope=str(trip.group.id),
                        passenger_scope=str(identity.id),
                        challenge_mode=request.challenge_mode,
                        expires_at=liveness.expires_at,
                        audit_image_retention_enabled=(
                            self._settings.my_photos.provider_audit_image_retention_enabled
                        ),
                        reference_frame_retention_seconds=(
                            self._settings.my_photos.reference_frame_retention_seconds
                        ),
                    )
                )
            client_flow = self._providers.liveness.client_flow
            if client_flow == "unavailable":
                raise MyPhotosUnavailable(
                    "MY_PHOTOS_PROVIDER_NOT_CONFIGURED",
                    "Face Scan is not available yet.",
                )
            provider_handle = _validated_liveness_session_handle(
                raw_provider_handle,
                requested_expiry=liveness.expires_at,
                client_flow=client_flow,
            )
        except MyPhotosUnavailable as exc:
            await self._fail_liveness_creation(liveness.id, enrollment.id, claim_token, exc.code)
            await self._session.commit()
            if exc.code == "MY_PHOTOS_PROVIDER_THROTTLED":
                raise MyPhotosRateLimited(
                    self._settings.my_photos.provider_retry_after_seconds,
                    "Face Scan is busy. Try again shortly.",
                    code="MY_PHOTOS_PROVIDER_THROTTLED",
                ) from exc
            raise
        except Exception as exc:
            await self._fail_liveness_creation(
                liveness.id,
                enrollment.id,
                claim_token,
                "MY_PHOTOS_PROVIDER_UNAVAILABLE",
            )
            await self._session.commit()
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_UNAVAILABLE",
                "Face Scan is temporarily unavailable.",
            ) from exc

        liveness = await self._complete_liveness_creation(
            liveness.id,
            enrollment.id,
            request.idempotency_key,
            claim_token,
            provider_handle.provider_reference,
            provider_handle.expires_at,
            provider_handle.native_launch_handle,
        )
        enrollment = await self._required_current_enrollment(identity.id, trip.group.id)
        return self._liveness_session_response(liveness, enrollment)

    async def complete_liveness(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        session_id: uuid.UUID,
        request: MyPhotosLivenessCompleteRequest,
    ) -> MyPhotosLivenessCompleteResponse:
        identity = self._require_passenger(claims, trip)
        gallery = await self._ready_gallery(claims.agency_id, trip.group.id)
        enrollment = await self._required_current_enrollment(identity.id, trip.group.id)
        liveness = (
            await self._session.execute(
                select(MyPhotoLivenessSessionModel)
                .where(
                    MyPhotoLivenessSessionModel.id == session_id,
                    MyPhotoLivenessSessionModel.enrollment_id == enrollment.id,
                    MyPhotoLivenessSessionModel.agency_id == claims.agency_id,
                    MyPhotoLivenessSessionModel.group_id == trip.group.id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if liveness is None:
            raise EntityNotFoundError("Face Scan session", session_id)
        if liveness.completion_idempotency_key is not None:
            if (
                liveness.completion_idempotency_key != request.idempotency_key
                or liveness.completion_outcome != request.outcome
            ):
                raise MyPhotosConflict(
                    "MY_PHOTOS_SESSION_ALREADY_USED",
                    "This Face Scan session has already been used.",
                )
            if liveness.status != "running":
                if enrollment.superseded_reference_deletion_status in {
                    "pending",
                    "failed",
                }:
                    enrollment = await self._delete_superseded_reference(
                        enrollment=enrollment,
                        passenger_identity_id=identity.id,
                    )
                search = await self._latest_search(identity.id, trip.group.id)
                return self._completion_response(liveness, enrollment, search)
            claim_check_time = datetime.now(tz=UTC)
            if _provider_claim_active(liveness, claim_check_time):
                raise _liveness_processing(liveness, claim_check_time)

        now = datetime.now(tz=UTC)
        if liveness.completion_idempotency_key is None:
            liveness.completion_idempotency_key = request.idempotency_key
            liveness.completion_outcome = request.outcome
        if request.outcome != "completed" or _as_utc(liveness.expires_at) <= now:
            liveness.provider_claim_token = None
            liveness.provider_claim_expires_at = None
            liveness.consumed_at = now
            liveness.native_launch_handle = None
            if request.outcome == "cancelled":
                liveness.status = "cancelled"
                liveness.stable_error_code = "SCAN_CANCELLED"
                liveness.result_retryable = True
                enrollment.status = (
                    "enrolled" if enrollment.provider_reference_handle is not None else "ready"
                )
            elif request.outcome == "expired" or _as_utc(liveness.expires_at) <= now:
                liveness.status = "expired"
                liveness.stable_error_code = "SESSION_EXPIRED"
                liveness.result_retryable = True
                enrollment.status = (
                    "enrolled" if enrollment.provider_reference_handle is not None else "rejected"
                )
            else:
                liveness.status = "failed"
                liveness.stable_error_code = "SCAN_INTERRUPTED"
                liveness.result_retryable = True
                enrollment.status = (
                    "enrolled" if enrollment.provider_reference_handle is not None else "rejected"
                )
            self._apply_liveness_cooldown(enrollment, now)
            await self._session.flush()
            return self._completion_response(liveness, enrollment, None)

        self._require_face_providers()
        if liveness.provider_session_reference is None:
            raise MyPhotosConflict(
                "MY_PHOTOS_SESSION_NOT_READY", "Face Scan session is not ready. Start again."
            )
        liveness.status = "running"
        enrollment.status = "processing"
        provider_session_reference = liveness.provider_session_reference
        claim_token = uuid.uuid4().hex
        liveness.provider_claim_token = claim_token
        liveness.provider_claim_expires_at = now + timedelta(
            seconds=self._settings.my_photos.liveness_provider_claim_seconds
        )
        # Persist the completion claim and release row locks before provider I/O.
        await self._session.flush()
        await self._session.commit()
        try:
            async with asyncio.timeout(self._settings.my_photos.liveness_provider_timeout_seconds):
                raw_result = await self._providers.liveness.get_result(provider_session_reference)
            result = _validated_liveness_result(raw_result)
        except MyPhotosUnavailable as exc:
            await self._release_liveness_result_claim(session_id, claim_token)
            if "THROTTLED" in exc.code:
                my_photos_metrics.provider("throttled")
                raise MyPhotosRateLimited(
                    self._settings.my_photos.provider_retry_after_seconds,
                    "Face Scan verification is busy. Try again shortly.",
                    code="MY_PHOTOS_PROVIDER_THROTTLED",
                ) from exc
            my_photos_metrics.provider("unavailable")
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_UNAVAILABLE",
                "Face Scan verification is temporarily unavailable.",
            ) from exc
        except Exception as exc:
            # Keep provider failures sanitized. The durable completion claim is
            # intentionally left running so the same idempotency key can retry.
            my_photos_metrics.provider("unavailable")
            await self._release_liveness_result_claim(session_id, claim_token)
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_UNAVAILABLE",
                "Face Scan verification is temporarily unavailable.",
            ) from exc
        if result.outcome == "throttled":
            my_photos_metrics.provider("throttled")
            await self._release_liveness_result_claim(session_id, claim_token)
            raise MyPhotosRateLimited(
                self._settings.my_photos.provider_retry_after_seconds,
                "Face Scan verification is busy. Try again shortly.",
                code="MY_PHOTOS_PROVIDER_THROTTLED",
            )
        if result.outcome == "unavailable":
            my_photos_metrics.provider("unavailable")
            await self._release_liveness_result_claim(session_id, claim_token)
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_UNAVAILABLE",
                "Face Scan verification is temporarily unavailable.",
            )

        gallery = await self._ready_gallery(claims.agency_id, trip.group.id)
        liveness, enrollment, search = await self._finalize_liveness_result(
            identity_id=identity.id,
            gallery=gallery,
            session_id=session_id,
            idempotency_key=request.idempotency_key,
            provider_session_reference=provider_session_reference,
            provider_claim_token=claim_token,
            result=result,
        )
        if enrollment.superseded_reference_deletion_status in {"pending", "failed"}:
            enrollment = await self._delete_superseded_reference(
                enrollment=enrollment,
                passenger_identity_id=identity.id,
            )
        return self._completion_response(liveness, enrollment, search)

    async def search_status(
        self, *, claims: MobileAccessClaims, trip: AuthorizedMobileTrip
    ) -> MyPhotosSearchResponse:
        identity = self._require_passenger(claims, trip)
        await self._ready_gallery(claims.agency_id, trip.group.id)
        search = await self._latest_search(identity.id, trip.group.id)
        return MyPhotosSearchResponse(search=self._search_response(search))

    async def _create_search_run(
        self,
        *,
        enrollment: MyPhotoEnrollmentModel,
        gallery: MyPhotoGalleryModel,
        passenger_identity_id: uuid.UUID,
        liveness_session_id: uuid.UUID,
    ) -> MyPhotoSearchRunModel:
        idempotency_key = f"liveness:{liveness_session_id}:reference:{enrollment.reference_version}"
        existing = (
            await self._session.execute(
                select(MyPhotoSearchRunModel).where(
                    MyPhotoSearchRunModel.passenger_identity_id == passenger_identity_id,
                    MyPhotoSearchRunModel.group_id == gallery.group_id,
                    MyPhotoSearchRunModel.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing
        total_face_count = int(
            (
                await self._session.execute(
                    select(func.count(MyPhotoFaceOccurrenceModel.id)).where(
                        MyPhotoFaceOccurrenceModel.agency_id == gallery.agency_id,
                        MyPhotoFaceOccurrenceModel.group_id == gallery.group_id,
                        MyPhotoFaceOccurrenceModel.index_version <= gallery.face_index_version,
                        MyPhotoFaceOccurrenceModel.active.is_(True),
                    )
                )
            ).scalar_one()
        )
        search = MyPhotoSearchRunModel(
            enrollment_id=enrollment.id,
            passenger_identity_id=passenger_identity_id,
            gallery_id=gallery.id,
            agency_id=gallery.agency_id,
            group_id=gallery.group_id,
            gallery_revision=gallery.published_revision,
            face_index_version=gallery.face_index_version,
            enrollment_version=enrollment.reference_version,
            idempotency_key=idempotency_key,
            status="queued",
            total_face_count=total_face_count,
            max_attempts=self._settings.my_photos.job_max_attempts,
            correlation_id=uuid.uuid4().hex,
        )
        self._session.add(search)
        await self._session.flush()
        self._session.add(
            MyPhotoJobModel(
                gallery_id=gallery.id,
                search_run_id=search.id,
                agency_id=gallery.agency_id,
                group_id=gallery.group_id,
                job_type="search_passenger",
                status="queued",
                idempotency_key=idempotency_key,
                max_attempts=self._settings.my_photos.job_max_attempts,
                total_count=total_face_count,
                correlation_id=search.correlation_id,
            )
        )
        return search

    async def photo_page(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        match_filter: MatchFilter,
        cursor: str | None,
        limit: int,
    ) -> MyPhotosPhotoPageResponse:
        identity = self._require_passenger(claims, trip)
        gallery = await self._ready_gallery(claims.agency_id, trip.group.id)
        limit = min(limit, self._settings.my_photos.maximum_page_size)
        effective_match_revision = (
            await self._session.execute(
                select(func.max(MyPhotoMatchModel.gallery_revision)).where(
                    MyPhotoMatchModel.passenger_identity_id == identity.id,
                    MyPhotoMatchModel.group_id == trip.group.id,
                    MyPhotoMatchModel.gallery_revision <= gallery.published_revision,
                    MyPhotoMatchModel.active.is_(True),
                )
            )
        ).scalar_one()
        latest_completed_revision = (
            await self._session.execute(
                select(func.max(MyPhotoSearchRunModel.gallery_revision)).where(
                    MyPhotoSearchRunModel.passenger_identity_id == identity.id,
                    MyPhotoSearchRunModel.group_id == trip.group.id,
                    MyPhotoSearchRunModel.gallery_revision <= gallery.published_revision,
                    MyPhotoSearchRunModel.status == "complete",
                )
            )
        ).scalar_one()
        snapshot_revision = (
            gallery.published_revision
            if match_filter == "all"
            else int(latest_completed_revision or gallery.published_revision)
            if effective_match_revision is None
            else int(effective_match_revision)
        )
        try:
            decoded = (
                self._cursor.decode(
                    cursor,
                    passenger_id=identity.id,
                    group_id=trip.group.id,
                    revision=snapshot_revision,
                    match_filter=match_filter,
                )
                if cursor is not None
                else None
            )
        except MyPhotosInvalidCursor as exc:
            my_photos_metrics.pagination_error(
                "stale" if exc.code == "MY_PHOTOS_CURSOR_STALE" else "invalid"
            )
            raise
        query_rows: list[tuple[MyPhotoMatchModel | None, MyPhotoMediaAssetModel]]
        if match_filter == "all":
            if not gallery.all_group_photos_enabled:
                raise MyPhotosConflict(
                    "MY_PHOTOS_ALL_GROUP_DISABLED",
                    "All Group Photos is not enabled for this trip.",
                )
            join_condition = and_(
                MyPhotoMatchModel.media_asset_id == MyPhotoMediaAssetModel.id,
                MyPhotoMatchModel.passenger_identity_id == identity.id,
                MyPhotoMatchModel.gallery_revision == effective_match_revision,
                MyPhotoMatchModel.active.is_(True),
            )
            statement = (
                select(MyPhotoMatchModel, MyPhotoMediaAssetModel)
                .select_from(MyPhotoMediaAssetModel)
                .outerjoin(MyPhotoMatchModel, join_condition)
                .where(
                    MyPhotoMediaAssetModel.gallery_id == gallery.id,
                    MyPhotoMediaAssetModel.agency_id == claims.agency_id,
                    MyPhotoMediaAssetModel.group_id == trip.group.id,
                    MyPhotoMediaAssetModel.published_revision <= gallery.published_revision,
                    MyPhotoMediaAssetModel.processing_state != "removed",
                    MyPhotoMediaAssetModel.availability_state != "removed",
                )
            )
            if decoded is not None:
                statement = statement.where(
                    or_(
                        MyPhotoMediaAssetModel.sort_rank > decoded.sort_rank,
                        and_(
                            MyPhotoMediaAssetModel.sort_rank == decoded.sort_rank,
                            MyPhotoMediaAssetModel.id > decoded.asset_id,
                        ),
                    )
                )
            statement = statement.order_by(
                MyPhotoMediaAssetModel.sort_rank, MyPhotoMediaAssetModel.id
            ).limit(limit + 1)
            query_rows = list((await self._session.execute(statement)).tuples().all())
            total_count = int(
                (
                    await self._session.execute(
                        select(func.count(MyPhotoMediaAssetModel.id)).where(
                            MyPhotoMediaAssetModel.gallery_id == gallery.id,
                            MyPhotoMediaAssetModel.published_revision <= gallery.published_revision,
                            MyPhotoMediaAssetModel.processing_state != "removed",
                            MyPhotoMediaAssetModel.availability_state != "removed",
                        )
                    )
                ).scalar_one()
            )
        else:
            latest = await self._latest_search(identity.id, trip.group.id)
            if effective_match_revision is None and (latest is None or latest.status != "complete"):
                raise MyPhotosConflict(
                    "MY_PHOTOS_SEARCH_INCOMPLETE",
                    "Your photo search is not complete yet.",
                )
            statement = (
                select(MyPhotoMatchModel, MyPhotoMediaAssetModel)
                .join(
                    MyPhotoMediaAssetModel,
                    and_(
                        MyPhotoMediaAssetModel.id == MyPhotoMatchModel.media_asset_id,
                        MyPhotoMediaAssetModel.agency_id == MyPhotoMatchModel.agency_id,
                        MyPhotoMediaAssetModel.group_id == MyPhotoMatchModel.group_id,
                    ),
                )
                .where(
                    MyPhotoMatchModel.passenger_identity_id == identity.id,
                    MyPhotoMatchModel.agency_id == claims.agency_id,
                    MyPhotoMatchModel.group_id == trip.group.id,
                    MyPhotoMatchModel.gallery_revision == effective_match_revision,
                    MyPhotoMatchModel.active.is_(True),
                    MyPhotoMatchModel.display_tier == match_filter,
                    MyPhotoMediaAssetModel.availability_state != "removed",
                )
            )
            if decoded is not None:
                statement = statement.where(
                    or_(
                        MyPhotoMatchModel.sort_rank > decoded.sort_rank,
                        and_(
                            MyPhotoMatchModel.sort_rank == decoded.sort_rank,
                            MyPhotoMatchModel.media_asset_id > decoded.asset_id,
                        ),
                    )
                )
            statement = statement.order_by(
                MyPhotoMatchModel.sort_rank, MyPhotoMatchModel.media_asset_id
            ).limit(limit + 1)
            query_rows = list((await self._session.execute(statement)).tuples().all())
            total_count = int(
                (
                    await self._session.execute(
                        select(func.count(MyPhotoMatchModel.id)).where(
                            MyPhotoMatchModel.passenger_identity_id == identity.id,
                            MyPhotoMatchModel.group_id == trip.group.id,
                            MyPhotoMatchModel.gallery_revision == effective_match_revision,
                            MyPhotoMatchModel.active.is_(True),
                            MyPhotoMatchModel.display_tier == match_filter,
                            MyPhotoMatchModel.media_asset_id.in_(
                                select(MyPhotoMediaAssetModel.id).where(
                                    MyPhotoMediaAssetModel.gallery_id == gallery.id,
                                    MyPhotoMediaAssetModel.availability_state != "removed",
                                )
                            ),
                        )
                    )
                ).scalar_one()
            )
        has_more = len(query_rows) > limit
        page_rows = query_rows[:limit]
        page_variants = await self._delivery.latest_variants(
            [asset.id for _, asset in page_rows],
            agency_id=claims.agency_id,
            group_id=trip.group.id,
            variant_kinds=("thumbnail", "preview", "optimized"),
        )
        items = [
            self._delivery.photo_response(
                gallery=gallery,
                group_id=trip.group.id,
                account_cache_scope=hashlib.sha256(
                    f"{claims.account_id}|{self._settings.app_secret_key}".encode("utf-8")
                ).hexdigest()[:16],
                match=match,
                asset=asset,
                thumbnail_variant=page_variants.get((asset.id, "thumbnail")),
                preview_variant=page_variants.get((asset.id, "preview")),
                optimized_variant=page_variants.get((asset.id, "optimized")),
            )
            for match, asset in page_rows
        ]
        next_cursor = None
        if has_more and page_rows:
            last_match, last_asset = page_rows[-1]
            cursor_sort_rank = (
                last_asset.sort_rank
                if match_filter == "all"
                else last_match.sort_rank
                if last_match is not None
                else last_asset.sort_rank
            )
            next_cursor = self._cursor.encode(
                GalleryCursor(
                    passenger_id=identity.id,
                    group_id=trip.group.id,
                    revision=snapshot_revision,
                    match_filter=match_filter,
                    sort_rank=cursor_sort_rank,
                    asset_id=last_asset.id,
                )
            )
        return MyPhotosPhotoPageResponse(
            snapshot_revision=snapshot_revision,
            filter=match_filter,
            items=items,
            next_cursor=next_cursor,
            page_size=limit,
            total_count=total_count,
        )

    async def record_feedback(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        asset_id: uuid.UUID,
        request: MyPhotosFeedbackRequest,
    ) -> MyPhotosFeedbackResponse:
        identity = self._require_passenger(claims, trip)
        gallery = await self._ready_gallery(claims.agency_id, trip.group.id)
        match = (
            await self._session.execute(
                select(MyPhotoMatchModel)
                .where(
                    MyPhotoMatchModel.passenger_identity_id == identity.id,
                    MyPhotoMatchModel.media_asset_id == asset_id,
                    MyPhotoMatchModel.agency_id == claims.agency_id,
                    MyPhotoMatchModel.group_id == trip.group.id,
                    MyPhotoMatchModel.gallery_revision <= gallery.published_revision,
                    MyPhotoMatchModel.active.is_(True),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if match is None:
            raise EntityNotFoundError("My Photos match", asset_id)
        if match.feedback_idempotency_key == request.idempotency_key:
            if match.feedback != request.feedback:
                raise MyPhotosConflict(
                    "MY_PHOTOS_IDEMPOTENCY_CONFLICT",
                    "This request key was already used for different feedback.",
                )
        else:
            match.feedback = request.feedback
            match.feedback_idempotency_key = request.idempotency_key
            match.updated_at = datetime.now(tz=UTC)
            await self._session.flush()
            await record_my_photos_audit(
                self._session,
                action="my_photos_match_feedback",
                agency_id=claims.agency_id,
                group_id=trip.group.id,
                outcome=request.feedback,
                gallery_revision=match.gallery_revision,
                configuration_version=match.match_config_version,
            )
        if match.feedback not in {"this_is_me", "not_me"}:
            raise MyPhotosConflict(
                "MY_PHOTOS_FEEDBACK_INVALID",
                "Photo feedback could not be saved. Try again.",
            )
        return MyPhotosFeedbackResponse(
            asset_id=asset_id,
            feedback=match.feedback,
            updated_at=match.updated_at,
        )

    async def delete_enrollment(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        request: MyPhotosDeleteEnrollmentRequest,
    ) -> MyPhotosDeleteEnrollmentResponse:
        identity = self._require_passenger(claims, trip)
        await self._lock_passenger_identity(identity.id, claims.agency_id, trip.group.id)
        enrollment = await self._enrollment(identity.id, trip.group.id, for_update=True)
        now = datetime.now(tz=UTC)
        if enrollment is None:
            return MyPhotosDeleteEnrollmentResponse(
                enrollment_status="deleted",
                removed_search_data=request.scope == "enrollment_and_search_data",
                local_downloads_affected=False,
                provider_deletion_status="not_required",
                provider_deletion_retryable=False,
                deleted_at=now,
            )
        deletion_created = False
        if enrollment.deletion_idempotency_key is not None:
            if enrollment.deletion_idempotency_key != request.idempotency_key:
                raise MyPhotosConflict(
                    "MY_PHOTOS_ENROLLMENT_ALREADY_DELETED",
                    "Face Scan enrollment has already been deleted.",
                )
            if enrollment.deletion_scope != request.scope:
                raise MyPhotosConflict(
                    "MY_PHOTOS_IDEMPOTENCY_CONFLICT",
                    "This request key was already used for a different deletion scope.",
                )
            if enrollment.provider_deletion_status in {
                "not_required",
                "complete",
            } and enrollment.superseded_reference_deletion_status not in {"pending", "failed"}:
                return self._deletion_response(enrollment)
        else:
            deletion_created = True
            active_search_ids = select(MyPhotoSearchRunModel.id).where(
                MyPhotoSearchRunModel.passenger_identity_id == identity.id,
                MyPhotoSearchRunModel.agency_id == claims.agency_id,
                MyPhotoSearchRunModel.group_id == trip.group.id,
                MyPhotoSearchRunModel.status.in_(("queued", "searching")),
            )
            await self._session.execute(
                update(MyPhotoJobModel)
                .where(
                    MyPhotoJobModel.search_run_id.in_(active_search_ids),
                    MyPhotoJobModel.status.in_(("queued", "running", "retrying")),
                )
                .values(cancellation_requested_at=now)
            )
            await self._session.execute(
                update(MyPhotoSearchRunModel)
                .where(MyPhotoSearchRunModel.id.in_(active_search_ids))
                .values(
                    status="cancelled",
                    completed_at=now,
                    heartbeat_at=now,
                    lease_owner=None,
                    lease_expires_at=None,
                    stable_error_code="CANCELLED_BY_REQUEST",
                )
            )
            if request.scope == "enrollment_and_search_data":
                search_ids = select(MyPhotoSearchRunModel.id).where(
                    MyPhotoSearchRunModel.passenger_identity_id == identity.id,
                    MyPhotoSearchRunModel.agency_id == claims.agency_id,
                    MyPhotoSearchRunModel.group_id == trip.group.id,
                )
                await self._session.execute(
                    delete(MyPhotoMatchModel).where(
                        MyPhotoMatchModel.passenger_identity_id == identity.id,
                        MyPhotoMatchModel.group_id == trip.group.id,
                    )
                )
                await self._session.execute(
                    delete(MyPhotoJobModel).where(MyPhotoJobModel.search_run_id.in_(search_ids))
                )
                await self._session.execute(
                    delete(MyPhotoSearchRunModel).where(
                        MyPhotoSearchRunModel.passenger_identity_id == identity.id,
                        MyPhotoSearchRunModel.group_id == trip.group.id,
                    )
                )
            await self._session.execute(
                delete(MyPhotoLivenessSessionModel).where(
                    MyPhotoLivenessSessionModel.enrollment_id == enrollment.id
                )
            )
            enrollment.status = "deleted"
            enrollment.deleted_at = now
            enrollment.deletion_idempotency_key = request.idempotency_key
            enrollment.deletion_scope = request.scope
            if enrollment.attempt_count >= enrollment.max_attempts and (
                enrollment.cooldown_until is None or _as_utc(enrollment.cooldown_until) <= now
            ):
                enrollment.cooldown_until = now + timedelta(
                    seconds=self._settings.my_photos.liveness_cooldown_seconds
                )
            if enrollment.provider_reference_handle is None:
                enrollment.provider_name = None
                enrollment.provider_deletion_status = "not_required"
                enrollment.provider_deletion_error_code = None
                enrollment.provider_deletion_requested_at = None
                enrollment.provider_deletion_completed_at = None
                enrollment.provider_deletion_attempt_count = 0
                enrollment.provider_deletion_next_attempt_at = None
                enrollment.provider_deletion_last_attempt_at = None
            else:
                enrollment.provider_deletion_status = "pending"
                enrollment.provider_deletion_error_code = None
                enrollment.provider_deletion_requested_at = now
                enrollment.provider_deletion_completed_at = None
                enrollment.provider_deletion_attempt_count = 0
                enrollment.provider_deletion_next_attempt_at = now
                enrollment.provider_deletion_last_attempt_at = None
        await self._session.flush()
        if deletion_created:
            await record_my_photos_audit(
                self._session,
                action="my_photos_enrollment_deleted",
                agency_id=claims.agency_id,
                group_id=trip.group.id,
                outcome=enrollment.provider_deletion_status,
            )
        if (
            enrollment.provider_deletion_status == "not_required"
            and enrollment.superseded_reference_deletion_status not in {"pending", "failed"}
        ):
            return self._deletion_response(enrollment)

        # Persist the user's deletion request before provider I/O. A process
        # interruption therefore leaves a retryable, auditable pending state.
        await self._session.commit()
        if enrollment.superseded_reference_deletion_status in {"pending", "failed"}:
            enrollment = await self._delete_superseded_reference(
                enrollment=enrollment,
                passenger_identity_id=identity.id,
            )
        if enrollment.provider_deletion_status in {"not_required", "complete"}:
            return self._deletion_response(enrollment)
        provider_reference = enrollment.provider_reference_handle
        if provider_reference is None:
            return self._deletion_response(enrollment)
        try:
            async with asyncio.timeout(self._settings.my_photos.liveness_provider_timeout_seconds):
                deletion_result = await self._providers.liveness.delete_reference(
                    ReferenceDeletionRequest(
                        tenant_scope=str(claims.agency_id),
                        group_scope=str(trip.group.id),
                        passenger_scope=str(identity.id),
                        provider_reference=provider_reference,
                        deletion_identity=request.idempotency_key,
                    )
                )
            if deletion_result.outcome not in {"deleted", "not_found"}:
                raise ValueError("Invalid provider deletion result")
        except MyPhotosUnavailable as exc:
            await self._mark_provider_deletion_pending(
                enrollment.id,
                request.idempotency_key,
                request.scope,
                self._stable_error_code(exc.code),
            )
            refreshed = await self._enrollment(identity.id, trip.group.id)
            if refreshed is None:
                raise MyPhotosConflict(
                    "MY_PHOTOS_ENROLLMENT_CHANGED",
                    "Face Scan deletion state changed. Refresh My Photos.",
                )
            return self._deletion_response(refreshed)
        except Exception:
            await self._mark_provider_deletion_pending(
                enrollment.id,
                request.idempotency_key,
                request.scope,
                "PROVIDER_DELETION_UNAVAILABLE",
            )
            refreshed = await self._enrollment(identity.id, trip.group.id)
            if refreshed is None:
                raise MyPhotosConflict(
                    "MY_PHOTOS_ENROLLMENT_CHANGED",
                    "Face Scan deletion state changed. Refresh My Photos.",
                )
            return self._deletion_response(refreshed)

        refreshed = await self._complete_provider_deletion(
            enrollment.id,
            request.idempotency_key,
            request.scope,
            provider_reference,
        )
        return self._deletion_response(refreshed)

    async def prepare_media(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        asset_id: uuid.UUID,
        request: MyPhotosPrepareRequest,
    ) -> MyPhotosPrepareResponse:
        return await self._delivery.prepare_media(
            claims=claims, trip=trip, asset_id=asset_id, request=request
        )

    async def authorize_downloads(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        request: MyPhotosDownloadAuthorizationRequest,
    ) -> MyPhotosDownloadAuthorizationResponse:
        return await self._delivery.authorize_downloads(claims=claims, trip=trip, request=request)

    async def download_plan(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
    ) -> MyPhotosDownloadPlanResponse:
        return await self._delivery.download_plan(claims=claims, trip=trip)

    async def development_download_content(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        authorization_id: uuid.UUID,
    ) -> tuple[bytes, str, str]:
        return await self._delivery.development_download_content(
            claims=claims, trip=trip, authorization_id=authorization_id
        )

    async def production_download_location(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        authorization_id: uuid.UUID,
    ) -> DeliveryResolution:
        return await self._delivery.production_download_location(
            claims=claims,
            trip=trip,
            authorization_id=authorization_id,
        )

    async def download_content_or_location(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        authorization_id: uuid.UUID,
    ) -> tuple[bytes, str, str] | DeliveryResolution:
        if self._providers.provider_name == "aws":
            return await self.production_download_location(
                claims=claims,
                trip=trip,
                authorization_id=authorization_id,
            )
        return await self.development_download_content(
            claims=claims,
            trip=trip,
            authorization_id=authorization_id,
        )

    async def development_preview_content(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        asset_id: uuid.UUID,
        variant: str,
    ) -> tuple[bytes, str]:
        return await self._delivery.development_preview_content(
            claims=claims, trip=trip, asset_id=asset_id, variant=variant
        )

    async def preview_content_or_location(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        asset_id: uuid.UUID,
        variant: Literal["thumbnail", "preview"],
    ) -> tuple[bytes, str] | DeliveryResolution:
        return await self._delivery.preview_content_or_location(
            claims=claims,
            trip=trip,
            asset_id=asset_id,
            variant=variant,
        )

    def _deletion_response(
        self,
        enrollment: MyPhotoEnrollmentModel,
    ) -> MyPhotosDeleteEnrollmentResponse:
        current_status = enrollment.provider_deletion_status
        superseded_status = enrollment.superseded_reference_deletion_status
        if "failed" in {current_status, superseded_status}:
            deletion_status = "failed"
        elif "pending" in {current_status, superseded_status}:
            deletion_status = "pending"
        elif "complete" in {current_status, superseded_status}:
            deletion_status = "complete"
        else:
            deletion_status = "not_required"
        current_retryable = current_status == "pending" or (
            current_status == "failed"
            and enrollment.provider_deletion_attempt_count
            < self._settings.my_photos.provider_deletion_max_attempts
        )
        superseded_retryable = superseded_status == "pending" or (
            superseded_status == "failed"
            and enrollment.superseded_deletion_attempt_count
            < self._settings.my_photos.provider_deletion_max_attempts
        )
        return MyPhotosDeleteEnrollmentResponse(
            enrollment_status="deleted",
            removed_search_data=enrollment.deletion_scope == "enrollment_and_search_data",
            local_downloads_affected=False,
            provider_deletion_status=cast(
                "Literal['not_required', 'pending', 'complete', 'failed']",
                deletion_status,
            ),
            provider_deletion_retryable=current_retryable or superseded_retryable,
            deleted_at=enrollment.deleted_at or datetime.now(tz=UTC),
        )

    async def _mark_provider_deletion_pending(
        self,
        enrollment_id: uuid.UUID,
        idempotency_key: str,
        deletion_scope: str,
        error_code: str,
    ) -> None:
        enrollment = (
            await self._session.execute(
                select(MyPhotoEnrollmentModel)
                .where(
                    MyPhotoEnrollmentModel.id == enrollment_id,
                    MyPhotoEnrollmentModel.status == "deleted",
                    MyPhotoEnrollmentModel.deletion_idempotency_key == idempotency_key,
                    MyPhotoEnrollmentModel.deletion_scope == deletion_scope,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if enrollment is None:
            return
        now = datetime.now(tz=UTC)
        enrollment.provider_deletion_attempt_count = min(
            enrollment.provider_deletion_attempt_count + 1,
            self._settings.my_photos.provider_deletion_max_attempts,
        )
        enrollment.provider_deletion_last_attempt_at = now
        exhausted = (
            enrollment.provider_deletion_attempt_count
            >= self._settings.my_photos.provider_deletion_max_attempts
        )
        enrollment.provider_deletion_status = "failed" if exhausted else "pending"
        enrollment.provider_deletion_error_code = error_code
        enrollment.provider_deletion_completed_at = None
        enrollment.provider_deletion_next_attempt_at = (
            None
            if exhausted
            else now + timedelta(seconds=self._settings.my_photos.job_retry_base_seconds)
        )
        await self._session.flush()
        await record_my_photos_audit(
            self._session,
            action="my_photos_provider_deletion",
            agency_id=enrollment.agency_id,
            group_id=enrollment.group_id,
            outcome="pending",
        )

    async def _delete_superseded_reference(
        self,
        *,
        enrollment: MyPhotoEnrollmentModel,
        passenger_identity_id: uuid.UUID,
    ) -> MyPhotoEnrollmentModel:
        provider_reference = enrollment.superseded_provider_reference_handle
        if provider_reference is None:
            return enrollment
        deletion_identity = f"supersede:{enrollment.id}:{max(enrollment.reference_version - 1, 0)}"
        # The new active reference and the pending cleanup marker must survive
        # a crash before the remote deletion completes.
        await self._session.commit()
        try:
            async with asyncio.timeout(self._settings.my_photos.liveness_provider_timeout_seconds):
                deletion_result = await self._providers.liveness.delete_reference(
                    ReferenceDeletionRequest(
                        tenant_scope=str(enrollment.agency_id),
                        group_scope=str(enrollment.group_id),
                        passenger_scope=str(passenger_identity_id),
                        provider_reference=provider_reference,
                        deletion_identity=deletion_identity,
                    )
                )
            if deletion_result.outcome not in {"deleted", "not_found"}:
                raise ValueError("Invalid provider deletion result")
            deletion_complete = True
            error_code = None
        except MyPhotosUnavailable as exc:
            deletion_complete = False
            error_code = self._stable_error_code(exc.code)
        except Exception:
            deletion_complete = False
            error_code = "PROVIDER_DELETION_UNAVAILABLE"

        refreshed = (
            await self._session.execute(
                select(MyPhotoEnrollmentModel)
                .where(MyPhotoEnrollmentModel.id == enrollment.id)
                .with_for_update()
            )
        ).scalar_one()
        if refreshed.superseded_provider_reference_handle != provider_reference:
            return refreshed
        if deletion_complete:
            refreshed.superseded_provider_reference_handle = None
            refreshed.superseded_reference_deletion_status = "complete"
            refreshed.superseded_reference_deletion_error_code = None
            refreshed.superseded_reference_deletion_completed_at = datetime.now(tz=UTC)
            refreshed.superseded_deletion_attempt_count = 0
            refreshed.superseded_deletion_next_attempt_at = None
        else:
            refreshed.superseded_deletion_attempt_count = min(
                refreshed.superseded_deletion_attempt_count + 1,
                self._settings.my_photos.provider_deletion_max_attempts,
            )
            failed_at = datetime.now(tz=UTC)
            exhausted = (
                refreshed.superseded_deletion_attempt_count
                >= self._settings.my_photos.provider_deletion_max_attempts
            )
            refreshed.superseded_reference_deletion_status = "failed" if exhausted else "pending"
            refreshed.superseded_reference_deletion_error_code = error_code
            refreshed.superseded_deletion_last_attempt_at = failed_at
            refreshed.superseded_deletion_next_attempt_at = (
                None
                if exhausted
                else failed_at + timedelta(seconds=self._settings.my_photos.job_retry_base_seconds)
            )
        await self._session.flush()
        await record_my_photos_audit(
            self._session,
            action="my_photos_provider_deletion",
            agency_id=refreshed.agency_id,
            group_id=refreshed.group_id,
            outcome="superseded_complete" if deletion_complete else "superseded_pending",
        )
        # Release the enrollment lock before any caller performs another
        # provider operation (for example deleting the current reference too).
        await self._session.commit()
        return refreshed

    async def _complete_provider_deletion(
        self,
        enrollment_id: uuid.UUID,
        idempotency_key: str,
        deletion_scope: str,
        provider_reference: str,
    ) -> MyPhotoEnrollmentModel:
        enrollment = (
            await self._session.execute(
                select(MyPhotoEnrollmentModel)
                .where(
                    MyPhotoEnrollmentModel.id == enrollment_id,
                    MyPhotoEnrollmentModel.status == "deleted",
                    MyPhotoEnrollmentModel.deletion_idempotency_key == idempotency_key,
                    MyPhotoEnrollmentModel.deletion_scope == deletion_scope,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if enrollment is None:
            raise MyPhotosConflict(
                "MY_PHOTOS_ENROLLMENT_CHANGED",
                "Face Scan deletion state changed. Refresh My Photos.",
            )
        if enrollment.provider_reference_handle not in {None, provider_reference}:
            raise MyPhotosConflict(
                "MY_PHOTOS_ENROLLMENT_CHANGED",
                "Face Scan deletion state changed. Refresh My Photos.",
            )
        enrollment.provider_name = None
        enrollment.provider_reference_handle = None
        enrollment.provider_deletion_status = "complete"
        enrollment.provider_deletion_error_code = None
        enrollment.provider_deletion_completed_at = datetime.now(tz=UTC)
        enrollment.provider_deletion_next_attempt_at = None
        await self._session.flush()
        await record_my_photos_audit(
            self._session,
            action="my_photos_provider_deletion",
            agency_id=enrollment.agency_id,
            group_id=enrollment.group_id,
            outcome="complete",
        )
        return enrollment

    @staticmethod
    def _stable_error_code(value: str) -> str:
        normalized = "".join(
            character if character.isascii() and (character.isalnum() or character == "_") else "_"
            for character in value.upper()
        ).strip("_")
        return (normalized or "PROVIDER_DELETION_UNAVAILABLE")[:64]

    async def _gallery(
        self, agency_id: uuid.UUID, group_id: uuid.UUID
    ) -> MyPhotoGalleryModel | None:
        return (
            await self._session.execute(
                select(MyPhotoGalleryModel).where(
                    MyPhotoGalleryModel.agency_id == agency_id,
                    MyPhotoGalleryModel.group_id == group_id,
                )
            )
        ).scalar_one_or_none()

    async def _ready_gallery(
        self, agency_id: uuid.UUID, group_id: uuid.UUID
    ) -> MyPhotoGalleryModel:
        gallery = await self._gallery(agency_id, group_id)
        if gallery is None or not gallery.feature_enabled:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_FEATURE_UNAVAILABLE", "My Photos is not available for this trip."
            )
        window_state = self._gallery_window_state(gallery, datetime.now(tz=UTC))
        if window_state == "not_started":
            raise MyPhotosUnavailable(
                "MY_PHOTOS_NOT_AVAILABLE_YET", "My Photos is not available for this trip yet."
            )
        if window_state == "expired":
            raise MyPhotosUnavailable(
                "MY_PHOTOS_ACCESS_EXPIRED", "Access to this trip's My Photos gallery has expired."
            )
        if gallery.status != "ready":
            raise MyPhotosUnavailable(
                "MY_PHOTOS_GALLERY_NOT_READY", "This trip's gallery is not ready yet."
            )
        return gallery

    @staticmethod
    def _gallery_window_state(gallery: MyPhotoGalleryModel | None, now: datetime) -> str:
        if gallery is None:
            return "not_started"
        if gallery.availability_starts_at is not None and now < _as_utc(
            gallery.availability_starts_at
        ):
            return "not_started"
        # The end instant is exclusive: authorizations and reads fail closed at
        # exactly availability_ends_at, not one request later.
        if gallery.availability_ends_at is not None and now >= _as_utc(
            gallery.availability_ends_at
        ):
            return "expired"
        return "active"

    async def _enrollment(
        self,
        passenger_identity_id: uuid.UUID,
        group_id: uuid.UUID,
        *,
        for_update: bool = False,
    ) -> MyPhotoEnrollmentModel | None:
        statement = select(MyPhotoEnrollmentModel).where(
            MyPhotoEnrollmentModel.passenger_identity_id == passenger_identity_id,
            MyPhotoEnrollmentModel.group_id == group_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def _lock_passenger_identity(
        self,
        passenger_identity_id: uuid.UUID,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
    ) -> None:
        """Serialize first-write idempotent mutations on an existing parent row."""

        locked_id = (
            await self._session.execute(
                select(MobilePassengerIdentityModel.id)
                .where(
                    MobilePassengerIdentityModel.id == passenger_identity_id,
                    MobilePassengerIdentityModel.agency_id == agency_id,
                    MobilePassengerIdentityModel.group_id == group_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if locked_id is None:
            raise AuthorizationError("Passenger resource is not available")

    def _apply_liveness_cooldown(self, enrollment: MyPhotoEnrollmentModel, now: datetime) -> None:
        if enrollment.status != "rejected":
            return
        if enrollment.attempt_count >= enrollment.max_attempts:
            enrollment.status = "cooldown"
            enrollment.cooldown_until = now + timedelta(
                seconds=self._settings.my_photos.liveness_cooldown_seconds
            )

    async def _finalize_liveness_result(
        self,
        *,
        identity_id: uuid.UUID,
        gallery: MyPhotoGalleryModel,
        session_id: uuid.UUID,
        idempotency_key: str,
        provider_session_reference: str,
        provider_claim_token: str,
        result: LivenessResult,
    ) -> tuple[
        MyPhotoLivenessSessionModel,
        MyPhotoEnrollmentModel,
        MyPhotoSearchRunModel | None,
    ]:
        await self._lock_passenger_identity(identity_id, gallery.agency_id, gallery.group_id)
        liveness = (
            await self._session.execute(
                select(MyPhotoLivenessSessionModel)
                .where(
                    MyPhotoLivenessSessionModel.id == session_id,
                    MyPhotoLivenessSessionModel.agency_id == gallery.agency_id,
                    MyPhotoLivenessSessionModel.group_id == gallery.group_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if liveness is None:
            raise EntityNotFoundError("Face Scan session", session_id)
        enrollment = (
            await self._session.execute(
                select(MyPhotoEnrollmentModel)
                .where(
                    MyPhotoEnrollmentModel.id == liveness.enrollment_id,
                    MyPhotoEnrollmentModel.passenger_identity_id == identity_id,
                    MyPhotoEnrollmentModel.agency_id == gallery.agency_id,
                    MyPhotoEnrollmentModel.group_id == gallery.group_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if enrollment is None:
            raise AuthorizationError("Passenger Face Scan enrollment is not available")
        if (
            liveness.completion_idempotency_key != idempotency_key
            or liveness.completion_outcome != "completed"
            or liveness.provider_session_reference != provider_session_reference
            or liveness.provider_claim_token != provider_claim_token
        ):
            raise MyPhotosConflict(
                "MY_PHOTOS_SESSION_CHANGED", "Face Scan session changed. Start again."
            )
        if liveness.status != "running":
            existing_search = await self._latest_search(identity_id, gallery.group_id)
            return liveness, enrollment, existing_search

        now = datetime.now(tz=UTC)
        liveness.provider_claim_token = None
        liveness.provider_claim_expires_at = None
        liveness.native_launch_handle = None
        liveness.consumed_at = now
        liveness.result_retryable = result.retryable
        search: MyPhotoSearchRunModel | None = None
        if result.outcome == "passed" and result.reference_face_handle is not None:
            liveness.status = "completed"
            liveness.stable_error_code = None
            if (
                enrollment.provider_reference_handle is not None
                and enrollment.provider_reference_handle != result.reference_face_handle
            ):
                enrollment.superseded_provider_reference_handle = (
                    enrollment.provider_reference_handle
                )
                enrollment.superseded_reference_deletion_status = "pending"
                enrollment.superseded_reference_deletion_error_code = None
                enrollment.superseded_reference_deletion_requested_at = now
                enrollment.superseded_reference_deletion_completed_at = None
                enrollment.superseded_deletion_attempt_count = 0
                enrollment.superseded_deletion_next_attempt_at = now
                enrollment.superseded_deletion_last_attempt_at = None
            enrollment.status = "enrolled"
            enrollment.provider_name = self._providers.provider_name
            enrollment.provider_reference_handle = result.reference_face_handle
            enrollment.reference_version += 1
            enrollment.enrolled_at = enrollment.enrolled_at or now
            enrollment.refreshed_at = now
            enrollment.attempt_count = 0
            enrollment.cooldown_until = None
            search = await self._create_search_run(
                enrollment=enrollment,
                gallery=gallery,
                passenger_identity_id=identity_id,
                liveness_session_id=liveness.id,
            )
        else:
            liveness.status = (
                "expired"
                if result.outcome == "expired"
                else "rejected"
                if result.outcome in {"rejected", "no_face", "multiple_faces"}
                else "failed"
            )
            liveness.stable_error_code = self._stable_error_code(
                result.stable_error_code or "LIVENESS_FAILED"
            )
            enrollment.status = (
                "enrolled" if enrollment.provider_reference_handle is not None else "rejected"
            )
            self._apply_liveness_cooldown(enrollment, now)
        await self._session.flush()
        await record_my_photos_audit(
            self._session,
            action="my_photos_enrollment_completed",
            agency_id=gallery.agency_id,
            group_id=gallery.group_id,
            outcome="enrolled" if enrollment.status == "enrolled" else liveness.status,
            gallery_revision=gallery.published_revision,
            configuration_version=self._settings.my_photos.match_config_version,
        )
        return liveness, enrollment, search

    async def _fail_liveness_creation(
        self,
        session_id: uuid.UUID,
        enrollment_id: uuid.UUID,
        provider_claim_token: str,
        error_code: str,
    ) -> None:
        liveness = (
            await self._session.execute(
                select(MyPhotoLivenessSessionModel)
                .where(
                    MyPhotoLivenessSessionModel.id == session_id,
                    MyPhotoLivenessSessionModel.enrollment_id == enrollment_id,
                    MyPhotoLivenessSessionModel.status == "creating",
                    MyPhotoLivenessSessionModel.provider_claim_token == provider_claim_token,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if liveness is None:
            return
        enrollment = (
            await self._session.execute(
                select(MyPhotoEnrollmentModel)
                .where(MyPhotoEnrollmentModel.id == enrollment_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        now = datetime.now(tz=UTC)
        liveness.status = "failed"
        liveness.provider_claim_token = None
        liveness.provider_claim_expires_at = None
        liveness.native_launch_handle = None
        liveness.stable_error_code = self._stable_error_code(error_code)
        liveness.result_retryable = True
        liveness.consumed_at = now
        if enrollment is not None:
            # Provider session creation never presented a usable challenge, so
            # it must not consume a passenger attempt. Preserve a prior valid
            # enrollment when an optional refresh fails before launch.
            enrollment.attempt_count = max(0, enrollment.attempt_count - 1)
            enrollment.cooldown_until = None
            enrollment.status = (
                "enrolled" if enrollment.provider_reference_handle is not None else "ready"
            )
        await self._session.flush()

    async def _complete_liveness_creation(
        self,
        session_id: uuid.UUID,
        enrollment_id: uuid.UUID,
        idempotency_key: str,
        provider_claim_token: str,
        provider_reference: str,
        provider_expires_at: datetime,
        native_launch_handle: str | None,
    ) -> MyPhotoLivenessSessionModel:
        liveness = (
            await self._session.execute(
                select(MyPhotoLivenessSessionModel)
                .where(
                    MyPhotoLivenessSessionModel.id == session_id,
                    MyPhotoLivenessSessionModel.enrollment_id == enrollment_id,
                    MyPhotoLivenessSessionModel.idempotency_key == idempotency_key,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if liveness is None:
            raise MyPhotosConflict(
                "MY_PHOTOS_SESSION_CHANGED", "Face Scan session changed. Start again."
            )
        if liveness.status == "created" and liveness.provider_session_reference is not None:
            return liveness
        if liveness.status != "creating" or liveness.provider_claim_token != provider_claim_token:
            raise MyPhotosConflict(
                "MY_PHOTOS_SESSION_CHANGED", "Face Scan session changed. Start again."
            )
        now = datetime.now(tz=UTC)
        expires_at = min(_as_utc(liveness.expires_at), _as_utc(provider_expires_at))
        if expires_at <= now:
            await self._fail_liveness_creation(
                session_id,
                enrollment_id,
                provider_claim_token,
                "MY_PHOTOS_SESSION_EXPIRED",
            )
            raise MyPhotosConflict(
                "MY_PHOTOS_SESSION_EXPIRED", "Face Scan session expired. Start again."
            )
        liveness.provider_session_reference = provider_reference
        liveness.native_launch_handle = native_launch_handle
        liveness.provider_claim_token = None
        liveness.provider_claim_expires_at = None
        liveness.expires_at = expires_at
        liveness.status = "created"
        await self._session.flush()
        return liveness

    async def _release_liveness_result_claim(
        self,
        session_id: uuid.UUID,
        provider_claim_token: str,
    ) -> None:
        """Release only this caller's claim after a sanitized provider failure."""

        liveness = (
            await self._session.execute(
                select(MyPhotoLivenessSessionModel)
                .where(
                    MyPhotoLivenessSessionModel.id == session_id,
                    MyPhotoLivenessSessionModel.status == "running",
                    MyPhotoLivenessSessionModel.provider_claim_token == provider_claim_token,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if liveness is None:
            return
        liveness.provider_claim_token = None
        liveness.provider_claim_expires_at = None
        await self._session.flush()
        await self._session.commit()

    async def _required_current_enrollment(
        self, passenger_identity_id: uuid.UUID, group_id: uuid.UUID
    ) -> MyPhotoEnrollmentModel:
        enrollment = await self._enrollment(passenger_identity_id, group_id, for_update=True)
        if enrollment is None or enrollment.status in {"revoked", "deleted"}:
            raise MyPhotosConflict(
                "MY_PHOTOS_CONSENT_REQUIRED", "Accept the current Face Scan consent first."
            )
        if enrollment.consent_version != self._settings.my_photos.consent_version:
            raise MyPhotosConflict(
                "MY_PHOTOS_CONSENT_VERSION_REQUIRED",
                "Review and accept the current Face Scan consent first.",
            )
        now = datetime.now(tz=UTC)
        if (
            enrollment.status == "cooldown"
            and enrollment.cooldown_until is not None
            and _as_utc(enrollment.cooldown_until) <= now
        ):
            enrollment.status = "ready"
            enrollment.attempt_count = 0
            enrollment.cooldown_until = None
        return enrollment

    async def _latest_search(
        self, passenger_identity_id: uuid.UUID, group_id: uuid.UUID
    ) -> MyPhotoSearchRunModel | None:
        return (
            await self._session.execute(
                select(MyPhotoSearchRunModel)
                .where(
                    MyPhotoSearchRunModel.passenger_identity_id == passenger_identity_id,
                    MyPhotoSearchRunModel.group_id == group_id,
                )
                .order_by(MyPhotoSearchRunModel.created_at.desc(), MyPhotoSearchRunModel.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def _search_by_id(self, search_id: uuid.UUID) -> MyPhotoSearchRunModel | None:
        return (
            await self._session.execute(
                select(MyPhotoSearchRunModel).where(MyPhotoSearchRunModel.id == search_id)
            )
        ).scalar_one_or_none()

    async def _search_job(self, search_id: uuid.UUID) -> MyPhotoJobModel | None:
        return (
            await self._session.execute(
                select(MyPhotoJobModel).where(
                    MyPhotoJobModel.search_run_id == search_id,
                    MyPhotoJobModel.job_type == "search_passenger",
                )
            )
        ).scalar_one_or_none()

    async def _fail_search(
        self,
        search: MyPhotoSearchRunModel,
        job: MyPhotoJobModel | None,
        error_code: str,
    ) -> None:
        now = datetime.now(tz=UTC)
        search.status = "failed"
        search.stable_error_code = error_code.upper()[:64]
        search.completed_at = now
        search.lease_owner = None
        search.lease_expires_at = None
        if job is not None:
            job.status = "failed"
            job.stable_error_code = search.stable_error_code
            job.error_detail = "Search stopped with a retry-safe provider category."
            job.completed_at = now
            job.lease_owner = None
            job.lease_expires_at = None
        await self._session.flush()

    def _search_response(
        self, search: MyPhotoSearchRunModel | None
    ) -> MyPhotosSearchRunResponse | None:
        if search is None:
            return None
        progress = (
            100
            if search.status == "complete"
            else int((search.processed_face_count / search.total_face_count) * 100)
            if search.total_face_count > 0
            else 0
        )
        return MyPhotosSearchRunResponse(
            id=search.id,
            status=search.status,  # type: ignore[arg-type]
            processed_face_count=search.processed_face_count,
            total_face_count=search.total_face_count,
            progress_percent=progress,
            matched_photo_count=search.matched_asset_count,
            best_match_count=search.best_match_count,
            possible_match_count=search.possible_match_count,
            started_at=search.started_at,
            completed_at=search.completed_at,
            error_code=search.stable_error_code,
        )

    def _liveness_session_response(
        self,
        session: MyPhotoLivenessSessionModel,
        enrollment: MyPhotoEnrollmentModel,
    ) -> MyPhotosLivenessSessionResponse:
        flow = self._providers.liveness.client_flow
        if flow == "unavailable":
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_NOT_CONFIGURED", "Face Scan is not available yet."
            )
        return MyPhotosLivenessSessionResponse(
            session_id=session.id,
            status="created",
            challenge_mode=session.challenge_mode,  # type: ignore[arg-type]
            client_flow=flow,
            native_launch_handle=(session.native_launch_handle if flow == "native" else None),
            expires_at=session.expires_at,
            attempts_remaining=max(enrollment.max_attempts - enrollment.attempt_count, 0),
            photosensitivity_warning=(
                "The movement-and-light challenge uses changing screen colors. Choose the "
                "movement-only alternative if you may be photosensitive."
            ),
        )

    def _completion_response(
        self,
        session: MyPhotoLivenessSessionModel,
        enrollment: MyPhotoEnrollmentModel,
        search: MyPhotoSearchRunModel | None,
    ) -> MyPhotosLivenessCompleteResponse:
        return MyPhotosLivenessCompleteResponse(
            session_id=session.id,
            session_status=session.status,  # type: ignore[arg-type]
            enrollment_status=enrollment.status,  # type: ignore[arg-type]
            search_run_id=search.id if search is not None else None,
            search_status="queued" if search is not None else "not_started",
            retryable=bool(session.result_retryable),
            error_code=session.stable_error_code,
            cooldown_until=enrollment.cooldown_until,
        )

    def _require_face_providers(self) -> None:
        if not self._providers.liveness.ready or not self._providers.face_search.ready:
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_NOT_CONFIGURED", "Face Scan is not available yet."
            )

    @staticmethod
    def _require_passenger(
        claims: MobileAccessClaims, trip: AuthorizedMobileTrip
    ) -> MobilePassengerIdentityModel:
        if claims.principal_type != "passenger" or trip.passenger_identity is None:
            raise AuthorizationError("My Photos is available only to the signed-in passenger")
        if trip.passenger_identity.id != claims.principal_id:
            raise AuthorizationError("Passenger resource is not available")
        return trip.passenger_identity
