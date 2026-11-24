"""Locked platform policy reads and revision-checked updates."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.platform_policies import PLATFORM_SETTINGS_KEY, PlatformPolicies
from app.domain.entities.entities import (
    User,
    UserRole,
)
from app.infrastructure.database.models import (
    PlatformSettingModel,
    PlatformSettingsValue,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.schemas.operations_schemas import (
    PlatformSettingsResponse,
    UpdatePlatformSettingsRequest,
)
from app.presentation.dependencies.auth import require_recent_mfa, require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()
DEFAULT_PLATFORM_SETTINGS = PlatformPolicies().as_dict()
PLATFORM_SETTINGS_REVISION_CONFLICT = "PLATFORM_SETTINGS_REVISION_CONFLICT"


@router.get(
    "/settings",
    response_model=PlatformSettingsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get editable platform settings",
)
async def get_platform_settings(
    current_user: User = Depends(require_role([UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN])),
    session: AsyncSession = Depends(get_db_session),
) -> PlatformSettingsResponse:
    settings = await _load_platform_settings(session)
    return settings


@router.put(
    "/settings",
    response_model=PlatformSettingsResponse,
    status_code=status.HTTP_200_OK,
    summary="Update editable platform settings",
    dependencies=[Depends(require_cookie_csrf), Depends(require_recent_mfa)],
)
async def update_platform_settings(
    body: UpdatePlatformSettingsRequest,
    current_user: User = Depends(require_role([UserRole.SUPER_ADMIN])),
    session: AsyncSession = Depends(get_db_session),
) -> PlatformSettingsResponse:
    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only platform administrators can update global settings",
        )
    result = await session.execute(
        select(PlatformSettingModel)
        .where(PlatformSettingModel.key == PLATFORM_SETTINGS_KEY)
        .with_for_update()
    )
    row = result.scalar_one_or_none()
    if row is None:
        if body.expected_updated_at is not None:
            raise _platform_settings_revision_conflict(current_updated_at=None)
    elif body.expected_updated_at is None or not _same_platform_settings_revision(
        row.updated_at,
        body.expected_updated_at,
    ):
        raise _platform_settings_revision_conflict(current_updated_at=row.updated_at)

    value = PlatformSettingsValue(
        platform_name=body.platform_name,
        require_client_email=body.require_client_email,
        require_client_phone=body.require_client_phone,
        duplicate_contact_policy=body.duplicate_contact_policy,
        default_group_status=body.default_group_status,
        auto_archive_closed_groups_days=body.auto_archive_closed_groups_days,
        passport_data_retention_days=body.passport_data_retention_days,
        mrz_review_threshold=body.mrz_review_threshold,
        allow_manager_group_creation=body.allow_manager_group_creation,
        audit_log_retention_days=body.audit_log_retention_days,
    )
    if row:
        row.value = value
    else:
        row = PlatformSettingModel(key=PLATFORM_SETTINGS_KEY, value=value)
        session.add(row)
    await session.flush()
    await session.refresh(row)

    await AuditLogRepository(session).record(
        action="platform_settings_updated",
        entity_type="platform_settings",
        agency_id=None if current_user.role == UserRole.SUPER_ADMIN else current_user.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        entity_id=PLATFORM_SETTINGS_KEY,
        metadata=dict(value),
    )
    return PlatformSettingsResponse.model_validate({**row.value, "updated_at": row.updated_at})


def _same_platform_settings_revision(current: datetime, expected: datetime) -> bool:
    """Compare exact instants without tolerances or string-format ambiguity."""

    normalized_current = (
        current.replace(tzinfo=UTC) if current.utcoffset() is None else current.astimezone(UTC)
    )
    return normalized_current == expected.astimezone(UTC)


def _platform_settings_revision_conflict(
    *,
    current_updated_at: datetime | None,
) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": PLATFORM_SETTINGS_REVISION_CONFLICT,
            "message": "Platform settings changed. Reload the latest values before saving.",
            "current_updated_at": (
                current_updated_at.isoformat() if current_updated_at is not None else None
            ),
        },
    )


async def _load_platform_settings(session: AsyncSession) -> PlatformSettingsResponse:
    result = await session.execute(
        select(PlatformSettingModel).where(PlatformSettingModel.key == PLATFORM_SETTINGS_KEY)
    )
    row = result.scalar_one_or_none()
    if not row:
        return PlatformSettingsResponse(**DEFAULT_PLATFORM_SETTINGS)
    return PlatformSettingsResponse(
        **{**DEFAULT_PLATFORM_SETTINGS, **row.value}, updated_at=row.updated_at
    )
