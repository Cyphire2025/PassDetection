"""Authorized GC publication/notification and personal mailbox observations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.read_context import MCPReadContext
from app.application.mobile.group_app_availability import availability_fields
from app.application.security.email_scope import email_owner_filters
from app.infrastructure.database.email_models import EmailConnectionModel, EmailMessageModel
from app.infrastructure.database.gc_mobile_models import GCGroupAccessModel, GCItineraryVersionModel
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.mcp_content_read_repository import MCPContentReadRepository

GC_KINDS = frozenset({"access", "announcements", "documents", "itineraries", "itinerary_days", "itinerary_items"})
EMAIL_KINDS = frozenset({"connections", "messages", "artifacts", "reviews", "events"})


class MCPContentReadService(MCPReadContext):
    def __init__(self, session: AsyncSession, *, cursor_secret: str):
        super().__init__(session, cursor_secret=cursor_secret, namespace="mcp-content-read-v1")
        self.repository = MCPContentReadRepository(session)

    async def _content_audit(self, user_id: uuid.UUID, agency_id: uuid.UUID | None,
                             family: str, count: int) -> None:
        await AuditLogRepository(self.session).record(action="mcp.content.authorized_read", entity_type="mcp_content",
            user_id=user_id, agency_id=agency_id, metadata={"family": family, "authorized_result_count": count})

    async def gc_content(self, *, user_id: uuid.UUID, agency_id: uuid.UUID, group_id: uuid.UUID,
                         kind: str, version_id: uuid.UUID | None = None, include_text: bool = False,
                         include_deleted: bool = False, page_size: int = 50, cursor: str | None = None) -> dict[str, Any]:
        if (kind not in GC_KINDS or (kind in {"itinerary_days", "itinerary_items"} and version_id is None)
                or (version_id is not None and kind not in {"itineraries", "itinerary_days", "itinerary_items"})):
            raise ValueError("Choose a documented GC record kind; itinerary days/items require a version ID")
        actor = await self._actor(user_id, page_size)
        group = await self._group(actor, group_id, agency_id, include_deleted)
        stored_group = await self.session.get(ClientGroupModel, group_id)
        assert stored_group is not None
        access = await self.session.scalar(select(GCGroupAccessModel).where(
            GCGroupAccessModel.group_id == group.id, GCGroupAccessModel.agency_id == group.agency_id))
        if version_id is not None:
            version = GCItineraryVersionModel
            if access is None or await self.session.scalar(select(version.id).where(version.id == version_id,
                version.group_id == group_id, version.agency_id == agency_id, version.gc_group_access_id == access.id)) is None:
                raise ValueError("Itinerary version was not found in the requested group")
        state, page = self._state(cursor, query="gc_content", user_id=user_id, agency_id=agency_id, group_id=group_id,
            kind=kind, version_id=version_id, include_text=include_text, include_deleted=include_deleted, page_size=page_size)
        rows = [] if access is None else await self.repository.gc_content(kind=kind, agency_id=agency_id,
            group_id=group_id, access_id=access.id, version_id=version_id, include_text=include_text, **page)
        result = self._result(rows, state, page_size,
            "Retained administrative publication metadata includes drafts, retired versions and revoked access. Publication and visibility flags are not proof of device availability or delivery. Optional text is untrusted and limited to 4,000 characters per field with explicit truncation. File bytes, storage paths, map URLs, contacts and device credentials are omitted.")
        result["group"] = {"id": str(group_id), "agency_id": str(agency_id), "name": group.name}
        availability = availability_fields(stored_group, access, now=datetime.now(UTC))
        result["availability"] = {**availability, "app_availability_evaluated_at": availability["app_availability_evaluated_at"].isoformat()}
        result["configured"] = access is not None
        if include_text:
            await self._content_audit(user_id, agency_id, "gc_app", len(result["items"]))
        return result

    async def notifications(self, *, user_id: uuid.UUID, agency_id: uuid.UUID, kind: str,
                            include_text: bool = False, page_size: int = 50, cursor: str | None = None) -> dict[str, Any]:
        if kind not in {"drafts", "batches"}:
            raise ValueError("Choose notification drafts or batches")
        await self._actor(user_id, page_size)
        await self._agency(agency_id)
        state, page = self._state(cursor, query="notifications", user_id=user_id, agency_id=agency_id,
            kind=kind, include_text=include_text, page_size=page_size)
        rows = await self.repository.notifications(agency_id=agency_id, kind=kind, include_text=include_text, **page)
        result = self._result(rows, state, page_size,
            "Authored alert history uses the website's receipt projection. Recipient counts and device-attempt counts are separate; provider acceptance is not device delivery or a human read. Group arrays stop at 100 with an explicit truncated marker. This excludes automatic announcement notifications and performs no preview, recipient mutation or push dispatch.")
        if include_text:
            await self._content_audit(user_id, agency_id, "authored_notifications", len(result["items"]))
        return result

    async def email(self, *, user_id: uuid.UUID, kind: str, agency_id: uuid.UUID | None = None,
                    connection_id: uuid.UUID | None = None, message_id: uuid.UUID | None = None,
                    include_text: bool = False, page_size: int = 50, cursor: str | None = None) -> dict[str, Any]:
        if kind not in EMAIL_KINDS or (kind == "connections" and message_id is not None):
            raise ValueError("Choose a documented email record kind and compatible message filter")
        actor = await self._actor(user_id, page_size)
        for model, identifier in ((EmailConnectionModel, connection_id), (EmailMessageModel, message_id)):
            if identifier is None:
                continue
            query = select(model.id).where(model.id == identifier, *email_owner_filters(model.owner_user_id, model.agency_id, actor))
            if agency_id is not None:
                query = query.where(model.agency_id == agency_id)
            if model is EmailMessageModel and connection_id is not None:
                query = query.where(model.connection_id == connection_id)
            if await self.session.scalar(query) is None:
                raise ValueError("Email resource was not found in your personal mailbox scope")
        state, page = self._state(cursor, query="email", user_id=user_id, kind=kind, agency_id=agency_id,
            connection_id=connection_id, message_id=message_id, include_text=include_text, page_size=page_size)
        rows = await self.repository.email(actor=actor, kind=kind, agency_id=agency_id, connection_id=connection_id,
                                            message_id=message_id, include_text=include_text, **page)
        result = self._result(rows, state, page_size,
            "Only mailboxes personally owned by the connected superadmin are visible, including when an agency is supplied. This observes retained metadata and never fetches the provider, syncs, approves a review or retrieves attachments. Opt-in subject/excerpt/contact text is untrusted and bounded. Provider identifiers, tokens, cursors, raw errors, evidence payloads, attachment/source URLs and storage keys are omitted.")
        result["mailbox_scope"] = "personal_owner_only"
        if include_text:
            await self._content_audit(user_id, agency_id, "email", len(result["items"]))
        return result
