"""Provider-await orchestration for single-use passenger Face Scan sessions."""

from __future__ import annotations

import asyncio
import math
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.application.my_photos.errors import (
    MyPhotosConflict,
    MyPhotosRateLimited,
    MyPhotosUnavailable,
)
from app.application.my_photos.providers import (
    LivenessSessionRequest,
)
from app.application.security.mobile_access_policy import AuthorizedMobileTrip
from app.core.security.mobile_jwt import MobileAccessClaims
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.infrastructure.database.my_photos_models import (
    MyPhotoLivenessSessionModel,
)
from app.infrastructure.my_photos.context import MyPhotosContext
from app.infrastructure.my_photos.liveness_store import MyPhotosLivenessStore
from app.infrastructure.my_photos.liveness_validation import (
    _as_utc,
    _liveness_processing,
    _provider_claim_active,
    _validated_liveness_result,
    _validated_liveness_session_handle,
)
from app.infrastructure.my_photos.reference_lifecycle import MyPhotosReferenceLifecycle
from app.infrastructure.my_photos.responses import _completion_response
from app.infrastructure.my_photos.telemetry import my_photos_metrics
from app.presentation.api.v1.schemas.my_photos_schemas import (
    MyPhotosLivenessCompleteRequest,
    MyPhotosLivenessCompleteResponse,
    MyPhotosLivenessSessionResponse,
    MyPhotosLivenessStartRequest,
)


