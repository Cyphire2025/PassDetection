"""Browser runtime continuity and privacy-safe offline discard receipts."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.coordinator_roster_revision import (
    coordinator_roster_revision,
)
from app.core.config.settings import get_settings
from app.core.security.mobile_offline_lease import sign_offline_manifest
from app.domain.entities.entities import (
    OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES,
    User,
    UserRole,
)
from app.infrastructure.database.models import (
    AttendanceSessionModel,
    ClientGroupModel,
    PassengerQRTokenModel,
    PassportSubmissionModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.attendance_discard_repository import (
    AttendanceDiscardInput,
    AttendanceDiscardRepository,
)
from app.infrastructure.repositories.attendance_runtime_repository import (
    AttendanceRuntimeError,
    AttendanceRuntimeRepository,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.routes.tour_operations import (
    _ensure_group_assigned_to_coordinator,
    _get_coordinator_attendance_session,
    _require_agency,
)
from app.presentation.api.v1.schemas.attendance_runtime_schemas import (
    AttendanceDiscardBatchRequest,
    AttendanceDiscardBatchResponse,
    AttendanceDiscardItemRequest,
    AttendanceDiscardItemResponse,
    AttendanceRuntimeDispositionRequest,
    AttendanceRuntimeDispositionResponse,
    AttendanceRuntimeRegistrationRequest,
    AttendanceRuntimeRegistrationResponse,
    BrowserOfflineAuthorizationBundleResponse,
    BrowserOfflineAuthorizationPayload,
    BrowserOfflineAuthorizedPassenger,
    BrowserOfflineAuthorizedSession,
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
    await _ensure_group_assigned_to_coordinator(
        session,
        agency_id,
        group_id,
        current_user.id,
    )
    group = await session.scalar(
        select(ClientGroupModel).where(
            ClientGroupModel.id == group_id,
            ClientGroupModel.agency_id == agency_id,
            ClientGroupModel.deleted_at.is_(None),
            ClientGroupModel.status != "deleted",
        )
    )
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    attendance_sessions = list(
        (
            await session.execute(
                select(AttendanceSessionModel)
                .where(
                    AttendanceSessionModel.agency_id == agency_id,
                    AttendanceSessionModel.group_id == group_id,
                    AttendanceSessionModel.id == AttendanceSessionModel.canonical_session_id,
                    AttendanceSessionModel.status == "active",
                )
                .order_by(
                    AttendanceSessionModel.scheduled_starts_at,
                    AttendanceSessionModel.id,
                )
                .limit(201)
            )
        ).scalars()
    )
    if not attendance_sessions:
        raise _offline_readiness_error(
            "OFFLINE_ACTIVITY_NOT_AVAILABLE",
            "No active attendance activity is available for offline scanning.",
        )
    if len(attendance_sessions) > 200:
        raise _offline_readiness_error(
            "OFFLINE_ACTIVITY_LIMIT_EXCEEDED",
            "Too many active attendance activities are configured for offline use.",
        )
    scheduled_sessions: list[tuple[AttendanceSessionModel, datetime, datetime]] = []
    for item in attendance_sessions:
        scheduled_starts_at = item.scheduled_starts_at
        scheduled_ends_at = item.scheduled_ends_at
        if scheduled_starts_at is None or scheduled_ends_at is None:
            raise _offline_readiness_error(
                "ATTENDANCE_SCHEDULE_REQUIRED",
                "Every active attendance activity needs an explicit start and end time.",
            )
        scheduled_sessions.append((item, scheduled_starts_at, scheduled_ends_at))

    approved_count = int(
        await session.scalar(
            select(func.count(PassportSubmissionModel.id)).where(
                PassportSubmissionModel.agency_id == agency_id,
                PassportSubmissionModel.group_id == group_id,
                PassportSubmissionModel.status.in_(OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES),
            )
        )
        or 0
    )
    now = datetime.now(tz=UTC)
    passenger_rows = list(
        (
            await session.execute(
                select(
                    PassportSubmissionModel.id,
                    PassportSubmissionModel.client_name,
                    PassengerQRTokenModel.token_hash,
                    PassengerQRTokenModel.token_version,
                    PassengerQRTokenModel.expires_at,
                )
                .join(
                    PassengerQRTokenModel,
                    PassengerQRTokenModel.passenger_id == PassportSubmissionModel.id,
                )
                .where(
                    PassportSubmissionModel.agency_id == agency_id,
                    PassportSubmissionModel.group_id == group_id,
                    PassportSubmissionModel.status.in_(
                        OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES
                    ),
                    PassengerQRTokenModel.agency_id == agency_id,
                    PassengerQRTokenModel.is_active.is_(True),
                    PassengerQRTokenModel.revoked_at.is_(None),
                    PassengerQRTokenModel.expires_at > now,
                    func.length(PassengerQRTokenModel.token_hash) == 64,
                )
                .order_by(PassportSubmissionModel.id)
                .limit(2_001)
            )
        ).all()
    )
    if approved_count == 0 or len(passenger_rows) != approved_count:
        raise _offline_readiness_error(
            "OFFLINE_ROSTER_INCOMPLETE",
            "The approved roster does not yet have complete active QR authorization.",
        )
    if len(passenger_rows) > 2_000:
        raise _offline_readiness_error(
            "OFFLINE_ROSTER_LIMIT_EXCEEDED",
            "The roster exceeds the supported offline authorization size.",
        )

    active_key_id = settings.mobile.offline_lease_active_kid
    if not active_key_id:
        raise _offline_readiness_error(
            "OFFLINE_SIGNING_UNAVAILABLE",
            "Offline authorization is temporarily unavailable.",
            service_unavailable=True,
        )
    suspension_seconds = min(
        settings.browser_offline_max_suspension_seconds,
        settings.browser_offline_authorization_ttl_minutes * 60,
    )
    expires_at = min(
        now + timedelta(seconds=suspension_seconds),
        max(scheduled_ends_at for _, _, scheduled_ends_at in scheduled_sessions),
    )
    if expires_at <= now:
        raise _offline_readiness_error(
            "OFFLINE_ACTIVITY_OUTSIDE_WINDOW",
            "The configured attendance activities have already ended.",
        )
    payload = BrowserOfflineAuthorizationPayload(
        coordinator_user_id=current_user.id,
        expires_at=expires_at,
        group_id=group.id,
        group_label=group.name,
        issued_at=now,
        key_id=active_key_id,
        max_suspension_seconds=suspension_seconds,
        not_before=now - timedelta(seconds=30),
        passengers=[
            BrowserOfflineAuthorizedPassenger(
                id=row.id,
                label=row.client_name,
                token_hash=row.token_hash,
                token_valid_until=row.expires_at,
                token_version=row.token_version,
            )
            for row in passenger_rows
        ],
        roster_revision=await coordinator_roster_revision(
            session,
            agency_id=agency_id,
            group_id=group_id,
        ),
        server_time=now,
        sessions=[
            BrowserOfflineAuthorizedSession(
                id=item.id,
                label=item.name,
                scheduled_starts_at=scheduled_starts_at,
                scheduled_ends_at=scheduled_ends_at,
            )
            for item, scheduled_starts_at, scheduled_ends_at in scheduled_sessions
        ],
        tenant_id=agency_id,
    )
    signed = sign_offline_manifest(payload.model_dump(mode="json"))
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    await AuditLogRepository(session).record(
        action="attendance.offline_authorization_provisioned",
        entity_type="attendance_runtime",
        agency_id=agency_id,
        user_id=current_user.id,
        entity_id=str(runtime.id),
        metadata={
            "group_id": str(group_id),
            "roster_revision": payload.roster_revision,
            "passenger_count": len(payload.passengers),
            "session_count": len(payload.sessions),
            "expires_at": expires_at.isoformat(),
            "key_id": signed.key_id,
        },
    )
    return BrowserOfflineAuthorizationBundleResponse(
        key_id=signed.key_id,
        payload=signed.payload,
        public_key=signed.public_key,
        signature=signed.signature,
    )


def _offline_readiness_error(
    code: str,
    message: str,
    *,
    service_unavailable: bool = False,
) -> HTTPException:
    return HTTPException(
        status_code=(
            status.HTTP_503_SERVICE_UNAVAILABLE if service_unavailable else status.HTTP_409_CONFLICT
        ),
        detail={"code": code, "message": message},
        headers={"Cache-Control": "private, no-store", "Retry-After": "30"},
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

    grouped: dict[tuple[uuid.UUID, uuid.UUID], list[AttendanceDiscardItemRequest]] = defaultdict(
        list
    )
    for item in body.items:
        grouped[(item.group_id, item.session_id)].append(item)

    responses: dict[uuid.UUID, AttendanceDiscardItemResponse] = {}
    accepted_count = 0
    already_applied_count = 0
    rejected_count = 0
    for (group_id, session_id), items in grouped.items():
        try:
            await _ensure_group_assigned_to_coordinator(
                session,
                agency_id,
                group_id,
                current_user.id,
            )
            attendance_session = await _get_coordinator_attendance_session(
                session,
                agency_id,
                session_id,
                current_user.id,
            )
            if attendance_session.group_id != group_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
            results = await AttendanceDiscardRepository(session).record_batch(
                agency_id=agency_id,
                group_id=group_id,
                session_id=attendance_session.id,
                coordinator_user_id=current_user.id,
                runtime_registration_id=runtime.id,
                items=tuple(
                    AttendanceDiscardInput(
                        discard_event_id=item.discard_event_id,
                        scan_reference=item.scan_reference,
                        reason_category=item.reason_category,
                        captured_at=item.captured_at,
                        discarded_at=item.discarded_at,
                    )
                    for item in items
                ),
                retention_days=settings.attendance_discard_retention_days,
            )
        except (HTTPException, AttendanceRuntimeError, ValueError):
            for item in items:
                responses[item.discard_event_id] = AttendanceDiscardItemResponse(
                    discard_event_id=item.discard_event_id,
                    status="rejected",
                    reason_code="DISCARD_SCOPE_NOT_AUTHORIZED",
                )
                rejected_count += 1
            continue
        for result in results:
            responses[result.discard_event_id] = AttendanceDiscardItemResponse(
                discard_event_id=result.discard_event_id,
                status=result.status,
                received_at=result.received_at,
            )
            if result.status == "accepted":
                accepted_count += 1
            else:
                already_applied_count += 1

    await AuditLogRepository(session).record(
        action="attendance.discard_evidence_synchronized",
        entity_type="attendance_runtime",
        agency_id=agency_id,
        user_id=current_user.id,
        entity_id=str(runtime.id),
        result="blocked" if rejected_count and not accepted_count else "success",
        metadata={
            "accepted_count": accepted_count,
            "already_applied_count": already_applied_count,
            "rejected_count": rejected_count,
            "runtime_kind": runtime.runtime_kind,
            "reason_categories": sorted({item.reason_category for item in body.items}),
        },
    )
    return AttendanceDiscardBatchResponse(
        items=[responses[item.discard_event_id] for item in body.items]
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
