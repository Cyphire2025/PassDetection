"""Fixed projections of GC publication history and owner-scoped email state."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.authored_notification_history import batch_responses
from app.application.security.email_scope import email_owner_filters
from app.domain.entities.entities import User
from app.infrastructure.database.email_models import (
    EmailActivityEventModel,
    EmailArtifactModel,
    EmailConnectionModel,
    EmailMessageModel,
    EmailReviewItemModel,
)
from app.infrastructure.database.gc_mobile_models import (
    GCAnnouncementModel,
    GCCommonDocumentModel,
    GCGroupAccessModel,
    GCItineraryDayModel,
    GCItineraryItemModel,
    GCItineraryVersionModel,
)
from app.infrastructure.database.gc_notification_models import (
    GCNotificationBatchModel,
    GCNotificationDraftModel,
)
from app.infrastructure.repositories.mcp_read_page import page_query, read_page


def bounded_text(column: Any, label: str, *, limit: int = 4000) -> list[Any]:
    return [func.substr(column, 1, limit).label(label), (func.length(column) > limit).label(label + "_truncated")]


def bounded_groups(row: dict[str, Any]) -> dict[str, Any]:
    row["group_count"] = len(row["group_ids"])
    row["group_list_truncated"] = len(row["group_ids"]) > 100
    row["group_ids"] = [str(value) for value in row["group_ids"][:100]]
    row["group_names"] = [str(value)[:255] for value in row["group_names"][:100]]
    return row


class MCPContentReadRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def gc_content(self, *, kind: str, agency_id: uuid.UUID, group_id: uuid.UUID,
                         access_id: uuid.UUID, version_id: uuid.UUID | None,
                         include_text: bool, **page: Any) -> list[dict[str, Any]]:
        models: dict[str, Any] = {"access": GCGroupAccessModel, "announcements": GCAnnouncementModel,
            "documents": GCCommonDocumentModel, "itineraries": GCItineraryVersionModel,
            "itinerary_days": GCItineraryDayModel, "itinerary_items": GCItineraryItemModel}
        model = models[kind]
        fields = [model.id, model.created_at, model.updated_at]
        if kind == "access":
            fields += [model.is_enabled, model.passenger_access_enabled, model.client_manager_access_enabled,
                model.coordinator_access_enabled, model.access_starts_at, model.access_expires_at, model.revoked_at,
                model.removed_at, model.revision, model.manifest_version, model.itinerary_version,
                model.common_document_version, model.announcement_version, model.last_successful_sync_at]
        elif kind == "announcements":
            fields += [model.logical_announcement_id, model.version, model.category, model.priority, model.title,
                model.status, model.passenger_visible, model.client_manager_visible, model.coordinator_visible,
                model.availability_starts_at, model.availability_expires_at, model.published_at, model.retired_at, model.revoked_at]
            if include_text:
                fields += bounded_text(model.body, "body")
        elif kind == "documents":
            fields += [model.logical_document_id, model.version, model.category, model.title, model.safe_filename,
                model.media_type, model.byte_size, model.status, model.passenger_visible,
                model.client_manager_visible, model.coordinator_visible, model.published_at, model.retired_at, model.revoked_at]
            if include_text:
                fields += bounded_text(model.description, "description")
        elif kind == "itineraries":
            fields += [model.version, model.revision, model.title, model.status, model.published_at,
                       model.availability_starts_at, model.availability_expires_at]
            if include_text:
                fields += bounded_text(model.summary, "summary") + bounded_text(model.destination_information, "destination_information")
        elif kind == "itinerary_days":
            fields += [model.itinerary_version_id, model.day_number, model.trip_date, model.title, model.sort_order]
            if include_text:
                fields += bounded_text(model.summary, "summary")
        else:
            fields += [model.itinerary_version_id, model.itinerary_day_id, model.common_document_id, model.item_type,
                model.title, model.starts_at, model.ends_at, model.is_all_day, model.location_name, model.is_important, model.sort_order]
            if include_text:
                fields += bounded_text(model.description, "description")
        query = select(*fields).where(model.agency_id == agency_id, model.group_id == group_id,
            (model.id if kind == "access" else model.gc_group_access_id) == access_id)
        if version_id is not None:
            query = query.where((model.id if kind == "itineraries" else model.itinerary_version_id) == version_id)
        return await read_page(self.session, query, model, **page)

    async def notifications(self, *, agency_id: uuid.UUID, kind: str, include_text: bool,
                            **page: Any) -> list[dict[str, Any]]:
        if kind == "drafts":
            draft = GCNotificationDraftModel
            fields = [draft.id, draft.title, draft.audience, draft.revision, draft.status,
                      draft.last_sent_at, draft.created_at, draft.updated_at, draft.group_ids, draft.group_names]
            if include_text:
                fields.append(draft.body)
            rows = await read_page(self.session, select(*fields).where(draft.agency_id == agency_id, draft.deleted_at.is_(None)), draft, **page)
            return [bounded_groups(row) for row in rows]
        batch = GCNotificationBatchModel
        records = list((await self.session.scalars(page_query(select(batch).where(batch.agency_id == agency_id), batch, **page))).all())
        # The shared website projection distinguishes recipient and device states.
        projected = await batch_responses(self.session, records)
        results = []
        for item in projected:
            row = bounded_groups(item.model_dump())
            if not include_text:
                row.pop("body", None)
            results.append(row)
        return results

    async def email(self, *, actor: User, kind: str, agency_id: uuid.UUID | None,
                    connection_id: uuid.UUID | None, message_id: uuid.UUID | None,
                    include_text: bool, **page: Any) -> list[dict[str, Any]]:
        models: dict[str, Any] = {"connections": EmailConnectionModel, "messages": EmailMessageModel,
            "artifacts": EmailArtifactModel, "reviews": EmailReviewItemModel, "events": EmailActivityEventModel}
        model, connection, message = models[kind], EmailConnectionModel, EmailMessageModel
        fields = [model.id, model.created_at]
        if kind == "connections":
            fields += [model.provider, model.display_name, model.status, model.sync_state, model.ai_processing_enabled,
                model.last_sync_attempt_at, model.last_successful_sync_at, model.consecutive_failures,
                model.next_sync_at, model.last_error_at, model.paused_at, model.disconnected_at, model.updated_at]
            if include_text:
                fields.append(model.email_address)
        elif kind == "messages":
            fields += [model.connection_id, model.group_id, model.received_at, model.has_attachments,
                model.relevance_status, model.processing_status, model.artifact_count, model.processed_artifact_count,
                model.review_count, model.ai_used, model.updated_at]
            if include_text:
                fields += [model.sender_address, model.sender_name] + bounded_text(model.subject, "subject", limit=1000) + bounded_text(model.body_excerpt, "body_excerpt")
        elif kind == "artifacts":
            fields += [model.message_id, model.filename, model.kind, model.verified_content_type, model.size_bytes,
                model.retrieval_status, model.processing_status, model.detected_type, model.group_id, model.passenger_id,
                model.attempt_count, model.max_attempts, model.next_retry_at, model.retrieved_at, model.updated_at]
        elif kind == "reviews":
            fields += [model.message_id, model.artifact_id, model.review_type, model.status, model.proposed_action,
                model.candidate_group_id, model.candidate_passenger_id, model.selected_group_id, model.selected_passenger_id,
                model.revision, model.deferred_until, model.resolved_at, model.updated_at]
        else:
            fields += [model.connection_id, model.message_id, model.artifact_id, model.review_item_id,
                       model.event_type, model.stage, model.actor_type, model.occurred_at, model.ai_used]
        query = select(*fields).where(*email_owner_filters(model.owner_user_id, model.agency_id, actor))
        if kind in {"messages", "events"}:
            query = query.join(connection, and_(connection.id == model.connection_id, connection.owner_user_id == model.owner_user_id,
                                               connection.agency_id == model.agency_id))
        elif kind in {"artifacts", "reviews"}:
            query = query.join(message, and_(message.id == model.message_id, message.owner_user_id == model.owner_user_id,
                message.agency_id == model.agency_id)).join(connection, and_(connection.id == message.connection_id,
                    connection.owner_user_id == message.owner_user_id, connection.agency_id == message.agency_id))
        if agency_id is not None:
            query = query.where(model.agency_id == agency_id)
        if connection_id is not None:
            query = query.where(connection.id == connection_id)
        if message_id is not None:
            query = query.where((model.id if kind == "messages" else model.message_id) == message_id)
        return await read_page(self.session, query, model, **page)