class MyPhotosLivenessService:
    def __init__(
        self,
        context: MyPhotosContext,
        *,
        state: MyPhotosLivenessStore,
        references: MyPhotosReferenceLifecycle,
    ) -> None:
        self._context = context
        self._state = state
        self._references = references

    async def start_liveness(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        request: MyPhotosLivenessStartRequest,
    ) -> MyPhotosLivenessSessionResponse:
        identity = self._context._require_passenger(claims, trip)
        await self._context._ready_gallery(claims.agency_id, trip.group.id)
        self._context._require_face_providers()
        await self._context._lock_passenger_identity(identity.id, claims.agency_id, trip.group.id)
        enrollment = await self._context._required_current_enrollment(identity.id, trip.group.id)
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
            await self._context.session.execute(
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
                    seconds=self._context.settings.my_photos.liveness_cooldown_seconds
                )
                raise MyPhotosRateLimited(
                    self._context.settings.my_photos.liveness_cooldown_seconds
                )
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
            await self._context.session.execute(
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
                return self._state._liveness_session_response(existing, enrollment)
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
                    seconds=self._context.settings.my_photos.liveness_cooldown_seconds
                )
                raise MyPhotosRateLimited(
                    self._context.settings.my_photos.liveness_cooldown_seconds
                )
            liveness = MyPhotoLivenessSessionModel(
                id=uuid.uuid4(),
                enrollment_id=enrollment.id,
                agency_id=claims.agency_id,
                group_id=trip.group.id,
                idempotency_key=request.idempotency_key,
                challenge_mode=request.challenge_mode,
                status="creating",
                provider_name=self._context.providers.provider_name,
                provider_session_reference=None,
                provider_claim_token=claim_token,
                provider_claim_expires_at=now
                + timedelta(
                    seconds=self._context.settings.my_photos.liveness_provider_claim_seconds
                ),
                expires_at=now
                + timedelta(seconds=self._context.settings.my_photos.liveness_session_ttl_seconds),
            )
            self._context.session.add(liveness)
            enrollment.attempt_count += 1
            enrollment.status = "session_pending"
            await self._context.session.flush()
        if existing is not None:
            liveness.provider_claim_token = claim_token
            liveness.provider_claim_expires_at = now + timedelta(
                seconds=self._context.settings.my_photos.liveness_provider_claim_seconds
            )

        # Commit the durable single-use reservation before calling a remote
        # liveness provider. Retrying the same idempotency key resumes this
        # logical session; a new passenger retry receives a new session ID.
        await self._context.session.commit()
        try:
            async with asyncio.timeout(
                self._context.settings.my_photos.liveness_provider_timeout_seconds
            ):
                raw_provider_handle = await self._context.providers.liveness.create_session(
                    LivenessSessionRequest(
                        session_identity=str(liveness.id),
                        tenant_scope=str(claims.agency_id),
                        group_scope=str(trip.group.id),
                        passenger_scope=str(identity.id),
                        challenge_mode=request.challenge_mode,
                        expires_at=liveness.expires_at,
                        audit_image_retention_enabled=(
                            self._context.settings.my_photos.provider_audit_image_retention_enabled
                        ),
                        reference_frame_retention_seconds=(
                            self._context.settings.my_photos.reference_frame_retention_seconds
                        ),
                    )
                )
            client_flow = self._context.providers.liveness.client_flow
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
            await self._context._ready_gallery(claims.agency_id, trip.group.id)
        except MyPhotosUnavailable as exc:
            await self._state._fail_liveness_creation(
                liveness.id, enrollment.id, claim_token, exc.code
            )
            await self._context.session.commit()
            if exc.code == "MY_PHOTOS_PROVIDER_THROTTLED":
                raise MyPhotosRateLimited(
                    self._context.settings.my_photos.provider_retry_after_seconds,
                    "Face Scan is busy. Try again shortly.",
                    code="MY_PHOTOS_PROVIDER_THROTTLED",
                ) from exc
            raise
        except Exception as exc:
            await self._state._fail_liveness_creation(
                liveness.id,
                enrollment.id,
                claim_token,
                "MY_PHOTOS_PROVIDER_UNAVAILABLE",
            )
            await self._context.session.commit()
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_UNAVAILABLE",
                "Face Scan is temporarily unavailable.",
            ) from exc

        await self._context._lock_passenger_identity(identity.id, claims.agency_id, trip.group.id)
        enrollment = await self._context._required_current_enrollment(identity.id, trip.group.id)
        liveness = await self._state._complete_liveness_creation(
            liveness.id,
            enrollment.id,
            request.idempotency_key,
            claim_token,
            provider_handle.provider_reference,
            provider_handle.expires_at,
            provider_handle.native_launch_handle,
        )
        return self._state._liveness_session_response(liveness, enrollment)

    async def complete_liveness(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        session_id: uuid.UUID,
        request: MyPhotosLivenessCompleteRequest,
    ) -> MyPhotosLivenessCompleteResponse:
        identity = self._context._require_passenger(claims, trip)
        gallery = await self._context._ready_gallery(claims.agency_id, trip.group.id)
        await self._context._lock_passenger_identity(identity.id, claims.agency_id, trip.group.id)
        enrollment = await self._context._required_current_enrollment(identity.id, trip.group.id)
        liveness = (
            await self._context.session.execute(
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
                    enrollment = await self._references._delete_superseded_reference(
                        enrollment=enrollment,
                        passenger_identity_id=identity.id,
                    )
                search = await self._context._latest_search(identity.id, trip.group.id)
                return _completion_response(liveness, enrollment, search)
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
            self._state._apply_liveness_cooldown(enrollment, now)
            await self._context.session.flush()
            return _completion_response(liveness, enrollment, None)

        self._context._require_face_providers()
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
            seconds=self._context.settings.my_photos.liveness_provider_claim_seconds
        )
        # Persist the completion claim and release row locks before provider I/O.
        await self._context.session.flush()
        await self._context.session.commit()
        try:
            async with asyncio.timeout(
                self._context.settings.my_photos.liveness_provider_timeout_seconds
            ):
                raw_result = await self._context.providers.liveness.get_result(
                    provider_session_reference
                )
            result = _validated_liveness_result(raw_result)
        except MyPhotosUnavailable as exc:
            await self._state._release_liveness_result_claim(session_id, claim_token)
            if "THROTTLED" in exc.code:
                my_photos_metrics.provider("throttled")
                raise MyPhotosRateLimited(
                    self._context.settings.my_photos.provider_retry_after_seconds,
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
            await self._state._release_liveness_result_claim(session_id, claim_token)
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_UNAVAILABLE",
                "Face Scan verification is temporarily unavailable.",
            ) from exc
        if result.outcome == "throttled":
            my_photos_metrics.provider("throttled")
            await self._state._release_liveness_result_claim(session_id, claim_token)
            raise MyPhotosRateLimited(
                self._context.settings.my_photos.provider_retry_after_seconds,
                "Face Scan verification is busy. Try again shortly.",
                code="MY_PHOTOS_PROVIDER_THROTTLED",
            )
        if result.outcome == "unavailable":
            my_photos_metrics.provider("unavailable")
            await self._state._release_liveness_result_claim(session_id, claim_token)
            raise MyPhotosUnavailable(
                "MY_PHOTOS_PROVIDER_UNAVAILABLE",
                "Face Scan verification is temporarily unavailable.",
            )

        gallery = await self._context._ready_gallery(claims.agency_id, trip.group.id)
        liveness, enrollment, search = await self._state._finalize_liveness_result(
            identity_id=identity.id,
            enrollment_id=enrollment.id,
            gallery=gallery,
            session_id=session_id,
            idempotency_key=request.idempotency_key,
            provider_session_reference=provider_session_reference,
            provider_claim_token=claim_token,
            result=result,
        )
        if enrollment.superseded_reference_deletion_status in {"pending", "failed"}:
            enrollment = await self._references._delete_superseded_reference(
                enrollment=enrollment,
                passenger_identity_id=identity.id,
            )
        return _completion_response(liveness, enrollment, search)
