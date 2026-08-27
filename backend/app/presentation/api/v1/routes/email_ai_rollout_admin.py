"""Audited SuperAdmin controls for staged email-AI rollout."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.application.use_cases.email_integrations.rollout_policy import (
    lock_email_ai_policy_namespace,
)
from app.core.config.settings import get_settings
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.email_ai_models import (
    EmailAiRolloutPolicyModel,
)
from app.infrastructure.database.email_models import EmailConnectionModel
from app.infrastructure.database.models import AgencyModel, UserModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import (
    AuditLogRepository,
)
from app.presentation.api.v1.schemas.email_ai_schemas import (
    EmailAiRolloutTargetResponse,
    EmailAiRolloutTargetsResponse,
    UpdateEmailAiRolloutPolicyRequest,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()
_super_admin = require_role([UserRole.SUPER_ADMIN])
_TARGET_LIMIT = 200
RolloutScope = Literal["agency", "user", "connection"]
PolicyKey = tuple[str, uuid.UUID, uuid.UUID | None, uuid.UUID | None]
_OFFICE_ROLES = {
    UserRole.SUPER_ADMIN.value,
    UserRole.AGENCY_ADMIN.value,
    UserRole.AGENCY_MANAGER.value,
    UserRole.AGENCY_STAFF.value,
}


@dataclass(frozen=True, slots=True)
class _RolloutTargetRow:
    agency_id: uuid.UUID
    target_id: uuid.UUID
    owner_user_id: uuid.UUID | None
    connection_id: uuid.UUID | None
    label: str
    detail: str


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
        global_notifications_enabled=(
            settings.email_ai_notifications_enabled
        ),
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
                str(policy.owner_user_id)
                if policy.owner_user_id is not None
                else None
            ),
            "connection_id": (
                str(policy.connection_id)
                if policy.connection_id is not None
                else None
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


async def _target_rows(
    session: AsyncSession,
    *,
    scope_type: RolloutScope,
    limit: int,
    search: str = "",
    agency_id: uuid.UUID | None = None,
    target_id: uuid.UUID | None = None,
    requesting_user_id: uuid.UUID | None = None,
) -> list[_RolloutTargetRow]:
    if scope_type == "agency":
        agency_statement = select(
            AgencyModel.id,
            AgencyModel.name,
            AgencyModel.email,
        ).where(AgencyModel.is_active.is_(True))
        if agency_id is not None:
            agency_statement = agency_statement.where(AgencyModel.id == agency_id)
        if target_id is not None:
            agency_statement = agency_statement.where(AgencyModel.id == target_id)
        if search:
            agency_statement = agency_statement.where(
                or_(
                    func.lower(AgencyModel.name).contains(search),
                    func.lower(AgencyModel.email).contains(search),
                )
            )
        agency_rows = (
            await session.execute(
                agency_statement.order_by(AgencyModel.name.asc()).limit(limit)
            )
        ).tuples()
        return [
            _RolloutTargetRow(
                agency_id=row_agency_id,
                target_id=row_agency_id,
                owner_user_id=None,
                connection_id=None,
                label=name,
                detail=email,
            )
            for row_agency_id, name, email in agency_rows
        ]

    if scope_type == "user":
        user_statement = select(
            UserModel.agency_id,
            UserModel.id,
            UserModel.full_name,
            UserModel.email,
        ).where(
            UserModel.is_active.is_(True),
            UserModel.agency_id.is_not(None),
            UserModel.role.in_(_OFFICE_ROLES),
        )
        if agency_id is not None:
            user_statement = user_statement.where(UserModel.agency_id == agency_id)
        if target_id is not None:
            user_statement = user_statement.where(UserModel.id == target_id)
        if search:
            user_statement = user_statement.where(
                or_(
                    func.lower(UserModel.full_name).contains(search),
                    func.lower(UserModel.email).contains(search),
                )
            )
        user_rows = (
            await session.execute(
                user_statement.order_by(
                    UserModel.full_name.asc(),
                    UserModel.id.asc(),
                ).limit(limit)
            )
        ).tuples()
        targets: list[_RolloutTargetRow] = []
        for row_agency_id, user_id, full_name, email in user_rows:
            # The SQL predicate is authoritative; this explicit check also
            # preserves a fail-closed boundary during compatible rolling states.
            if row_agency_id is None:
                continue
            targets.append(
                _RolloutTargetRow(
                    agency_id=row_agency_id,
                    target_id=user_id,
                    owner_user_id=user_id,
                    connection_id=None,
                    label=full_name,
                    detail=email,
                )
            )
        return targets

    connection_statement = (
        select(
            EmailConnectionModel.agency_id,
            EmailConnectionModel.id,
            EmailConnectionModel.owner_user_id,
            EmailConnectionModel.email_address,
            UserModel.full_name,
            EmailConnectionModel.provider,
        )
        .join(UserModel, UserModel.id == EmailConnectionModel.owner_user_id)
        .where(
            EmailConnectionModel.owner_user_id == requesting_user_id,
            EmailConnectionModel.status != "disconnected",
            UserModel.is_active.is_(True),
            UserModel.role.in_(_OFFICE_ROLES),
        )
    )
    if agency_id is not None:
        connection_statement = connection_statement.where(
            EmailConnectionModel.agency_id == agency_id
        )
    if target_id is not None:
        connection_statement = connection_statement.where(
            EmailConnectionModel.id == target_id
        )
    if search:
        connection_statement = connection_statement.where(
            or_(
                func.lower(EmailConnectionModel.email_address).contains(
                    search
                ),
                func.lower(UserModel.full_name).contains(search),
            )
        )
    connection_rows = (
        await session.execute(
            connection_statement.order_by(
                EmailConnectionModel.email_address.asc(),
                EmailConnectionModel.id.asc(),
            ).limit(limit)
        )
    ).tuples()
    return [
        _RolloutTargetRow(
            agency_id=row_agency_id,
            target_id=connection_id,
            owner_user_id=owner_user_id,
            connection_id=connection_id,
            label=email_address,
            detail=f"{owner_name} · {provider}",
        )
        for (
            row_agency_id,
            connection_id,
            owner_user_id,
            email_address,
            owner_name,
            provider,
        ) in connection_rows
    ]


async def _load_policy_map(
    session: AsyncSession,
    rows: Sequence[_RolloutTargetRow],
) -> dict[PolicyKey, EmailAiRolloutPolicyModel]:
    if not rows:
        return {}
    agency_ids = {row.agency_id for row in rows}
    owner_user_ids = {
        row.owner_user_id
        for row in rows
        if row.owner_user_id is not None
    }
    connection_ids = {
        row.connection_id
        for row in rows
        if row.connection_id is not None
    }
    scope_predicates = [
        and_(
            EmailAiRolloutPolicyModel.scope_type == "agency",
            EmailAiRolloutPolicyModel.owner_user_id.is_(None),
            EmailAiRolloutPolicyModel.connection_id.is_(None),
        )
    ]
    if owner_user_ids:
        scope_predicates.append(
            and_(
                EmailAiRolloutPolicyModel.scope_type == "user",
                EmailAiRolloutPolicyModel.owner_user_id.in_(
                    owner_user_ids
                ),
                EmailAiRolloutPolicyModel.connection_id.is_(None),
            )
        )
    if connection_ids:
        scope_predicates.append(
            and_(
                EmailAiRolloutPolicyModel.scope_type == "connection",
                EmailAiRolloutPolicyModel.connection_id.in_(
                    connection_ids
                ),
            )
        )
    policies = list(
        (
            await session.execute(
                select(EmailAiRolloutPolicyModel).where(
                    EmailAiRolloutPolicyModel.agency_id.in_(agency_ids),
                    or_(*scope_predicates),
                )
            )
        ).scalars()
    )
    return {
        _policy_key(
            policy.scope_type,
            agency_id=policy.agency_id,
            owner_user_id=policy.owner_user_id,
            connection_id=policy.connection_id,
        ): policy
        for policy in policies
    }


def _target_response(
    row: _RolloutTargetRow,
    *,
    scope_type: RolloutScope,
    policy_map: dict[PolicyKey, EmailAiRolloutPolicyModel],
    global_enabled: bool,
) -> EmailAiRolloutTargetResponse:
    key = _target_key(row, scope_type)
    direct_policy = policy_map.get(key)
    chain = [
        policy_map.get(
            _policy_key(
                "agency",
                agency_id=row.agency_id,
                owner_user_id=None,
                connection_id=None,
            )
        )
    ]
    if row.owner_user_id is not None:
        chain.append(
            policy_map.get(
                _policy_key(
                    "user",
                    agency_id=row.agency_id,
                    owner_user_id=row.owner_user_id,
                    connection_id=None,
                )
            )
        )
    if row.connection_id is not None:
        chain.append(
            policy_map.get(
                _policy_key(
                    "connection",
                    agency_id=row.agency_id,
                    owner_user_id=row.owner_user_id,
                    connection_id=row.connection_id,
                )
            )
        )
    effective_enabled = global_enabled and not any(
        policy is not None and not policy.enabled for policy in chain
    )
    return EmailAiRolloutTargetResponse(
        scope_type=scope_type,
        target_id=row.target_id,
        agency_id=row.agency_id,
        owner_user_id=row.owner_user_id,
        connection_id=row.connection_id,
        label=row.label,
        detail=row.detail,
        direct_enabled=(
            direct_policy.enabled
            if direct_policy is not None
            else None
        ),
        effective_enabled=effective_enabled,
        updated_at=(
            direct_policy.updated_at
            if direct_policy is not None
            else None
        ),
    )


def _target_key(
    row: _RolloutTargetRow,
    scope_type: RolloutScope,
) -> PolicyKey:
    return _policy_key(
        scope_type,
        agency_id=row.agency_id,
        owner_user_id=(
            row.owner_user_id if scope_type != "agency" else None
        ),
        connection_id=(
            row.connection_id if scope_type == "connection" else None
        ),
    )


def _policy_key(
    scope_type: str,
    *,
    agency_id: uuid.UUID,
    owner_user_id: uuid.UUID | None,
    connection_id: uuid.UUID | None,
) -> PolicyKey:
    return (
        scope_type,
        agency_id,
        owner_user_id,
        connection_id,
    )


def _policy_predicates(
    scope_type: RolloutScope,
    *,
    agency_id: uuid.UUID,
    owner_user_id: uuid.UUID | None,
    connection_id: uuid.UUID | None,
) -> tuple[ColumnElement[bool], ...]:
    return (
        EmailAiRolloutPolicyModel.scope_type == scope_type,
        EmailAiRolloutPolicyModel.agency_id == agency_id,
        (
            EmailAiRolloutPolicyModel.owner_user_id.is_(None)
            if owner_user_id is None
            else EmailAiRolloutPolicyModel.owner_user_id == owner_user_id
        ),
        (
            EmailAiRolloutPolicyModel.connection_id.is_(None)
            if connection_id is None
            else EmailAiRolloutPolicyModel.connection_id == connection_id
        ),
    )


def _same_instant(left: datetime, right: datetime) -> bool:
    return _aware_utc(left) == _aware_utc(right)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
