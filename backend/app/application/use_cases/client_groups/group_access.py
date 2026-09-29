"""Shared assignable-group rules and flush-only additive access writes."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.domain.entities.entities import GroupStatus
from app.infrastructure.database.models import ClientGroupModel, ManagerGroupAccessModel, UserModel


def assignable_group_predicates(agency_id: uuid.UUID) -> tuple[ColumnElement[bool], ...]:
    return (
        ClientGroupModel.agency_id == agency_id,
        ClientGroupModel.status.notin_((GroupStatus.ARCHIVED.value, GroupStatus.DELETED.value)),
    )


def explicit_access_group_ids(
    groups: list[ClientGroupModel], account_id: uuid.UUID
) -> list[uuid.UUID]:
    # Both staff and managers already own the groups they created.
    return [group.id for group in groups if group.created_by_user_id != account_id]


async def add_missing_group_access(
    session: AsyncSession,
    *,
    account: UserModel,
    groups: list[ClientGroupModel],
    existing: list[ManagerGroupAccessModel],
) -> list[ManagerGroupAccessModel]:
    present = {row.group_id for row in existing}
    added = [
        ManagerGroupAccessModel(
            id=uuid.uuid4(),
            manager_id=account.id,
            group_id=group_id,
            agency_id=account.agency_id,
        )
        for group_id in explicit_access_group_ids(groups, account.id)
        if group_id not in present
    ]
    session.add_all(added)
    await session.flush()
    return added
