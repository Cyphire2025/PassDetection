"""Audited SuperAdmin controls for staged email-AI rollout."""

from __future__ import annotations

import uuid as uuid
from collections.abc import Sequence as Sequence
from dataclasses import dataclass as dataclass
from datetime import UTC as UTC
from datetime import datetime as datetime
from typing import Literal as Literal

from fastapi import APIRouter as APIRouter
from fastapi import Depends as Depends
from fastapi import HTTPException as HTTPException
from fastapi import Query as Query
from fastapi import status as status
from sqlalchemy import and_ as and_
from sqlalchemy import func as func
from sqlalchemy import or_ as or_
from sqlalchemy import select as select
from sqlalchemy.ext.asyncio import AsyncSession as AsyncSession
from sqlalchemy.sql.elements import ColumnElement as ColumnElement

from app.application.use_cases.email_integrations.rollout_policy import (
    lock_email_ai_policy_namespace as lock_email_ai_policy_namespace,
)
from app.core.config.settings import get_settings as get_settings
from app.domain.entities.entities import User as User
from app.domain.entities.entities import UserRole as UserRole
from app.infrastructure.database.email_ai_models import (
    EmailAiRolloutPolicyModel as EmailAiRolloutPolicyModel,
)
from app.infrastructure.database.email_models import EmailConnectionModel as EmailConnectionModel
from app.infrastructure.database.models import AgencyModel as AgencyModel
from app.infrastructure.database.models import UserModel as UserModel
from app.infrastructure.database.session import get_db_session as get_db_session
from app.infrastructure.repositories.audit_log_repository import (
    AuditLogRepository as AuditLogRepository,
)
from app.presentation.api.v1.routes.email_rollout_policy_mapping import (
    _load_policy_map as _load_policy_map,
)
from app.presentation.api.v1.routes.email_rollout_policy_mapping import (
    _policy_key as _policy_key,
)
from app.presentation.api.v1.routes.email_rollout_policy_mapping import (
    _policy_predicates as _policy_predicates,
)
from app.presentation.api.v1.routes.email_rollout_policy_mapping import (
    _target_key as _target_key,
)
from app.presentation.api.v1.routes.email_rollout_policy_mapping import (
    _target_response as _target_response,
)
from app.presentation.api.v1.routes.email_rollout_targets import (
    _OFFICE_ROLES as _OFFICE_ROLES,
)
from app.presentation.api.v1.routes.email_rollout_targets import (
    PolicyKey as PolicyKey,
)
from app.presentation.api.v1.routes.email_rollout_targets import (
    RolloutScope as RolloutScope,
)
from app.presentation.api.v1.routes.email_rollout_targets import (
    _RolloutTargetRow as _RolloutTargetRow,
)
from app.presentation.api.v1.routes.email_rollout_targets import (
    _target_rows as _target_rows,
)
from app.presentation.api.v1.schemas.email_ai_schemas import (
    EmailAiRolloutTargetResponse as EmailAiRolloutTargetResponse,
)
from app.presentation.api.v1.schemas.email_ai_schemas import (
    EmailAiRolloutTargetsResponse as EmailAiRolloutTargetsResponse,
)
from app.presentation.api.v1.schemas.email_ai_schemas import (
    UpdateEmailAiRolloutPolicyRequest as UpdateEmailAiRolloutPolicyRequest,
)
from app.presentation.dependencies.auth import require_role as require_role
from app.presentation.dependencies.csrf import require_cookie_csrf as require_cookie_csrf

router = APIRouter()
_super_admin = require_role([UserRole.SUPER_ADMIN])
_TARGET_LIMIT = 200


