"""Shared fail-closed rollout policy expressions for travel email analysis."""

from __future__ import annotations

import uuid

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.selectable import Exists

from app.infrastructure.database.email_ai_models import EmailAiRolloutPolicyModel
from app.infrastructure.database.models import AgencyModel


def email_ai_disabled_policy_exists(
    *,
    agency_id: object,
    owner_user_id: object,
    connection_id: object,
) -> Exists:
    """Build the agency/user/connection deny expression used by every surface."""

    return exists(
        select(1).where(
            EmailAiRolloutPolicyModel.agency_id == agency_id,
            EmailAiRolloutPolicyModel.enabled.is_(False),
            or_(
                and_(
                    EmailAiRolloutPolicyModel.scope_type == "agency",
                    EmailAiRolloutPolicyModel.owner_user_id.is_(None),
                    EmailAiRolloutPolicyModel.connection_id.is_(None),
                ),
                and_(
                    EmailAiRolloutPolicyModel.scope_type == "user",
                    EmailAiRolloutPolicyModel.owner_user_id == owner_user_id,
                    EmailAiRolloutPolicyModel.connection_id.is_(None),
                ),
                and_(
                    EmailAiRolloutPolicyModel.scope_type == "connection",
                    EmailAiRolloutPolicyModel.owner_user_id == owner_user_id,
                    EmailAiRolloutPolicyModel.connection_id == connection_id,
                ),
            ),
        )
    )


async def email_ai_policy_allows(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    owner_user_id: uuid.UUID,
    connection_id: uuid.UUID,
    lock_namespace: bool = False,
) -> bool:
    """Return whether no agency, user, or connection kill-switch denies work."""

    if lock_namespace and not await lock_email_ai_policy_namespace(
        session,
        agency_id=agency_id,
    ):
        return False
    disabled = await session.scalar(
        select(
            email_ai_disabled_policy_exists(
                agency_id=agency_id,
                owner_user_id=owner_user_id,
                connection_id=connection_id,
            )
        )
    )
    return not bool(disabled)


async def lock_email_ai_policy_namespace(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
) -> bool:
    """Serialize policy mutations and final AI writes within one agency."""

    locked_agency_id = await session.scalar(
        select(AgencyModel.id)
        .where(AgencyModel.id == agency_id)
        .with_for_update()
    )
    return locked_agency_id == agency_id
