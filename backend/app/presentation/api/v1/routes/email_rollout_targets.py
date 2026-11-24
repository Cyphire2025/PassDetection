"""Typed rollout target rows and bounded agency, office-user and mailbox queries."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from types import FunctionType
from typing import Literal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import UserRole
from app.infrastructure.database.email_models import EmailConnectionModel
from app.infrastructure.database.models import AgencyModel, UserModel

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


async def _target_rows(
    session: AsyncSession,
    *,
    scope_type: RolloutScope,
    limit: int,
    search: str = "",
    agency_id: uuid.UUID | None = None,
    target_id: uuid.UUID | None = None,
    requesting_user_id: uuid.UUID | None = None,
    offset: int = 0,
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
                agency_statement.order_by(AgencyModel.name.asc(), AgencyModel.id.asc())
                .offset(offset)
                .limit(limit)
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
                )
                .offset(offset)
                .limit(limit)
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
        connection_statement = connection_statement.where(EmailConnectionModel.id == target_id)
    if search:
        connection_statement = connection_statement.where(
            or_(
                func.lower(EmailConnectionModel.email_address).contains(search),
                func.lower(UserModel.full_name).contains(search),
            )
        )
    connection_rows = (
        await session.execute(
            connection_statement.order_by(
                EmailConnectionModel.email_address.asc(),
                EmailConnectionModel.id.asc(),
            )
            .offset(offset)
            .limit(limit)
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


# Preserve the actual legacy dataclass/pickle and generated-method identities.
_RolloutTargetRow.__module__ = "app.presentation.api.v1.routes.email_ai_rollout_admin"
for _method in vars(_RolloutTargetRow).values():
    if isinstance(_method, FunctionType) and _method.__module__ == __name__:
        _method.__module__ = _RolloutTargetRow.__module__
del _method
_target_rows.__module__ = "app.presentation.api.v1.routes.email_ai_rollout_admin"
