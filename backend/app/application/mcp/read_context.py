"""Live office reads with shared authorization, roster and trip semantics."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.credentials import MCPAuthError, utc
from app.application.mcp.read_cursor import MCPReadCursor
from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import ClientGroup, User, UserRole
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.models import (
    AgencyModel,
    UserModel,
)
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.user_repository import UserRepository


class MCPReadContext:
    """Shared identity, group scope and signed live-page support for read services."""

    def __init__(self, session: AsyncSession, *, cursor_secret: str, namespace: str):
        self.session = session
        self.cursors = MCPReadCursor(cursor_secret, namespace)

    async def _actor(self, user_id: uuid.UUID, page_size: int) -> User:
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("Page size must be between 1 and 100")
        actor = await UserRepository(self.session).get_by_id(user_id)
        retained = await self.session.scalar(select(UserModel.id).where(UserModel.id == user_id, UserModel.deleted_at.is_(None)))
        if actor is None or retained is None or not actor.is_active or actor.role != UserRole.SUPER_ADMIN:
            raise MCPAuthError("access_denied", 403)
        return actor

    async def _group(self, actor: User, group_id: uuid.UUID, agency_id: uuid.UUID | None,
                     include_deleted: bool) -> ClientGroup:
        group = await ClientGroupRepository(self.session).get_by_id(group_id)
        if (group is None or (agency_id is not None and group.agency_id != agency_id)
                or (not include_deleted and (group.deleted_at is not None or group.status == "deleted"))):
            raise ValueError("Group was not found in the requested scope")
        try:
            await AuthorizationPolicy(self.session).require_view_group(actor, group)
        except AuthorizationError as exc:
            raise MCPAuthError("access_denied", 403) from exc
        return group

    async def _agency(self, agency_id: uuid.UUID | None) -> None:
        if agency_id is not None and await self.session.scalar(select(AgencyModel.id).where(AgencyModel.id == agency_id)) is None:
            raise ValueError("Agency was not found")

    def _state(self, cursor: str | None, **binding: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        state = self.cursors.read(cursor, binding)
        return state, {"cutoff": datetime.fromisoformat(state["cutoff"]),
                       "after": self.cursors.after(state), "size": binding["page_size"]}

    def _result(self, rows: list[dict[str, Any]], state: dict[str, Any], size: int,
                notice: str) -> dict[str, Any]:
        page, more = rows[:size], len(rows) > size
        truncated = any(value is True for row in page for key, value in row.items() if key.endswith("_truncated"))
        return {"items": [{key: utc(value).isoformat() if isinstance(value, datetime)
            else value.isoformat() if isinstance(value, date) else str(value) if isinstance(value, uuid.UUID)
            else value for key, value in row.items()} for row in page],
            "has_more": more, "page_size": size, "next_cursor": self.cursors.next(state, page[-1]) if more else None,
            "completeness": "partial" if more or truncated else "complete", "content_truncated": truncated,
            "content_trust": "untrusted_business_data",
            "consistency": {"mode": "live_keyset", "snapshot_guaranteed": False, "created_before": state["cutoff"],
                "notice": "Mutable values, membership and aggregate counts can change between pages. Newer records are excluded by the creation cutoff. Restart for a fresh observation."},
            "notice": notice}
