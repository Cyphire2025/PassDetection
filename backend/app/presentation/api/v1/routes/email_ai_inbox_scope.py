"""Owner and agency predicates shared by the email inbox's read/write queries."""

from __future__ import annotations

from typing import TypeAlias

from sqlalchemy import false
from sqlalchemy.sql.elements import ColumnElement

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.email_ai_models import (
    EmailActionProposalModel,
    EmailAiAnalysisModel,
    EmailDetectedDeadlineModel,
    EmailReplyDraftModel,
)

_OwnerScopedModel: TypeAlias = (
    type[EmailAiAnalysisModel]
    | type[EmailActionProposalModel]
    | type[EmailDetectedDeadlineModel]
    | type[EmailReplyDraftModel]
)


def _owner_predicates(
    model: _OwnerScopedModel,
    user: User,
) -> list[ColumnElement[bool]]:
    predicates: list[ColumnElement[bool]] = [model.owner_user_id == user.id]
    if user.role != UserRole.SUPER_ADMIN:
        if user.agency_id is None:
            predicates.append(false())
            return predicates
        predicates.append(model.agency_id == user.agency_id)
    return predicates
