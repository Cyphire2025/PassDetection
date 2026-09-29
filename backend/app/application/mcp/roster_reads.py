"""The website's duplicate-aware passport view with revision-bound continuation."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.credentials import MCPAuthError
from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import UserRole
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.passports.roster_view_service import prepared_roster
from app.infrastructure.repositories.passport_submission_view_repository import (
    PassportSubmissionViewRepository,
)
from app.infrastructure.repositories.sensitive_read_audit import record_sensitive_read
from app.infrastructure.repositories.user_repository import UserRepository


class MCPRosterReadService:
    def __init__(self, session: AsyncSession, *, cursor_secret: str):
        if not cursor_secret:
            raise ValueError("Cursor signing secret is required")
        self.session, self.secret = session, cursor_secret.encode()

    def _encode(self, state: dict[str, Any]) -> str:
        body = base64.urlsafe_b64encode(json.dumps(state, sort_keys=True).encode()).decode().rstrip("=")
        signature = hmac.new(self.secret, b"mcp-roster-v1\0" + body.encode(), hashlib.sha256).hexdigest()
        return body + "." + signature

    def _decode(self, cursor: str) -> dict[str, Any]:
        try:
            if not 1 <= len(cursor) <= 2048:
                raise ValueError()
            body, signature = cursor.split(".")
            expected = hmac.new(self.secret, b"mcp-roster-v1\0" + body.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError()
            state = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
            if state["v"] != 1 or datetime.fromisoformat(state["expires"]) <= datetime.now(UTC):
                raise ValueError()
            if type(state["page"]) is not int or state["page"] < 2:
                raise ValueError()
            return dict(state)
        except (ValueError, TypeError, KeyError, UnicodeError) as exc:
            raise ValueError("Invalid or expired roster cursor; restart the query") from exc

    async def list_passports(
        self, *, user_id: uuid.UUID, group_id: uuid.UUID,
        submission_filter: str = "all", search: str | None = None,
        page_size: int = 50, cursor: str | None = None,
        include_contact_details: bool = False,
    ) -> dict[str, Any]:
        if submission_filter not in {"all", "pending_ai", "ai_approved", "needs_review",
                                     "staff_approved", "duplicates", "document_follow_up"}:
            raise ValueError("Unsupported passport view filter")
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("Page size must be between 1 and 100")
        if search is not None and not 1 <= len(search.strip()) <= 200:
            raise ValueError("Search must contain 1 to 200 characters")
        actor = await UserRepository(self.session).get_by_id(user_id)
        if actor is None or not actor.is_active or actor.role != UserRole.SUPER_ADMIN:
            raise MCPAuthError("access_denied", 403)
        group = await self.session.scalar(AuthorizationPolicy.apply_group_visibility_scope(
            select(ClientGroupModel).where(ClientGroupModel.id == group_id,
                ClientGroupModel.deleted_at.is_(None),
                ClientGroupModel.status.notin_(["archived", "deleted"])), actor))
        if group is None:
            return {"group_id": str(group_id), "resolution": "not_found", "items": [],
                    "next_cursor": None, "has_more": False, "completeness": "unavailable"}
        # Existing website services require an explicit agency context. Only the
        # already-authorized group's tenant supplies it; callers cannot spoof it.
        scoped_actor = replace(actor, agency_id=group.agency_id)
        options = {"group_id": str(group_id), "actor_id": str(actor.id),
                   "submission_filter": submission_filter, "search": search,
                   "page_size": page_size, "include_contact_details": include_contact_details}
        binding = hashlib.sha256(json.dumps(options, sort_keys=True).encode()).hexdigest()
        continuation = self._decode(cursor) if cursor else None
        if continuation and continuation.get("binding") != binding:
            raise ValueError("Roster cursor belongs to a different query; restart the query")
        prepared, revision = await prepared_roster(
            self.session, group_id=group_id, user=scoped_actor, include_deleted=False,
            submission_filter=submission_filter, sort_by="name", sort_order="asc",
            search=search, page_size=page_size)
        current_revision = await PassportSubmissionViewRepository(self.session).revision(
            group_id=group_id, user=scoped_actor, include_deleted=False)
        if revision != current_revision:
            raise ValueError("The roster changed while reading; restart the query")
        # The trigger revision protects PostgreSQL. The content fingerprint also
        # detects changes in stores without triggers and bounds page identity.
        identities = [(str(entry.submission.id), entry.submission.extraction_revision,
                       entry.submission.updated_at.isoformat())
                      for page in prepared.pages for entry in page]
        fingerprint = hashlib.sha256(json.dumps([str(revision), identities], sort_keys=True).encode()).hexdigest()
        if continuation and continuation.get("fingerprint") != fingerprint:
            raise ValueError("The roster changed since the previous page; restart the query")
        page_number = continuation["page"] if continuation else 1
        page = prepared.page(page_number)
        items = []
        for entry in page.items:
            row = entry.submission
            item = {"submission_id": str(row.id), "client_name": row.client_name,
                    "status": row.status, "extraction_revision": row.extraction_revision,
                    "updated_at": row.updated_at.isoformat(),
                    "document_follow_up": row.document_follow_up,
                    "duplicate_cluster_id": entry.duplicate_cluster_id,
                    "duplicate_cluster_size": entry.duplicate_cluster_size,
                    "verification_confidence": entry.verification_confidence}
            if include_contact_details:
                item.update(client_email=row.client_email, client_phone=row.client_phone)
            items.append(item)
        has_more = page_number < page.total_pages
        next_cursor = self._encode({"v": 1, "binding": binding, "fingerprint": fingerprint,
            "page": page_number + 1, "expires": continuation["expires"] if continuation else
            (datetime.now(UTC) + timedelta(minutes=30)).isoformat()}) if has_more else None
        await record_sensitive_read(self.session, user=scoped_actor, kind="group_list",
                                    agency_id=group.agency_id, entity_id=group_id, count=len(items))
        return {"group_id": str(group_id), "agency_id": str(group.agency_id), "resolution": "resolved",
                "items": items, "group_total": page.group_total, "matching_total": page.total,
                "document_follow_up_count": page.document_follow_up_count,
                "page": page_number, "page_size": page_size, "total_pages": page.total_pages,
                "next_cursor": next_cursor, "has_more": has_more,
                "roster_kind": "office_visible_passport_submissions",
                "count_notice": "This is the website passport view, not the operational-passenger or WhatsApp-recipient roster.",
                "roster_revision": revision[0] if revision else None,
                "consistency": "restart_on_roster_change",
                "completeness": "partial" if has_more else "complete"}
