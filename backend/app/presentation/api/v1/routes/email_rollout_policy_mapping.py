"""Rollout policy loading, inherited-deny mapping and exact policy identities."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.infrastructure.database.email_ai_models import EmailAiRolloutPolicyModel
from app.presentation.api.v1.routes.email_rollout_targets import (
    PolicyKey,
    RolloutScope,
    _RolloutTargetRow,
)
from app.presentation.api.v1.schemas.email_ai_schemas import EmailAiRolloutTargetResponse


async def _load_policy_map(
    session: AsyncSession,
    rows: Sequence[_RolloutTargetRow],
) -> dict[PolicyKey, EmailAiRolloutPolicyModel]:
    if not rows:
        return {}
    agency_ids = {row.agency_id for row in rows}
    owner_user_ids = {row.owner_user_id for row in rows if row.owner_user_id is not None}
    connection_ids = {row.connection_id for row in rows if row.connection_id is not None}
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
                EmailAiRolloutPolicyModel.owner_user_id.in_(owner_user_ids),
                EmailAiRolloutPolicyModel.connection_id.is_(None),
            )
        )
    if connection_ids:
        scope_predicates.append(
            and_(
                EmailAiRolloutPolicyModel.scope_type == "connection",
                EmailAiRolloutPolicyModel.connection_id.in_(connection_ids),
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
        direct_enabled=(direct_policy.enabled if direct_policy is not None else None),
        effective_enabled=effective_enabled,
        updated_at=(direct_policy.updated_at if direct_policy is not None else None),
    )


def _target_key(
    row: _RolloutTargetRow,
    scope_type: RolloutScope,
) -> PolicyKey:
    return _policy_key(
        scope_type,
        agency_id=row.agency_id,
        owner_user_id=(row.owner_user_id if scope_type != "agency" else None),
        connection_id=(row.connection_id if scope_type == "connection" else None),
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


# Existing API/MCP imports retain direct references to these complete functions.
_load_policy_map.__module__ = "app.presentation.api.v1.routes.email_ai_rollout_admin"
_target_response.__module__ = "app.presentation.api.v1.routes.email_ai_rollout_admin"
_target_key.__module__ = "app.presentation.api.v1.routes.email_ai_rollout_admin"
_policy_key.__module__ = "app.presentation.api.v1.routes.email_ai_rollout_admin"
_policy_predicates.__module__ = "app.presentation.api.v1.routes.email_ai_rollout_admin"
