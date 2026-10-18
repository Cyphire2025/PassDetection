"""Superadmin-only assistant configuration, without returning provider secrets."""

from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.assistant.contracts import AssistantError
from app.application.assistant.settings_contracts import (
    AssistantConnectionCheck,
    AssistantSettingsResponse,
    AssistantSettingsUpdate,
)
from app.application.assistant.usage_contracts import AssistantUsageResponse
from app.domain.entities.entities import User, UserRole
from app.infrastructure.assistant.gemini_provider import GEMINI_ORIGIN
from app.infrastructure.assistant.settings_store import (
    OFFICE_ROLES,
    AssistantSnapshot,
    load_snapshot,
    provider_key,
    save_settings,
)
from app.infrastructure.assistant.usage import usage_snapshot
from app.infrastructure.database.models import UserModel
from app.infrastructure.database.session import get_db_session
from app.presentation.dependencies.auth import require_recent_mfa, require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()
PRIVATE = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


def _http(exc: AssistantError) -> HTTPException:
    return HTTPException(exc.status, detail={"code": exc.code, "message": exc.message})


async def _response(
    session: AsyncSession, snapshot: AssistantSnapshot
) -> AssistantSettingsResponse:
    credentials = {}
    for provider in ("gemini", "openai"):
        try:
            credentials[provider] = bool(provider_key(snapshot, provider).get_secret_value())
        except AssistantError:
            credentials[provider] = False
    users = (
        (
            await session.scalars(
                select(UserModel).where(UserModel.id.in_(snapshot.configuration.allowed_user_ids))
            )
        ).all()
        if snapshot.configuration.allowed_user_ids
        else []
    )
    return AssistantSettingsResponse(
        revision=snapshot.revision,
        configuration=snapshot.configuration,
        credentials=credentials,
        granted_users=[
            {
                "id": str(user.id),
                "name": user.full_name,
                "email": user.email,
                "role": str(user.role),
            }
            for user in users
        ],
    )


@router.get("/settings", response_model=AssistantSettingsResponse)
async def get_ai_settings(
    response: Response,
    user: User = Depends(require_role([UserRole.SUPER_ADMIN])),
    session: AsyncSession = Depends(get_db_session),
) -> AssistantSettingsResponse:
    response.headers.update(PRIVATE)
    try:
        return await _response(session, await load_snapshot(session))
    except AssistantError as exc:
        raise _http(exc) from None


@router.put(
    "/settings",
    response_model=AssistantSettingsResponse,
    dependencies=[Depends(require_cookie_csrf), Depends(require_recent_mfa)],
)
async def update_ai_settings(
    body: AssistantSettingsUpdate,
    response: Response,
    user: User = Depends(require_role([UserRole.SUPER_ADMIN])),
    session: AsyncSession = Depends(get_db_session),
) -> AssistantSettingsResponse:
    response.headers.update(PRIVATE)
    try:
        after = await save_settings(session, user, body)
        return await _response(session, after)
    except AssistantError as exc:
        raise _http(exc) from None


@router.get("/settings/usage", response_model=AssistantUsageResponse)
async def assistant_usage(
    response: Response,
    user: User = Depends(require_role([UserRole.SUPER_ADMIN])),
    session: AsyncSession = Depends(get_db_session),
) -> AssistantUsageResponse:
    response.headers.update(PRIVATE)
    try:
        limits = (await load_snapshot(session)).configuration.usage_limits
        await session.rollback()
        return await usage_snapshot(user.id, limits)
    except AssistantError as exc:
        raise _http(exc) from None


@router.get("/settings/people")
async def assistant_people(
    response: Response,
    q: str = Query("", max_length=120),
    user: User = Depends(require_role([UserRole.SUPER_ADMIN])),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    response.headers.update(PRIVATE)
    statement = select(UserModel).where(
        UserModel.is_active.is_(True),
        UserModel.agency_id.is_not(None),
        UserModel.role.in_([role.value for role in OFFICE_ROLES]),
    )
    if q.strip():
        term = "%" + q.strip().replace("%", "\\%").replace("_", "\\_") + "%"
        statement = statement.where(
            or_(
                UserModel.full_name.ilike(term, escape="\\"),
                UserModel.email.ilike(term, escape="\\"),
            )
        )
    users = (
        await session.scalars(statement.order_by(UserModel.full_name, UserModel.id).limit(31))
    ).all()
    return {
        "items": [
            {
                "id": str(item.id),
                "name": item.full_name,
                "email": item.email,
                "role": str(item.role),
            }
            for item in users[:30]
        ],
        "has_more": len(users) > 30,
    }


@router.post(
    "/settings/check", dependencies=[Depends(require_cookie_csrf), Depends(require_recent_mfa)]
)
async def check_ai_connection(
    body: AssistantConnectionCheck,
    response: Response,
    user: User = Depends(require_role([UserRole.SUPER_ADMIN])),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str | bool]:
    response.headers.update(PRIVATE)
    try:
        snapshot = await load_snapshot(session)
        key = provider_key(snapshot, body.provider)
        if not key.get_secret_value():
            raise AssistantError("setup_pending", "Save this provider's API key first.", 422)
        await session.rollback()
        origin = GEMINI_ORIGIN if body.provider == "gemini" else "https://api.openai.com/v1"
        path = "/models/" + (
            snapshot.configuration.gemini_model if body.provider == "gemini" else "gpt-6-luna"
        )
        headers = (
            {"x-goog-api-key": key.get_secret_value()}
            if body.provider == "gemini"
            else {"Authorization": "Bearer " + key.get_secret_value()}
        )
        async with httpx.AsyncClient(
            base_url=origin, headers=headers, timeout=15, follow_redirects=False
        ) as client:
            result = await client.get(path)
        if result.status_code != 200:
            raise AssistantError(
                "provider_configuration",
                "The provider did not accept this key or model. Check its API restrictions, project and billing.",
                422,
            )
        return {"ok": True, "message": "API key accepted."}
    except AssistantError as exc:
        raise _http(exc) from None
    except httpx.HTTPError:
        raise HTTPException(
            503, "The provider could not be reached. Your saved settings are unchanged."
        ) from None
