"""Durable current and superseded biometric reference cleanup."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from sqlalchemy import select

from app.application.my_photos.errors import (
    MyPhotosConflict,
    MyPhotosUnavailable,
)
from app.application.my_photos.providers import (
    ReferenceDeletionRequest,
)
from app.infrastructure.database.my_photos_models import (
    MyPhotoEnrollmentModel,
)
from app.infrastructure.my_photos.audit import record_my_photos_audit
from app.infrastructure.my_photos.context import MyPhotosContext
from app.infrastructure.my_photos.liveness_validation import (
    _stable_error_code,
)
from app.presentation.api.v1.schemas.my_photos_schemas import (
    MyPhotosDeleteEnrollmentResponse,
)


class MyPhotosReferenceLifecycle:
    def __init__(self, context: MyPhotosContext) -> None:
        self._context = context

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
            < self._context.settings.my_photos.provider_deletion_max_attempts
        )
        superseded_retryable = superseded_status == "pending" or (
            superseded_status == "failed"
            and enrollment.superseded_deletion_attempt_count
            < self._context.settings.my_photos.provider_deletion_max_attempts
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
        *,
        expected_provider_reference: str,
    ) -> None:
        enrollment = (
            await self._context.session.execute(
                select(MyPhotoEnrollmentModel)
                .where(
                    MyPhotoEnrollmentModel.id == enrollment_id,
                    MyPhotoEnrollmentModel.status == "deleted",
                    MyPhotoEnrollmentModel.deletion_idempotency_key == idempotency_key,
                    MyPhotoEnrollmentModel.deletion_scope == deletion_scope,
                    MyPhotoEnrollmentModel.provider_reference_handle == expected_provider_reference,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        if enrollment is None:
            return
        now = datetime.now(tz=UTC)
        enrollment.provider_deletion_attempt_count = min(
            enrollment.provider_deletion_attempt_count + 1,
            self._context.settings.my_photos.provider_deletion_max_attempts,
        )
        enrollment.provider_deletion_last_attempt_at = now
        exhausted = (
            enrollment.provider_deletion_attempt_count
            >= self._context.settings.my_photos.provider_deletion_max_attempts
        )
        enrollment.provider_deletion_status = "failed" if exhausted else "pending"
        enrollment.provider_deletion_error_code = error_code
        enrollment.provider_deletion_completed_at = None
        enrollment.provider_deletion_next_attempt_at = (
            None
            if exhausted
            else now + timedelta(seconds=self._context.settings.my_photos.job_retry_base_seconds)
        )
        await self._context.session.flush()
        await record_my_photos_audit(
            self._context.session,
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
        await self._context.session.commit()
        try:
            async with asyncio.timeout(
                self._context.settings.my_photos.liveness_provider_timeout_seconds
            ):
                deletion_result = await self._context.providers.liveness.delete_reference(
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
            error_code = _stable_error_code(exc.code)
        except Exception:
            deletion_complete = False
            error_code = "PROVIDER_DELETION_UNAVAILABLE"

        refreshed = (
            await self._context.session.execute(
                select(MyPhotoEnrollmentModel)
                .where(MyPhotoEnrollmentModel.id == enrollment.id)
                .with_for_update()
                .execution_options(populate_existing=True)
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
                self._context.settings.my_photos.provider_deletion_max_attempts,
            )
            failed_at = datetime.now(tz=UTC)
            exhausted = (
                refreshed.superseded_deletion_attempt_count
                >= self._context.settings.my_photos.provider_deletion_max_attempts
            )
            refreshed.superseded_reference_deletion_status = "failed" if exhausted else "pending"
            refreshed.superseded_reference_deletion_error_code = error_code
            refreshed.superseded_deletion_last_attempt_at = failed_at
            refreshed.superseded_deletion_next_attempt_at = (
                None
                if exhausted
                else failed_at
                + timedelta(seconds=self._context.settings.my_photos.job_retry_base_seconds)
            )
        await self._context.session.flush()
        await record_my_photos_audit(
            self._context.session,
            action="my_photos_provider_deletion",
            agency_id=refreshed.agency_id,
            group_id=refreshed.group_id,
            outcome="superseded_complete" if deletion_complete else "superseded_pending",
        )
        # Release the enrollment lock before any caller performs another
        # provider operation (for example deleting the current reference too).
        await self._context.session.commit()
        return refreshed

    async def _complete_provider_deletion(
        self,
        enrollment_id: uuid.UUID,
        idempotency_key: str,
        deletion_scope: str,
        provider_reference: str,
    ) -> MyPhotoEnrollmentModel:
        enrollment = (
            await self._context.session.execute(
                select(MyPhotoEnrollmentModel)
                .where(
                    MyPhotoEnrollmentModel.id == enrollment_id,
                    MyPhotoEnrollmentModel.status == "deleted",
                    MyPhotoEnrollmentModel.deletion_idempotency_key == idempotency_key,
                    MyPhotoEnrollmentModel.deletion_scope == deletion_scope,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
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
        await self._context.session.flush()
        await record_my_photos_audit(
            self._context.session,
            action="my_photos_provider_deletion",
            agency_id=enrollment.agency_id,
            group_id=enrollment.group_id,
            outcome="complete",
        )
        return enrollment
