"""Live group discovery that never treats a group name as a unique identity.

Pagination is stable by immutable creation time/UUID, but is explicitly not a
durable snapshot of edits, membership or status. Transport supplies environment,
observation time, grant verification, capability enforcement and invocation audit.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.credentials import MCPAuthError, utc
from app.domain.entities.entities import User, UserRole
from app.infrastructure.repositories.mcp_group_read_repository import MCPGroupReadRepository
from app.infrastructure.repositories.user_repository import UserRepository

COUNT_DEFINITIONS = {
    "passport_submission_records": "All stored passport-submission rows, including imported or incomplete rows; not a count of approved people.",
    "operational_passengers": "Operationally approved passport rows remaining in the shared operational roster after active rejection/replacement decisions.",
    "whatsapp_active_recipient_entries": "Active recipient entries across linked, unarchived broadcasts. Entries in separate lists are distinct; this is not a unique-person count or proof of delivery.",
    "linked_whatsapp_broadcasts": "Tenant-matching linked broadcasts, including archived broadcasts.",
}


class MCPGroupReadService:
    def __init__(self, session: AsyncSession, *, cursor_secret: str):
        if not cursor_secret:
            raise ValueError("Cursor signing secret is required")
        self.session = session
        self.cursor_secret = cursor_secret.encode()

    async def _user(self, user_id: uuid.UUID) -> User:
        user = await UserRepository(self.session).get_by_id(user_id)
        if user is None or not user.is_active or user.role != UserRole.SUPER_ADMIN:
            raise MCPAuthError("access_denied", 403)
        return user

    def _encode(self, data: dict[str, Any]) -> str:
        body = base64.urlsafe_b64encode(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).decode().rstrip("=")
        digest = hmac.new(self.cursor_secret, b"mcp-groups-v1\0" + body.encode(), hashlib.sha256).hexdigest()
        return body + "." + digest

    def _decode(self, cursor: str, binding: str) -> dict[str, Any]:
        try:
            if not 1 <= len(cursor) <= 2048:
                raise ValueError()
            body, signature = cursor.split(".")
            expected = hmac.new(self.cursor_secret, b"mcp-groups-v1\0" + body.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError()
            data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
            if (data["version"] != 1 or data["binding"] != binding
                    or datetime.fromisoformat(data["expires_at"]) <= datetime.now(UTC)):
                raise ValueError()
            return dict(data)
        except (KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
            raise ValueError("Invalid, expired or differently scoped group cursor; restart the search") from exc

    async def list_groups(
        self, *, user_id: uuid.UUID, name: str | None = None, name_match: str = "contains",
        agency_id: uuid.UUID | None = None, group_id: uuid.UUID | None = None,
        status: str | None = None, include_deleted: bool = False,
        page_size: int = 25, cursor: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(page_size, int) or isinstance(page_size, bool) or not 1 <= page_size <= 100:
            raise ValueError("Page size must be between 1 and 100")
        if name_match not in {"exact", "contains"}:
            raise ValueError("Name match must be exact or contains")
        if status not in {None, "active", "closed", "archived", "deleted"}:
            raise ValueError("Unsupported group status")
        if status == "deleted" and not include_deleted:
            raise ValueError("Retained deleted groups require include_deleted")
        name = name.strip() if name is not None else None
        if name is not None and not 1 <= len(name) <= 255:
            raise ValueError("Group name search must contain 1 to 255 characters")
        user = await self._user(user_id)
        filters = dict(user_id=str(user_id), name=name, name_match=name_match,
                       agency_id=str(agency_id) if agency_id else None,
                       group_id=str(group_id) if group_id else None, status=status,
                       include_deleted=include_deleted, page_size=page_size)
        binding = hashlib.sha256(json.dumps(filters, sort_keys=True).encode()).hexdigest()
        state: dict[str, Any] = self._decode(cursor, binding) if cursor else {
            "version": 1, "binding": binding, "created_before": datetime.now(UTC).isoformat(),
            "expires_at": (datetime.now(UTC) + timedelta(minutes=30)).isoformat(),
        }
        after = (datetime.fromisoformat(state["after_created_at"]), uuid.UUID(state["after_id"])) if cursor else None
        rows = await MCPGroupReadRepository(self.session).page(
            user=user, created_before=datetime.fromisoformat(state["created_before"]), after=after,
            page_size=page_size, name=name, name_match=name_match, agency_id=agency_id,
            group_id=group_id, status=status, include_deleted=include_deleted,
        )
        has_more = len(rows) > page_size
        rows = rows[:page_size]
        next_cursor = None
        if has_more:
            last = rows[-1]
            next_cursor = self._encode({**state, "after_created_at": utc(last["created_at"]).isoformat(), "after_id": str(last["id"])})
        items = []
        for row in rows:
            counts = {key: int(row.pop(key)) for key in COUNT_DEFINITIONS}
            items.append({**row, "id": str(row["id"]), "agency_id": str(row["agency_id"]),
                          "created_at": utc(row["created_at"]).isoformat(),
                          "travel_date": row["travel_date"].isoformat() if row["travel_date"] else None,
                          "return_date": row["return_date"].isoformat() if row["return_date"] else None,
                          "deleted_at": utc(row["deleted_at"]).isoformat() if row["deleted_at"] else None,
                          "counts": counts})
        return {
            "items": items, "next_cursor": next_cursor, "page_size": page_size,
            "has_more": has_more, "count_definitions": COUNT_DEFINITIONS,
            "consistency": {"mode": "live_keyset", "snapshot_guaranteed": False,
                            "created_before": state["created_before"],
                            "notice": "Names, lifecycle filters, membership and counts may change between pages. Newer groups are excluded by the creation cutoff. Restart the search for a fresh observation."},
        }

    async def resolve_group(
        self, *, user_id: uuid.UUID, group_id: uuid.UUID | None = None,
        name: str | None = None, agency_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        if (group_id is None) == (name is None):
            raise ValueError("Provide either a group ID or an exact group name")
        page = await self.list_groups(user_id=user_id, group_id=group_id, name=name,
                                      name_match="exact", agency_id=agency_id, page_size=25)
        items = page["items"]
        resolution = "not_found" if not items else "resolved" if len(items) == 1 and not page["has_more"] else "ambiguous"
        return {**page, "resolution": resolution,
                "resolved_group_id": items[0]["id"] if resolution == "resolved" else None,
                "requires_choice": resolution == "ambiguous"}
