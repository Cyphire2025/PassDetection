"""Live owner authorization for linked-group notification metadata."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import UserRole
from app.infrastructure.database.email_ai_models import EmailAiAnalysisModel
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.repositories.user_repository import UserRepository


async def _visible_linked_group_name(
    session: AsyncSession,
    analysis: EmailAiAnalysisModel,
) -> str | None:
    """Resolve a linked group only through the current owner's live visibility."""

    raw_group_id = (analysis.result_json or {}).get("linked_group_id")
    if not isinstance(raw_group_id, str):
        return None
    try:
        group_id = uuid.UUID(raw_group_id)
    except ValueError:
        return None
    owner = await UserRepository(session).get_by_id(analysis.owner_user_id)
    if (
        owner is None
        or not owner.is_active
        or (owner.role != UserRole.SUPER_ADMIN and owner.agency_id != analysis.agency_id)
    ):
        return None
    statement = select(ClientGroupModel).where(
        ClientGroupModel.id == group_id,
        ClientGroupModel.agency_id == analysis.agency_id,
        ClientGroupModel.status.notin_({"archived", "deleted"}),
    )
    group = await session.scalar(
        AuthorizationPolicy.apply_group_visibility_scope(
            statement,
            owner,
        )
    )
    if group is None:
        return None
    normalized = " ".join(group.name.split())[:160]
    return normalized or None


# Direct public aliases keep their existing callable metadata.
_visible_linked_group_name.__module__ = "app.infrastructure.email.deadline_notifications"
