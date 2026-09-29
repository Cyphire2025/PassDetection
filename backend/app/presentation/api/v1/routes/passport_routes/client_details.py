"""Authorized, concurrency-fenced corrections of client-provided group details."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.passenger_change_propagation import propagate_mobile_passenger_change
from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.passports.client_details_fields import client_details_payload
from app.application.use_cases.passports.client_details_transaction import (
    ClientDetailDependencies,
    ClientDetailsUnavailable,
    apply_client_detail_correction,
    editable_client_submission,
)
from app.domain.entities.entities import ClientGroup, PassportSubmission, User
from app.domain.exceptions.exceptions import ValidationError
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.passport_roster_resolution_repository import (
    lock_linked_whatsapp_broadcast_groups,
)
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.repositories.sensitive_read_audit import record_sensitive_read
from app.infrastructure.whatsapp.private_delivery_policy import (
    PrivateDeliveryMutationBlocked,
    prepare_private_delivery_identity_mutation,
)
from app.presentation.api.v1.schemas.passport_client_details_schemas import (
    PassportClientDetailsResponse,
    UpdatePassportClientDetailsRequest,
)
from app.presentation.api.v1.schemas.passport_schemas import PassportSubmissionResponse
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

from .response_support import _response_from_submission

router = APIRouter()


def _dependencies(session: AsyncSession) -> ClientDetailDependencies:
    return ClientDetailDependencies(
        PassportSubmissionRepository(session),
        ClientGroupRepository(session),
        AuditLogRepository(session),
        AuthorizationPolicy(session),
        lock_linked_whatsapp_broadcast_groups,
        prepare_private_delivery_identity_mutation,
        propagate_mobile_passenger_change,
    )


async def _editable_submission(
    submission_id: uuid.UUID,
    current_user: User,
    session: AsyncSession,
    *,
    lock: bool,
) -> tuple[PassportSubmission, ClientGroup]:
    try:
        return await editable_client_submission(
            submission_id, current_user, session, lock=lock, dependencies=_dependencies(session)
        )
    except ClientDetailsUnavailable as exc:
        raise HTTPException(exc.status, exc.message) from exc


@router.get("/{submission_id}/client-details", response_model=PassportClientDetailsResponse)
async def get_passport_client_details(
    submission_id: uuid.UUID,
    response: Response,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportClientDetailsResponse:
    submission, group = await _editable_submission(submission_id, current_user, session, lock=False)
    await record_sensitive_read(
        session,
        user=current_user,
        kind="client_details",
        agency_id=submission.agency_id,
        entity_id=submission.id,
    )
    response.headers["Cache-Control"] = "no-store"
    return PassportClientDetailsResponse.model_validate(client_details_payload(submission, group))


@router.patch("/{submission_id}/client-details", response_model=PassportSubmissionResponse)
async def update_passport_client_details(
    submission_id: uuid.UUID,
    body: UpdatePassportClientDetailsRequest,
    response: Response,
    _csrf: None = Depends(require_cookie_csrf),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportSubmissionResponse:
    try:
        correction = await apply_client_detail_correction(
            session,
            submission_id=submission_id,
            user=current_user,
            expected_updated_at=body.expected_updated_at,
            changes=body.model_dump(
                mode="json", exclude_unset=True, exclude={"expected_updated_at"}
            ),
            cancel_queued=True,
            dependencies=_dependencies(session),
        )
        # The web boundary retains its established cancellation and commit
        # behavior; the shared helper never commits or dispatches messaging.
        await session.commit()
    except ClientDetailsUnavailable as exc:
        await session.rollback()
        raise HTTPException(exc.status, exc.message) from exc
    except PrivateDeliveryMutationBlocked as exc:
        await session.rollback()
        raise HTTPException(409, str(exc)) from exc
    except ValidationError as exc:
        await session.rollback()
        raise HTTPException(422, exc.message) from exc
    except Exception:
        await session.rollback()
        raise
    response.headers["Cache-Control"] = "no-store"
    return await _response_from_submission(correction.submission, session=session)
