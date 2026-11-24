"""Passport review approval: cohesive transaction and response owner."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.passenger_change_propagation import propagate_mobile_passenger_change
from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.passports.get_passport_submission_use_case import (
    GetPassportSubmissionUseCase,
)
from app.application.use_cases.passports.staff_approve_passport_use_case import (
    StaffApprovalResult,
    StaffApprovePassportUseCase,
)
from app.domain.entities.entities import StaffApprovalOutcome, User
from app.domain.exceptions.exceptions import (
    AuthorizationError,
    EntityNotFoundError,
    StaffApprovalStaleError,
    StaffApprovalUnavailableError,
)
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.observability.operational_events import (
    OperationalEvent,
    record_operational_event,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportSubmissionResponse,
    StaffApprovePassportRequest,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

from .dependencies import (
    _get_get_passport_use_case,
    _get_staff_approve_passport_use_case,
)
from .response_support import _ensure_submission_qr, _response_from_dto
from .submission_review_support import (
    _schedule_review_history,
    _staff_approval_conflict_response,
)

router = APIRouter()


@router.post(
    "/{submission_id}/staff-approve",
    response_model=PassportSubmissionResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve a passport that needs post-submission review",
)
async def staff_approve_passport(
    submission_id: uuid.UUID,
    body: StaffApprovePassportRequest,
    response: Response,
    _csrf: None = Depends(require_cookie_csrf),
    current_user: User = Depends(get_current_active_user),
    get_use_case: GetPassportSubmissionUseCase = Depends(_get_get_passport_use_case),
    approve_use_case: StaffApprovePassportUseCase = Depends(_get_staff_approve_passport_use_case),
    session: AsyncSession = Depends(get_db_session),
) -> PassportSubmissionResponse | JSONResponse:
    try:
        existing = await get_use_case.execute(submission_id)
        await AuthorizationPolicy(session).require_staff_approve_passport(
            current_user,
            existing,
        )
        await session.execute(
            select(ClientGroupModel.id)
            .where(
                ClientGroupModel.id == existing.group_id,
                ClientGroupModel.agency_id == existing.agency_id,
            )
            .with_for_update()
        )
        approval: StaffApprovalResult = await approve_use_case.execute(
            submission_id,
            reviewer_id=current_user.id,
            reviewer_name=current_user.full_name,
            confirmed_fields=body.confirmed_fields,
            expected_extraction_revision=body.expected_extraction_revision,
            review_reason=body.review_reason,
        )
        result = approval.submission
        await _schedule_review_history(
            session,
            result=result,
            trigger=f"staff-approval:{result.id}:{result.extraction_revision}",
        )
        if approval.outcome is StaffApprovalOutcome.APPROVED:
            audit_metadata: dict[str, object] = {
                "group_id": str(result.group_id),
                "prior_status": approval.previous_status,
                "new_status": result.status,
                "corrected_field_names": list(approval.corrected_field_names),
                "outcome": approval.outcome.value,
                "extraction_revision": result.extraction_revision,
                "verification_revision": (result.post_submission_verification_revision),
            }
            if approval.review_reason is not None:
                audit_metadata["review_reason"] = approval.review_reason
            await AuditLogRepository(session).record(
                action="passport_staff_approved",
                entity_type="passport_submission",
                entity_id=str(result.id),
                agency_id=result.agency_id,
                user_id=current_user.id,
                metadata=audit_metadata,
            )
            await _ensure_submission_qr(session, result.id, current_user.id)
            await propagate_mobile_passenger_change(
                session,
                agency_id=result.agency_id,
                group_id=result.group_id,
                passenger_submission_ids=[result.id],
                actor_user_id=current_user.id,
            )

        # The locked transition, audit row, and first QR issuance are one
        # transaction. Commit before presigned-URL work so the row lock is
        # released and a lost response can be retried idempotently.
        await session.commit()
        record_operational_event(
            OperationalEvent.STAFF_APPROVAL,
            (
                "approved"
                if approval.outcome is StaffApprovalOutcome.APPROVED
                else "already_approved"
            ),
        )
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Staff-Approval-Outcome"] = approval.outcome.value
        response.headers["X-Staff-Approval-Revision"] = str(result.extraction_revision)
        return await _response_from_dto(result, session=session)
    except (StaffApprovalStaleError, StaffApprovalUnavailableError) as exc:
        # The typed conflict is raised while the submission row is locked.
        # Release that lock before returning the retry-safe 409 response.
        await session.rollback()
        record_operational_event(
            OperationalEvent.STAFF_APPROVAL,
            ("stale" if isinstance(exc, StaffApprovalStaleError) else "unavailable"),
        )
        return _staff_approval_conflict_response(exc)
    except EntityNotFoundError as exc:
        record_operational_event(
            OperationalEvent.STAFF_APPROVAL,
            "not_found",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.message,
        )
    except AuthorizationError as exc:
        record_operational_event(
            OperationalEvent.STAFF_APPROVAL,
            "forbidden",
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.message,
        )
    except Exception:
        record_operational_event(
            OperationalEvent.STAFF_APPROVAL,
            "unexpected_failure",
        )
        raise


staff_approve_passport.__module__ = (
    "app.presentation.api.v1.routes.passport_routes.submission_review"
)
