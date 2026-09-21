"""Global sender template overrides with optimistic concurrency and audit history."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import PlatformSettingModel, PlatformSettingsValue
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.whatsapp.template_settings import (
    TEMPLATE_REGISTRY,
    TEMPLATE_SETTINGS_KEY,
    TEMPLATE_SETTINGS_MEMO,
    TemplateSettingsSnapshot,
    environment_template_name,
    load_template_settings,
    snapshot_from_row,
    template_language,
)
from app.presentation.api.v1.schemas.whatsapp_template_settings_schemas import (
    WhatsAppTemplateOverrideRequest,
    WhatsAppTemplateSettingResponse,
    WhatsAppTemplateSettingsResponse,
)
from app.presentation.dependencies.auth import require_recent_mfa, require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


def _response(snapshot: TemplateSettingsSnapshot, user: User) -> WhatsAppTemplateSettingsResponse:
    return WhatsAppTemplateSettingsResponse(
        revision=snapshot.revision, can_edit=user.role == UserRole.SUPER_ADMIN,
        updated_at=snapshot.updated_at,
        templates=[WhatsAppTemplateSettingResponse(
            key=item.key, label=item.label,
            environment_name=environment_template_name(item.key),
            override_name=snapshot.overrides.get(item.key), effective_name=snapshot.name(item.key),
            language=template_language(item.key),
            source="override" if item.key in snapshot.overrides else "environment",
            contract_description=item.contract_description,
        ) for item in TEMPLATE_REGISTRY],
    )


def _conflict(revision: int) -> HTTPException:
    return HTTPException(409, detail={
        "code": "WHATSAPP_TEMPLATE_REVISION_CONFLICT",
        "message": "WhatsApp template settings changed. Reload the latest names before saving.",
        "current_revision": revision,
    })


@router.get("/whatsapp-templates", response_model=WhatsAppTemplateSettingsResponse)
async def get_whatsapp_template_settings(
    response: Response,
    current_user: User = Depends(require_role([UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN])),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppTemplateSettingsResponse:
    response.headers["Cache-Control"] = "private, no-store"
    return _response(await load_template_settings(session), current_user)


@router.put(
    "/whatsapp-templates", response_model=WhatsAppTemplateSettingsResponse,
    dependencies=[Depends(require_cookie_csrf), Depends(require_recent_mfa)],
)
async def update_whatsapp_template_settings(
    body: WhatsAppTemplateOverrideRequest,
    response: Response,
    current_user: User = Depends(require_role([UserRole.SUPER_ADMIN])),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppTemplateSettingsResponse:
    result = await session.execute(
        select(PlatformSettingModel).where(PlatformSettingModel.key == TEMPLATE_SETTINGS_KEY)
        .with_for_update().execution_options(populate_existing=True)
    )
    row = result.scalar_one_or_none()
    before = snapshot_from_row(row)
    if before.revision != body.expected_revision:
        raise _conflict(before.revision)
    overrides = dict(before.overrides)
    for key, name in body.overrides.items():
        if name is None:
            overrides.pop(key, None)
        else:
            overrides[key] = name
    if overrides == before.overrides:
        response.headers["Cache-Control"] = "private, no-store"
        return _response(before, current_user)
    now = datetime.now(tz=UTC)
    value = PlatformSettingsValue(
        whatsapp_template_revision=before.revision + 1, whatsapp_template_overrides=overrides,
    )
    if row is None:
        inserted = await session.execute(
            pg_insert(PlatformSettingModel).values(key=TEMPLATE_SETTINGS_KEY, value=value, updated_at=now)
            .on_conflict_do_nothing(index_elements=[PlatformSettingModel.key])
            .returning(PlatformSettingModel.key)
        )
        if inserted.scalar_one_or_none() is None:
            winner = (await session.execute(select(PlatformSettingModel).where(
                PlatformSettingModel.key == TEMPLATE_SETTINGS_KEY,
            ).execution_options(populate_existing=True))).scalar_one()
            raise _conflict(snapshot_from_row(winner).revision)
    else:
        row.value = value
        row.updated_at = now
        await session.flush()
    after = TemplateSettingsSnapshot(before.revision + 1, now, overrides)
    await AuditLogRepository(session).record(
        action="whatsapp_template_settings_updated", entity_type="platform_settings",
        entity_id=TEMPLATE_SETTINGS_KEY, agency_id=None,
        user_id=current_user.id, actor_email=current_user.email,
        metadata={
            "previous_revision": before.revision, "revision": after.revision,
            "before_overrides": before.overrides, "after_overrides": after.overrides,
            "before_effective_names": {item.key: before.name(item.key) for item in TEMPLATE_REGISTRY},
            "after_effective_names": {item.key: after.name(item.key) for item in TEMPLATE_REGISTRY},
        },
    )
    await session.commit()
    session.info[TEMPLATE_SETTINGS_MEMO] = after
    response.headers["Cache-Control"] = "private, no-store"
    return _response(after, current_user)