@router.get(
    "",
    response_model=EmailAiRolloutTargetsResponse,
)
async def list_email_ai_rollout_targets(
    scope_type: RolloutScope = Query(),
    search: str | None = Query(default=None, max_length=120),
    current_user: User = Depends(_super_admin),
    session: AsyncSession = Depends(get_db_session),
) -> EmailAiRolloutTargetsResponse:
    normalized_search = " ".join((search or "").split()).casefold()
    rows = await _target_rows(
        session,
        scope_type=scope_type,
        search=normalized_search,
        limit=_TARGET_LIMIT + 1,
        requesting_user_id=current_user.id,
    )
    truncated = len(rows) > _TARGET_LIMIT
    rows = rows[:_TARGET_LIMIT]
    policy_map = await _load_policy_map(session, rows)
    settings = get_settings()
    items = [
        _target_response(
            row,
            scope_type=scope_type,
            policy_map=policy_map,
            global_enabled=settings.email_ai_enabled,
        )
        for row in rows
    ]
    return EmailAiRolloutTargetsResponse(
        global_enabled=settings.email_ai_enabled,
        global_notifications_enabled=(settings.email_ai_notifications_enabled),
        scope_type=scope_type,
        items=items,
        truncated=truncated,
    )


@router.put(
    "",
    response_model=EmailAiRolloutTargetResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def update_email_ai_rollout_policy(
    payload: UpdateEmailAiRolloutPolicyRequest,
    current_user: User = Depends(_super_admin),
    session: AsyncSession = Depends(get_db_session),
) -> EmailAiRolloutTargetResponse:
    rows = await _target_rows(
        session,
        scope_type=payload.scope_type,
        agency_id=payload.agency_id,
        target_id=payload.target_id,
        limit=2,
        requesting_user_id=current_user.id,
    )
    if len(rows) != 1:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The rollout target was not found.",
        )
    target = rows[0]
    key = _target_key(target, payload.scope_type)
    if not await lock_email_ai_policy_namespace(
        session,
        agency_id=key[1],
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The rollout target was not found.",
        )
    policy = (
        await session.execute(
            select(EmailAiRolloutPolicyModel)
            .where(
                *_policy_predicates(
                    payload.scope_type,
                    agency_id=key[1],
                    owner_user_id=key[2],
                    connection_id=key[3],
                )
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if policy is None and payload.expected_updated_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This rollout control changed. Refresh before saving.",
        )
    if policy is not None and (
        payload.expected_updated_at is None
        or not _same_instant(
            policy.updated_at,
            payload.expected_updated_at,
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This rollout control changed. Refresh before saving.",
        )

    old_enabled = policy.enabled if policy is not None else None
    now = datetime.now(tz=UTC)
    if policy is None:
        policy = EmailAiRolloutPolicyModel(
            agency_id=key[1],
            owner_user_id=key[2],
            connection_id=key[3],
            scope_type=payload.scope_type,
            enabled=payload.enabled,
            updated_by_user_id=current_user.id,
            created_at=now,
            updated_at=now,
        )
        session.add(policy)
    else:
        policy.enabled = payload.enabled
        policy.updated_by_user_id = current_user.id
        policy.updated_at = now
    await session.flush()
    await AuditLogRepository(session).record(
        action="email_ai_rollout_policy_updated",
        entity_type="email_ai_rollout_policy",
        agency_id=policy.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        entity_id=str(policy.id),
        metadata={
            "scope_type": policy.scope_type,
            "target_id": str(payload.target_id),
            "owner_user_id": (
                str(policy.owner_user_id) if policy.owner_user_id is not None else None
            ),
            "connection_id": (
                str(policy.connection_id) if policy.connection_id is not None else None
            ),
            "old_enabled": old_enabled,
            "new_enabled": policy.enabled,
        },
    )
    policy_map = await _load_policy_map(session, [target])
    return _target_response(
        target,
        scope_type=payload.scope_type,
        policy_map=policy_map,
        global_enabled=get_settings().email_ai_enabled,
    )


def _same_instant(left: datetime, right: datetime) -> bool:
    return _aware_utc(left) == _aware_utc(right)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
