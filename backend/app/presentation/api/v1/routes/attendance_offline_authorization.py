"""Signed browser roster orchestration after authenticated runtime admission."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.infrastructure.database.models import ClientGroupModel
from app.presentation.api.v1.routes.attendance_offline_sources import (
    _offline_readiness_error,
    approved_offline_passenger_count,
    load_authorized_offline_passengers,
    load_scheduled_offline_activities,
)
from app.presentation.api.v1.routes.attendance_runtime_dependencies import (
    OfflineAuthorizationDependencies,
)
from app.presentation.api.v1.schemas.attendance_runtime_schemas import (
    BrowserOfflineAuthorizationBundleResponse,
    BrowserOfflineAuthorizationPayload,
    BrowserOfflineAuthorizedPassenger,
    BrowserOfflineAuthorizedSession,
)


async def build_browser_offline_authorization(
    group_id: uuid.UUID,
    request: Request,
    response: Response,
    current_user: User,
    session: AsyncSession,
    *,
    dependencies: OfflineAuthorizationDependencies,
) -> BrowserOfflineAuthorizationBundleResponse:
    settings = dependencies.settings
    agency_id = dependencies.agency_id
    runtime = await dependencies.resolve_runtime(
        request,
        session=session,
        agency_id=agency_id,
        coordinator_user_id=current_user.id,
        required=True,
    )
    if runtime is None:  # pragma: no cover - required=True is exhaustive
        raise RuntimeError("Attendance runtime resolution was incomplete")
    await dependencies.ensure_group(
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

    scheduled_sessions = await load_scheduled_offline_activities(
        session, agency_id=agency_id, group_id=group_id
    )
    approved_count = await approved_offline_passenger_count(
        session, agency_id=agency_id, group_id=group_id
    )
    now = datetime.now(tz=UTC)
    passenger_rows = await load_authorized_offline_passengers(
        session, agency_id=agency_id, group_id=group_id, now=now, approved_count=approved_count
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
        roster_revision=await dependencies.roster_revision(
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
    signed = dependencies.sign_manifest(payload.model_dump(mode="json"))
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    await dependencies.audit_repository(session).record(
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
