"""Passport review confirmation: cohesive transaction and response owner."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.passenger_change_propagation import propagate_mobile_passenger_change
from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.passports.confirm_passport_submission_use_case import (
    ConfirmPassportSubmissionUseCase,
)
from app.application.use_cases.passports.get_passport_submission_use_case import (
    GetPassportSubmissionUseCase,
)
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import (
    AuthorizationError,
    ConflictError,
    EntityNotFoundError,
    PassDetectionError,
)
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.schemas.passport_schemas import (
    ConfirmPassportSubmissionRequest,
    PassportSubmissionResponse,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

from .dependencies import (
    _get_confirm_passport_use_case,
    _get_get_passport_use_case,
)
from .response_support import _ensure_submission_qr, _response_from_dto
from .submission_review_support import (
    _schedule_review_history,
)

router = APIRouter()


@router.post(
    "/{submission_id}/confirm",
    response_model=PassportSubmissionResponse,
    status_code=status.HTTP_200_OK,
    summary="Confirm reviewed passport fields",
)
async def confirm_passport(
    submission_id: uuid.UUID,
    body: ConfirmPassportSubmissionRequest,
    _csrf: None = Depends(require_cookie_csrf),
    current_user: User = Depends(get_current_active_user),
    get_use_case: GetPassportSubmissionUseCase = Depends(_get_get_passport_use_case),
    confirm_use_case: ConfirmPassportSubmissionUseCase = Depends(_get_confirm_passport_use_case),
    session: AsyncSession = Depends(get_db_session),
) -> PassportSubmissionResponse:
    try:
        existing = await get_use_case.execute(submission_id)
        await AuthorizationPolicy(session).require_confirm_passport(current_user, existing)

        await session.execute(
            select(ClientGroupModel.id)
            .where(
                ClientGroupModel.id == existing.group_id,
                ClientGroupModel.agency_id == existing.agency_id,
            )
            .with_for_update()
        )
        result = await confirm_use_case.execute(
            submission_id,
            confirmed_fields=body.confirmed_fields,
        )
        await _schedule_review_history(
            session,
            result=result,
            trigger=f"staff-confirm:{result.id}:{result.extraction_revision}",
        )
        await AuditLogRepository(session).record(
            action="passport_confirmed",
            entity_type="passport_submission",
            entity_id=str(result.id),
            agency_id=result.agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
        )
        await _ensure_submission_qr(session, result.id, current_user.id)
        await propagate_mobile_passenger_change(
            session,
            agency_id=result.agency_id,
            group_id=result.group_id,
            passenger_submission_ids=[result.id],
            actor_user_id=current_user.id,
        )
        return await _response_from_dto(result, session=session)
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except AuthorizationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=e.message)
    except PassDetectionError as e:
        raise HTTPException(
            status_code=(
                status.HTTP_409_CONFLICT
                if isinstance(e, ConflictError)
                else status.HTTP_400_BAD_REQUEST
            ),
            detail=e.message,
        )


confirm_passport.__module__ = "app.presentation.api.v1.routes.passport_routes.submission_review"
