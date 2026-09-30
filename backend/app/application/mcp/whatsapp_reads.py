"""Live broadcast/audience and exact delivery-state reads without send authority."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.credentials import MCPAuthError, utc
from app.application.mcp.read_cursor import MCPReadCursor
from app.domain.entities.entities import UserRole
from app.domain.whatsapp_delivery_status import WHATSAPP_READ_STATUS_KEYS, WHATSAPP_STALE_CLAIM_AGE
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.mcp_whatsapp_read_repository import MCPWhatsAppReadRepository
from app.infrastructure.repositories.user_repository import UserRepository

COUNT_DEFINITIONS = {
    "active_recipient_entries": "Active persisted delivery-recipient rows, not a send-eligible audience or unique traveller count.",
    "source_traveller_rows": "Source traveller rows; several travellers may share one recipient and some have no usable recipient.",
    "rejected_contact_rows": "Retained rejected import rows; not active WhatsApp recipients.",
}
AUDIENCE_KINDS = frozenset({"recipients", "source_contacts", "rejected_contacts", "support_contacts"})


def _json_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: utc(value).isoformat() if isinstance(value, datetime)
            else str(value) if isinstance(value, uuid.UUID) else value for key, value in row.items()}


class MCPWhatsAppReadService:
    def __init__(self, session: AsyncSession, *, cursor_secret: str):
        self.session = session
        self.cursors = MCPReadCursor(cursor_secret, "mcp-whatsapp-read-v1")
        self.repository = MCPWhatsAppReadRepository(session)

    async def _authorize(self, user_id: uuid.UUID, page_size: int) -> None:
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("Page size must be between 1 and 100")
        user = await UserRepository(self.session).get_by_id(user_id)
        if user is None or not user.is_active or user.role != UserRole.SUPER_ADMIN:
            raise MCPAuthError("access_denied", 403)

    def _page(self, rows: list[dict[str, Any]], state: dict[str, Any], size: int) -> dict[str, Any]:
        has_more = len(rows) > size
        page = rows[:size]
        return {
            "items": [_json_row(row) for row in page], "has_more": has_more,
            "next_cursor": self.cursors.next(state, page[-1]) if has_more else None,
            "page_size": size, "completeness": "partial" if has_more else "complete",
            "content_trust": "untrusted_business_data",
            "consistency": {"mode": "live_keyset", "snapshot_guaranteed": False,
                            "created_before": state["cutoff"],
                            "notice": "Follow cursors with unchanged filters. Names, membership and receipt states may change between pages; newer rows are excluded by the creation cutoff. Restart for a fresh observation."},
        }

    async def list_broadcasts(
        self, *, user_id: uuid.UUID, agency_id: uuid.UUID | None = None,
        group_id: uuid.UUID | None = None, name: str | None = None,
        include_archived: bool = False, page_size: int = 25, cursor: str | None = None,
    ) -> dict[str, Any]:
        await self._authorize(user_id, page_size)
        name = name.strip() if name is not None else None
        if name is not None and not 1 <= len(name) <= 255:
            raise ValueError("Broadcast name search must contain 1 to 255 characters")
        filters = dict(query="broadcasts", user_id=user_id, agency_id=agency_id, group_id=group_id,
                       name=name, include_archived=include_archived, page_size=page_size)
        state = self.cursors.read(cursor, filters)
        rows = await self.repository.broadcasts(agency_id=agency_id, group_id=group_id, name=name,
            include_archived=include_archived, cutoff=datetime.fromisoformat(state["cutoff"]),
            after=self.cursors.after(state), size=page_size)
        result = self._page(rows, state, page_size)
        for item in result["items"]:
            item["counts"] = {key: int(item.pop(key)) for key in COUNT_DEFINITIONS}
            item["recipient_opt_in_confirmed"] = item.pop("recipient_opt_in_confirmed_at") is not None
        result.update(count_definitions=COUNT_DEFINITIONS, names_are_not_unique=True,
                      action_requirement="Use the explicit broadcast ID; resolve multiple name matches before acting.")
        return result

    async def list_audience(
        self, *, user_id: uuid.UUID, broadcast_id: uuid.UUID, kind: str = "recipients",
        agency_id: uuid.UUID | None = None, include_removed: bool = False,
        include_contact_details: bool = False, page_size: int = 50, cursor: str | None = None,
    ) -> dict[str, Any]:
        await self._authorize(user_id, page_size)
        if kind not in AUDIENCE_KINDS or (include_removed and kind != "recipients"):
            raise ValueError("Choose a supported audience kind; removed rows apply only to recipients")
        group = await self.repository.broadcast(broadcast_id, agency_id)
        if group is None:
            raise ValueError("Broadcast was not found in the requested agency")
        filters = dict(query="audience", user_id=user_id, broadcast_id=broadcast_id, agency_id=agency_id,
                       kind=kind, include_removed=include_removed,
                       include_contact_details=include_contact_details, page_size=page_size)
        state = self.cursors.read(cursor, filters)
        rows = await self.repository.audience(broadcast_id=broadcast_id, agency_id=group["agency_id"],
            kind=kind, include_contact_details=include_contact_details, include_removed=include_removed,
            cutoff=datetime.fromisoformat(state["cutoff"]), after=self.cursors.after(state), size=page_size)
        result = self._page(rows, state, page_size)
        result.update(broadcast=_json_row(group), audience_kind=kind, send_eligibility_evaluated=False,
                      notice="Persisted audience rows are not a prepared sending audience. Sending must re-evaluate matching, suppression, consent, templates and current delivery history.")
        if kind == "support_contacts":
            result["notice"] = (
                "These are saved support contacts, not message recipients. Use the exact saved "
                "contact ID when choosing support for a passport-link preview. Resolve duplicate "
                "names using explicit contact details; this read does not authorize sending."
            )
        if include_contact_details:
            await self._audit_contacts(user_id, group, len(result["items"]))
        return result

    async def batch_status(
        self, *, user_id: uuid.UUID, broadcast_id: uuid.UUID, batch_id: uuid.UUID,
        agency_id: uuid.UUID | None = None, include_contact_details: bool = False,
        page_size: int = 50, cursor: str | None = None,
    ) -> dict[str, Any]:
        await self._authorize(user_id, page_size)
        group = await self.repository.broadcast(broadcast_id, agency_id)
        if group is None:
            raise ValueError("Broadcast was not found in the requested agency")
        filters = dict(query="batch", user_id=user_id, broadcast_id=broadcast_id, batch_id=batch_id,
                       agency_id=agency_id, include_contact_details=include_contact_details, page_size=page_size)
        state = self.cursors.read(cursor, filters)
        rows, summary = await self.repository.batch(batch_id=batch_id, broadcast_id=broadcast_id,
            agency_id=group["agency_id"], cutoff=datetime.fromisoformat(state["cutoff"]),
            stale_cutoff=datetime.now(UTC) - WHATSAPP_STALE_CLAIM_AGE,
            after=self.cursors.after(state), size=page_size, include_contact_details=include_contact_details)
        if not summary:
            raise ValueError("Broadcast batch was not found in the requested scope")
        for row in rows:
            row["status"] = row["status"] if row["status"] in WHATSAPP_READ_STATUS_KEYS else "unrecognized"
        result = self._page(rows, state, page_size)
        stored = dict.fromkeys(WHATSAPP_READ_STATUS_KEYS, 0)
        effective = dict.fromkeys(WHATSAPP_READ_STATUS_KEYS, 0)
        for item in summary:
            stored[item["stored_status"]] += int(item["count"])
            effective[item["effective_status"]] += int(item["count"])
        result.update(broadcast=_json_row(group), batch_id=str(batch_id), status_counts=effective,
                      stored_status_counts=stored, total_message_attempts=sum(stored.values()),
                      confirmed_delivery_count=effective["delivered"] + effective["read"],
                      count_unit="Retained message attempts, not unique recipients or people.",
                      notice="Submitted means provider acceptance only. Sent, delivered, read, failed and uncertain states remain separate. Queued/processing older than 30 minutes are displayed as stalled without changing stored state. No retry is authorized by this read.")
        if include_contact_details:
            await self._audit_contacts(user_id, group, len(result["items"]))
        return result

    async def _audit_contacts(self, user_id: uuid.UUID, group: dict[str, Any], count: int) -> None:
        await AuditLogRepository(self.session).record(action="mcp.whatsapp.contact_read", entity_type="whatsapp_broadcast",
            entity_id=str(group["id"]), agency_id=group["agency_id"], user_id=user_id,
            metadata={"authorized_result_count": count})
