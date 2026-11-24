"""Browser runtime continuity and privacy-safe offline discard receipts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.coordinator_roster_revision import (
    coordinator_roster_revision,
)
from app.core.config.settings import get_settings
from app.core.security.mobile_offline_lease import sign_offline_manifest
from app.domain.entities.entities import (
    User,
    UserRole,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.attendance_discard_repository import (
    AttendanceDiscardRepository,
)
from app.infrastructure.repositories.attendance_runtime_repository import (
    AttendanceRuntimeError,
    AttendanceRuntimeRepository,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.routes.attendance_discard_sync import (
    synchronize_browser_discard_groups,
)
from app.presentation.api.v1.routes.attendance_offline_authorization import (
    build_browser_offline_authorization,
)
from app.presentation.api.v1.routes.attendance_offline_sources import (
    _offline_readiness_error as _offline_readiness_error,
)
from app.presentation.api.v1.routes.attendance_runtime_dependencies import (
    DiscardSynchronizationDependencies,
    OfflineAuthorizationDependencies,
)
from app.presentation.api.v1.routes.tour_operations import (
    _ensure_group_assigned_to_coordinator,
    _get_coordinator_attendance_session,
    _require_agency,
)
from app.presentation.api.v1.schemas.attendance_runtime_schemas import (
    AttendanceDiscardBatchRequest,
    AttendanceDiscardBatchResponse,
    AttendanceRuntimeDispositionRequest,
    AttendanceRuntimeDispositionResponse,
    AttendanceRuntimeRegistrationRequest,
    AttendanceRuntimeRegistrationResponse,
    BrowserOfflineAuthorizationBundleResponse,
)
from app.presentation.dependencies.auth import require_recent_mfa, require_role
from app.presentation.dependencies.csrf import require_cookie_csrf
from app.presentation.security.attendance_runtime import (
    attendance_runtime_cookie_value,
    parse_attendance_runtime_cookie,
    resolve_browser_attendance_runtime,
)
from app.presentation.security.auth_cookies import (
    ATTENDANCE_RUNTIME_COOKIE_NAME,
    ATTENDANCE_RUNTIME_COOKIE_PATH,
)
from app.presentation.security.client_ip import trusted_client_ip

router = APIRouter()


@router.post(
    "/coordinator/attendance/runtime",
    response_model=AttendanceRuntimeRegistrationResponse,
    dependencies=[Depends(require_cookie_csrf)],
    status_code=status.HTTP_201_CREATED,
    summary="Register this coordinator browser/WebView runtime",
)
async def register_browser_attendance_runtime(
    body: AttendanceRuntimeRegistrationRequest,
    request: Request,
    response: Response,
    current_user: User = Depends(require_role([UserRole.AGENCY_COORDINATOR])),
    session: AsyncSession = Depends(get_db_session),
) -> AttendanceRuntimeRegistrationResponse:
    settings = get_settings()
    agency_id = _require_agency(current_user)
    now = datetime.now(tz=UTC)
    expiry = now + timedelta(days=settings.attendance_runtime_registration_days)
    parsed_cookie = parse_attendance_runtime_cookie(
        request.cookies.get(ATTENDANCE_RUNTIME_COOKIE_NAME)
    )
    existing = await resolve_browser_attendance_runtime(
        request,
        session=session,
        agency_id=agency_id,
        coordinator_user_id=current_user.id,
        required=False,
    )
    outcome = "registered"
    if (
        existing is not None
        and parsed_cookie is not None
        and existing.runtime_kind == body.runtime_kind
    ):
        registration = existing
        cookie_secret = parsed_cookie[1]
        registration.expires_at = expiry
        registration.last_seen_at = now
        registration.updated_at = now
        outcome = "renewed"
        await session.flush()
    else:
        issued = await AttendanceRuntimeRepository(session).issue_browser_runtime(
            agency_id=agency_id,
            coordinator_user_id=current_user.id,
            runtime_kind=body.runtime_kind,
            expires_at=expiry,
            now=now,
        )
        registration = issued.registration
        cookie_secret = issued.cookie_secret
        if existing is not None:
            await AttendanceRuntimeRepository(session).revoke(
                registration_id=existing.id,
                agency_id=agency_id,
                coordinator_user_id=current_user.id,
                status="replaced",
                reason="browser_runtime_kind_changed",
                replacement_runtime_id=registration.id,
                now=now,
            )
            outcome = "replaced"
    response.set_cookie(
        key=ATTENDANCE_RUNTIME_COOKIE_NAME,
        value=attendance_runtime_cookie_value(
            runtime_kind=body.runtime_kind,
            secret=cookie_secret,
        ),
        max_age=settings.attendance_runtime_registration_days * 86_400,
        expires=expiry,
        path=ATTENDANCE_RUNTIME_COOKIE_PATH,
        secure=settings.jwt.cookie_secure or settings.is_production,
        httponly=True,
        samesite="strict",
    )
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    await AuditLogRepository(session).record(
        action="attendance.runtime_registered",
        entity_type="attendance_runtime",
        agency_id=agency_id,
        user_id=current_user.id,
        entity_id=str(registration.id),
        metadata={
            "runtime_kind": registration.runtime_kind,
            "expires_at": expiry.isoformat(),
            "outcome": outcome,
        },
    )
    return AttendanceRuntimeRegistrationResponse(
        runtime_id=registration.id,
        runtime_kind=body.runtime_kind,
        expires_at=expiry,
    )


@router.delete(
    "/coordinator/attendance/runtime",
    dependencies=[Depends(require_cookie_csrf)],
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Revoke this coordinator browser/WebView runtime",
)
async def revoke_current_browser_attendance_runtime(
    request: Request,
    response: Response,
    current_user: User = Depends(require_role([UserRole.AGENCY_COORDINATOR])),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    settings = get_settings()
    agency_id = _require_agency(current_user)
    runtime = await resolve_browser_attendance_runtime(
        request,
        session=session,
        agency_id=agency_id,
        coordinator_user_id=current_user.id,
        required=True,
    )
    if runtime is None:  # pragma: no cover - required=True is exhaustive
        raise RuntimeError("Attendance runtime resolution was incomplete")
    await AttendanceRuntimeRepository(session).revoke(
        registration_id=runtime.id,
        agency_id=agency_id,
        coordinator_user_id=current_user.id,
        reason="coordinator_runtime_revoked",
    )
    await AuditLogRepository(session).record(
        action="attendance.runtime_revoked",
        entity_type="attendance_runtime",
        agency_id=agency_id,
        user_id=current_user.id,
        entity_id=str(runtime.id),
        ip_address=trusted_client_ip(request),
        metadata={"runtime_kind": runtime.runtime_kind, "reason": "self_revoked"},
    )
    response.delete_cookie(
        ATTENDANCE_RUNTIME_COOKIE_NAME,
        path=ATTENDANCE_RUNTIME_COOKIE_PATH,
        secure=settings.jwt.cookie_secure or settings.is_production,
        httponly=True,
        samesite="strict",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.patch(
    "/attendance/runtimes/{runtime_id}/status",
    dependencies=[Depends(require_cookie_csrf), Depends(require_recent_mfa)],
    response_model=AttendanceRuntimeDispositionResponse,
    status_code=status.HTTP_200_OK,
    summary="Mark an unavailable coordinator runtime lost or revoked",
)
async def dispose_attendance_runtime(
    runtime_id: uuid.UUID,
    body: AttendanceRuntimeDispositionRequest,
    request: Request,
    current_user: User = Depends(require_role([UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER])),
    session: AsyncSession = Depends(get_db_session),
) -> AttendanceRuntimeDispositionResponse:
    agency_id = _require_agency(current_user)
    try:
        runtime = await AttendanceRuntimeRepository(session).revoke(
            registration_id=runtime_id,
            agency_id=agency_id,
            coordinator_user_id=body.coordinator_user_id,
            status=body.status,
            reason=body.reason,
        )
    except AttendanceRuntimeError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from None
    if runtime.revoked_at is None:
        raise RuntimeError("Attendance runtime disposition was incomplete")
    await AuditLogRepository(session).record(
        action="attendance.runtime_disposition_recorded",
        entity_type="attendance_runtime",
        agency_id=agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        entity_id=str(runtime.id),
        ip_address=trusted_client_ip(request),
        metadata={
            "coordinator_user_id": str(body.coordinator_user_id),
            "runtime_kind": runtime.runtime_kind,
            "status": runtime.status,
            "reason_category": "manager_runtime_disposition",
        },
    )
    return AttendanceRuntimeDispositionResponse(
        runtime_id=runtime.id,
        status=body.status,
        revoked_at=runtime.revoked_at,
    )


@router.get(
    "/coordinator/groups/{group_id}/offline-authorization",
    response_model=BrowserOfflineAuthorizationBundleResponse,
    status_code=status.HTTP_200_OK,
    summary="Provision a signed, bounded browser offline roster",
)
async def provision_browser_offline_authorization(
    group_id: uuid.UUID,
    request: Request,
    response: Response,
    current_user: User = Depends(require_role([UserRole.AGENCY_COORDINATOR])),
    session: AsyncSession = Depends(get_db_session),
) -> BrowserOfflineAuthorizationBundleResponse:
    return await build_browser_offline_authorization(
        group_id,
        request,
        response,
        current_user,
        session,
        dependencies=OfflineAuthorizationDependencies(
            settings=get_settings(),
            agency_id=_require_agency(current_user),
            resolve_runtime=resolve_browser_attendance_runtime,
            ensure_group=_ensure_group_assigned_to_coordinator,
            roster_revision=coordinator_roster_revision,
            sign_manifest=sign_offline_manifest,
            audit_repository=AuditLogRepository,
        ),
    )


@router.post(
    "/coordinator/attendance/discards",
    response_model=AttendanceDiscardBatchResponse,
    dependencies=[Depends(require_cookie_csrf)],
    status_code=status.HTTP_200_OK,
    summary="Synchronize privacy-safe offline discard evidence",
)
async def synchronize_attendance_discards(
    body: AttendanceDiscardBatchRequest,
    request: Request,
    current_user: User = Depends(require_role([UserRole.AGENCY_COORDINATOR])),
    session: AsyncSession = Depends(get_db_session),
) -> AttendanceDiscardBatchResponse:
    return await synchronize_browser_discard_groups(
        body,
        request,
        current_user,
        session,
        dependencies=DiscardSynchronizationDependencies(
            settings=get_settings(),
            agency_id=_require_agency(current_user),
            resolve_runtime=resolve_browser_attendance_runtime,
            ensure_group=_ensure_group_assigned_to_coordinator,
            get_session=_get_coordinator_attendance_session,
            discard_repository=AttendanceDiscardRepository,
            audit_repository=AuditLogRepository,
        ),
    )


__all__ = [
    "dispose_attendance_runtime",
    "provision_browser_offline_authorization",
    "register_browser_attendance_runtime",
    "revoke_current_browser_attendance_runtime",
    "resolve_browser_attendance_runtime",
    "router",
    "synchronize_attendance_discards",
]
