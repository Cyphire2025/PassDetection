"""Passenger consent and deletion workflows with durable cleanup markers."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update

from app.application.my_photos.errors import (
    MyPhotosConflict,
    MyPhotosUnavailable,
)
from app.application.my_photos.providers import (
    ReferenceDeletionRequest,
)
from app.application.security.mobile_access_policy import AuthorizedMobileTrip
from app.core.security.mobile_jwt import MobileAccessClaims
from app.infrastructure.database.my_photos_models import (
    MyPhotoEnrollmentModel,
    MyPhotoJobModel,
    MyPhotoLivenessSessionModel,
    MyPhotoMatchModel,
    MyPhotoSearchRunModel,
)
from app.infrastructure.my_photos.audit import record_my_photos_audit
from app.infrastructure.my_photos.context import MyPhotosContext
from app.infrastructure.my_photos.liveness_validation import (
    _as_utc,
    _stable_error_code,
)
from app.infrastructure.my_photos.reference_lifecycle import MyPhotosReferenceLifecycle
from app.infrastructure.my_photos.summary_projector import MyPhotosSummaryProjector
from app.presentation.api.v1.schemas.my_photos_schemas import (
    MyPhotosConsentRequest,
    MyPhotosDeleteEnrollmentRequest,
    MyPhotosDeleteEnrollmentResponse,
    MyPhotosSummaryResponse,
)


class MyPhotosEnrollmentService:
    def __init__(
        self,
        context: MyPhotosContext,
        *,
        references: MyPhotosReferenceLifecycle,
        summary: MyPhotosSummaryProjector,
    ) -> None:
        self._context = context
        self._references = references
        self._summary = summary

    async def accept_consent(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        request: MyPhotosConsentRequest,
    ) -> MyPhotosSummaryResponse:
        identity = self._context._require_passenger(claims, trip)
        gallery = await self._context._ready_gallery(claims.agency_id, trip.group.id)
        self._context._require_face_providers()
        await self._context._lock_passenger_identity(identity.id, claims.agency_id, trip.group.id)
        config = self._context.settings.my_photos
        if request.consent_version != config.consent_version:
            raise MyPhotosConflict(
                "MY_PHOTOS_CONSENT_VERSION_REQUIRED",
                "The Face Scan consent text changed. Review the current consent before continuing.",
            )
        now = datetime.now(tz=UTC)
        enrollment = await self._context._enrollment(identity.id, trip.group.id, for_update=True)
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
            self._context.session.add(enrollment)
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
        await self._context.session.flush()
        if consent_changed:
            await record_my_photos_audit(
                self._context.session,
                action="my_photos_consent_accepted",
                agency_id=claims.agency_id,
                group_id=trip.group.id,
                outcome="accepted",
                configuration_version=request.consent_version,
            )
        search = await self._context._latest_search(identity.id, trip.group.id)
        return await self._summary.build(
            group_name=trip.group.name,
            group_id=trip.group.id,
            gallery=gallery,
            enrollment=enrollment,
            search=search,
            passenger_identity_id=identity.id,
        )

    async def delete_enrollment(
        self,
        *,
        claims: MobileAccessClaims,
        trip: AuthorizedMobileTrip,
        request: MyPhotosDeleteEnrollmentRequest,
    ) -> MyPhotosDeleteEnrollmentResponse:
        identity = self._context._require_passenger(claims, trip)
        await self._context._lock_passenger_identity(identity.id, claims.agency_id, trip.group.id)
        enrollment = await self._context._enrollment(identity.id, trip.group.id, for_update=True)
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
                return self._references._deletion_response(enrollment)
        else:
            deletion_created = True
            active_search_ids = select(MyPhotoSearchRunModel.id).where(
                MyPhotoSearchRunModel.passenger_identity_id == identity.id,
                MyPhotoSearchRunModel.agency_id == claims.agency_id,
                MyPhotoSearchRunModel.group_id == trip.group.id,
                MyPhotoSearchRunModel.status.in_(("queued", "searching")),
            )
            await self._context.session.execute(
                update(MyPhotoJobModel)
                .where(
                    MyPhotoJobModel.search_run_id.in_(active_search_ids),
                    MyPhotoJobModel.status.in_(("queued", "running", "retrying")),
                )
                .values(cancellation_requested_at=now)
            )
            await self._context.session.execute(
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
                await self._context.session.execute(
                    delete(MyPhotoMatchModel).where(
                        MyPhotoMatchModel.passenger_identity_id == identity.id,
                        MyPhotoMatchModel.group_id == trip.group.id,
                    )
                )
                await self._context.session.execute(
                    delete(MyPhotoJobModel).where(MyPhotoJobModel.search_run_id.in_(search_ids))
                )
                await self._context.session.execute(
                    delete(MyPhotoSearchRunModel).where(
                        MyPhotoSearchRunModel.passenger_identity_id == identity.id,
                        MyPhotoSearchRunModel.group_id == trip.group.id,
                    )
                )
            await self._context.session.execute(
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
                    seconds=self._context.settings.my_photos.liveness_cooldown_seconds
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
        await self._context.session.flush()
        if deletion_created:
            await record_my_photos_audit(
                self._context.session,
                action="my_photos_enrollment_deleted",
                agency_id=claims.agency_id,
                group_id=trip.group.id,
                outcome=enrollment.provider_deletion_status,
            )
        if (
            enrollment.provider_deletion_status == "not_required"
            and enrollment.superseded_reference_deletion_status not in {"pending", "failed"}
        ):
            return self._references._deletion_response(enrollment)

        # Persist the user's deletion request before provider I/O. A process
        # interruption therefore leaves a retryable, auditable pending state.
        await self._context.session.commit()
        if enrollment.superseded_reference_deletion_status in {"pending", "failed"}:
            enrollment = await self._references._delete_superseded_reference(
                enrollment=enrollment,
                passenger_identity_id=identity.id,
            )
        if enrollment.provider_deletion_status in {"not_required", "complete"}:
            return self._references._deletion_response(enrollment)
        provider_reference = enrollment.provider_reference_handle
        if provider_reference is None:
            return self._references._deletion_response(enrollment)
        try:
            async with asyncio.timeout(
                self._context.settings.my_photos.liveness_provider_timeout_seconds
            ):
                deletion_result = await self._context.providers.liveness.delete_reference(
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
            await self._references._mark_provider_deletion_pending(
                enrollment.id,
                request.idempotency_key,
                request.scope,
                _stable_error_code(exc.code),
                expected_provider_reference=provider_reference,
            )
            refreshed = await self._context._enrollment(identity.id, trip.group.id)
            if refreshed is None:
                raise MyPhotosConflict(
                    "MY_PHOTOS_ENROLLMENT_CHANGED",
                    "Face Scan deletion state changed. Refresh My Photos.",
                )
            return self._references._deletion_response(refreshed)
        except Exception:
            await self._references._mark_provider_deletion_pending(
                enrollment.id,
                request.idempotency_key,
                request.scope,
                "PROVIDER_DELETION_UNAVAILABLE",
                expected_provider_reference=provider_reference,
            )
            refreshed = await self._context._enrollment(identity.id, trip.group.id)
            if refreshed is None:
                raise MyPhotosConflict(
                    "MY_PHOTOS_ENROLLMENT_CHANGED",
                    "Face Scan deletion state changed. Refresh My Photos.",
                )
            return self._references._deletion_response(refreshed)

        refreshed = await self._references._complete_provider_deletion(
            enrollment.id,
            request.idempotency_key,
            request.scope,
            provider_reference,
        )
        return self._references._deletion_response(refreshed)
