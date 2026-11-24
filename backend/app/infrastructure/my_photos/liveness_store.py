"""Claim-fenced liveness persistence and durable search scheduling."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.application.my_photos.errors import (
    MyPhotosConflict,
    MyPhotosUnavailable,
)
from app.application.my_photos.providers import (
    LivenessResult,
)
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.infrastructure.database.my_photos_models import (
    MyPhotoEnrollmentModel,
    MyPhotoFaceOccurrenceModel,
    MyPhotoGalleryModel,
    MyPhotoJobModel,
    MyPhotoLivenessSessionModel,
    MyPhotoSearchRunModel,
)
from app.infrastructure.my_photos.audit import record_my_photos_audit
from app.infrastructure.my_photos.context import MyPhotosContext
from app.infrastructure.my_photos.liveness_validation import (
    _as_utc,
    _provider_claim_active,
    _require_current_consent,
    _stable_error_code,
)
from app.presentation.api.v1.schemas.my_photos_schemas import (
    MyPhotosLivenessSessionResponse,
)


class MyPhotosLivenessStore:
    def __init__(self, context: MyPhotosContext) -> None:
        self._context = context

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
            await self._context.session.execute(
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
                await self._context.session.execute(
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
            max_attempts=self._context.settings.my_photos.job_max_attempts,
            correlation_id=uuid.uuid4().hex,
        )
        self._context.session.add(search)
        await self._context.session.flush()
        self._context.session.add(
            MyPhotoJobModel(
                gallery_id=gallery.id,
                search_run_id=search.id,
                agency_id=gallery.agency_id,
                group_id=gallery.group_id,
                job_type="search_passenger",
                status="queued",
                idempotency_key=idempotency_key,
                max_attempts=self._context.settings.my_photos.job_max_attempts,
                total_count=total_face_count,
                correlation_id=search.correlation_id,
            )
        )
        return search

    def _apply_liveness_cooldown(self, enrollment: MyPhotoEnrollmentModel, now: datetime) -> None:
        if enrollment.status != "rejected":
            return
        if enrollment.attempt_count >= enrollment.max_attempts:
            enrollment.status = "cooldown"
            enrollment.cooldown_until = now + timedelta(
                seconds=self._context.settings.my_photos.liveness_cooldown_seconds
            )

    async def _finalize_liveness_result(
        self,
        *,
        identity_id: uuid.UUID,
        enrollment_id: uuid.UUID,
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
        await self._context._lock_passenger_identity(
            identity_id, gallery.agency_id, gallery.group_id
        )
        enrollment = (
            await self._context.session.execute(
                select(MyPhotoEnrollmentModel)
                .where(
                    MyPhotoEnrollmentModel.id == enrollment_id,
                    MyPhotoEnrollmentModel.passenger_identity_id == identity_id,
                    MyPhotoEnrollmentModel.agency_id == gallery.agency_id,
                    MyPhotoEnrollmentModel.group_id == gallery.group_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if enrollment is None:
            raise EntityNotFoundError("Face Scan session", session_id)
        _require_current_consent(enrollment, self._context.settings.my_photos.consent_version)
        liveness = (
            await self._context.session.execute(
                select(MyPhotoLivenessSessionModel)
                .where(
                    MyPhotoLivenessSessionModel.id == session_id,
                    MyPhotoLivenessSessionModel.enrollment_id == enrollment_id,
                    MyPhotoLivenessSessionModel.agency_id == gallery.agency_id,
                    MyPhotoLivenessSessionModel.group_id == gallery.group_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if liveness is None:
            raise EntityNotFoundError("Face Scan session", session_id)
        if (
            liveness.completion_idempotency_key != idempotency_key
            or liveness.completion_outcome != "completed"
            or liveness.provider_session_reference != provider_session_reference
            or liveness.provider_claim_token != provider_claim_token
            or not _provider_claim_active(liveness, datetime.now(tz=UTC))
        ):
            raise MyPhotosConflict(
                "MY_PHOTOS_SESSION_CHANGED", "Face Scan session changed. Start again."
            )
        if liveness.status != "running":
            existing_search = await self._context._latest_search(identity_id, gallery.group_id)
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
            enrollment.provider_name = self._context.providers.provider_name
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
            liveness.stable_error_code = _stable_error_code(
                result.stable_error_code or "LIVENESS_FAILED"
            )
            enrollment.status = (
                "enrolled" if enrollment.provider_reference_handle is not None else "rejected"
            )
            self._apply_liveness_cooldown(enrollment, now)
        await self._context.session.flush()
        await record_my_photos_audit(
            self._context.session,
            action="my_photos_enrollment_completed",
            agency_id=gallery.agency_id,
            group_id=gallery.group_id,
            outcome="enrolled" if enrollment.status == "enrolled" else liveness.status,
            gallery_revision=gallery.published_revision,
            configuration_version=self._context.settings.my_photos.match_config_version,
        )
        return liveness, enrollment, search

    async def _fail_liveness_creation(
        self,
        session_id: uuid.UUID,
        enrollment_id: uuid.UUID,
        provider_claim_token: str,
        error_code: str,
    ) -> None:
        enrollment = (
            await self._context.session.execute(
                select(MyPhotoEnrollmentModel)
                .where(MyPhotoEnrollmentModel.id == enrollment_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        liveness = (
            await self._context.session.execute(
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
        now = datetime.now(tz=UTC)
        liveness.status = "failed"
        liveness.provider_claim_token = None
        liveness.provider_claim_expires_at = None
        liveness.native_launch_handle = None
        liveness.stable_error_code = _stable_error_code(error_code)
        liveness.result_retryable = True
        liveness.consumed_at = now
        if enrollment is not None and enrollment.status not in {"revoked", "deleted"}:
            # Provider session creation never presented a usable challenge, so
            # it must not consume a passenger attempt. Preserve a prior valid
            # enrollment when an optional refresh fails before launch.
            enrollment.attempt_count = max(0, enrollment.attempt_count - 1)
            enrollment.cooldown_until = None
            enrollment.status = (
                "enrolled" if enrollment.provider_reference_handle is not None else "ready"
            )
        await self._context.session.flush()

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
            await self._context.session.execute(
                select(MyPhotoLivenessSessionModel)
                .where(
                    MyPhotoLivenessSessionModel.id == session_id,
                    MyPhotoLivenessSessionModel.enrollment_id == enrollment_id,
                    MyPhotoLivenessSessionModel.idempotency_key == idempotency_key,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if liveness is None:
            raise MyPhotosConflict(
                "MY_PHOTOS_SESSION_CHANGED", "Face Scan session changed. Start again."
            )
        if liveness.status == "created" and liveness.provider_session_reference is not None:
            return liveness
        now = datetime.now(tz=UTC)
        if (
            liveness.status != "creating"
            or liveness.provider_claim_token != provider_claim_token
            or not _provider_claim_active(liveness, now)
        ):
            raise MyPhotosConflict(
                "MY_PHOTOS_SESSION_CHANGED", "Face Scan session changed. Start again."
            )
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
        await self._context.session.flush()
        return liveness

    async def _release_liveness_result_claim(
        self,
        session_id: uuid.UUID,
        provider_claim_token: str,
    ) -> None:
        """Release only this caller's claim after a sanitized provider failure."""

        liveness = (
            await self._context.session.execute(
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
        await self._context.session.flush()
        await self._context.session.commit()

    def _liveness_session_response(
        self,
        session: MyPhotoLivenessSessionModel,
        enrollment: MyPhotoEnrollmentModel,
    ) -> MyPhotosLivenessSessionResponse:
        flow = self._context.providers.liveness.client_flow
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
