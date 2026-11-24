"""Index already scoped account/group rows without changing their display order."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.infrastructure.database.models import ClientGroupModel, ManagerGroupAccessModel


@dataclass(frozen=True, slots=True)
class AccountGroups:
    created: dict[uuid.UUID, list[ClientGroupModel]]
    assigned: dict[uuid.UUID, list[ClientGroupModel]]


def index_account_groups(
    groups: list[ClientGroupModel],
    access_rows: list[ManagerGroupAccessModel],
) -> AccountGroups:
    """Preserve group order and membership order, including repeated input rows."""
    by_id: dict[uuid.UUID, list[ClientGroupModel]] = {}
    created: dict[uuid.UUID, list[ClientGroupModel]] = {}
    assigned: dict[uuid.UUID, list[ClientGroupModel]] = {}
    for group in groups:
        by_id.setdefault(group.id, []).append(group)
        if group.created_by_user_id is not None:
            created.setdefault(group.created_by_user_id, []).append(group)
    for access in access_rows:
        matching = by_id.get(access.group_id)
        if matching:
            assigned.setdefault(access.manager_id, []).extend(matching)
    return AccountGroups(created=created, assigned=assigned)
