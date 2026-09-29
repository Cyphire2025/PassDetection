"""Retained document metadata and passport jobs under shared group authority."""

from __future__ import annotations

import math
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.credentials import MCPAuthError, utc
from app.application.mcp.read_cursor import MCPReadCursor
from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import ClientGroup, User, UserRole
from app.domain.exceptions.exceptions import AuthorizationError
from app.domain.value_objects.travel_document_taxonomy import DOCUMENT_TYPES
from app.infrastructure.documents.document_approval_provenance import (
    has_manual_document_type_approval,
)
from app.infrastructure.processing.job_state import ProcessingJobStatus
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.mcp_document_read_repository import MCPDocumentReadRepository
from app.infrastructure.repositories.sensitive_read_audit import record_sensitive_read
from app.infrastructure.repositories.user_repository import UserRepository

_JOB_STAGES = frozenset({"queued", "starting", "downloading_image", "extracting_passport_fields",
    "verifying_passport_fields", "saving_extraction_result", "extraction_busy", "retry_queued",
    "recovery_queued", "failed", "dead_letter", "completed", "cancelled"})


class MCPDocumentReadService:
    def __init__(self, session: AsyncSession, *, cursor_secret: str):
        self.session = session
        self.cursors = MCPReadCursor(cursor_secret, "mcp-document-read-v1")
        self.repository = MCPDocumentReadRepository(session)

    async def _scope(self, user_id: uuid.UUID, group_id: uuid.UUID, agency_id: uuid.UUID | None,
                     page_size: int, include_deleted: bool) -> tuple[User, ClientGroup]:
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ValueError("Page size must be between 1 and 100")
        actor = await UserRepository(self.session).get_by_id(user_id)
        if actor is None or not actor.is_active or actor.role != UserRole.SUPER_ADMIN:
            raise MCPAuthError("access_denied", 403)
        group = await ClientGroupRepository(self.session).get_by_id(group_id)
        if (group is None or (agency_id is not None and group.agency_id != agency_id)
                or (not include_deleted and (group.deleted_at is not None or group.status == "deleted"))):
            raise ValueError("Group was not found in the requested scope")
        try:
            await AuthorizationPolicy(self.session).require_export_data(actor, group)
        except AuthorizationError as exc:
            raise MCPAuthError("access_denied", 403) from exc
        return actor, group

    @staticmethod
    def _document_type(document_type: str | None) -> None:
        if document_type is not None and document_type not in DOCUMENT_TYPES:
            raise ValueError("Unsupported document type; use a canonical document lane")

    def _result(self, rows: list[dict[str, Any]], state: dict[str, Any], size: int,
                group: ClientGroup) -> dict[str, Any]:
        has_more = len(rows) > size
        page = rows[:size]
        return {"items": [{key: utc(value).isoformat() if isinstance(value, datetime)
                           else str(value) if isinstance(value, uuid.UUID) else value for key, value in row.items()}
                          for row in page],
                "group": {"id": str(group.id), "agency_id": str(group.agency_id), "name": group.name, "status": group.status},
                "page_size": size, "has_more": has_more,
                "next_cursor": self.cursors.next(state, page[-1]) if has_more else None,
                "completeness": "partial" if has_more else "complete",
                "content_trust": "untrusted_business_data",
                "consistency": {"mode": "live_keyset", "snapshot_guaranteed": False, "created_before": state["cutoff"],
                    "notice": "Metadata, assignments and processing status can change between pages. Newer rows are excluded by the creation cutoff. Restart for a fresh observation."}}

    async def list_documents(
        self, *, user_id: uuid.UUID, group_id: uuid.UUID, agency_id: uuid.UUID | None = None,
        document_type: str | None = None, include_extracted_identifiers: bool = False,
        include_deleted: bool = False, page_size: int = 50, cursor: str | None = None,
    ) -> dict[str, Any]:
        self._document_type(document_type)
        actor, group = await self._scope(user_id, group_id, agency_id, page_size, include_deleted)
        state = self.cursors.read(cursor, dict(query="documents", user_id=user_id, group_id=group_id,
            agency_id=agency_id, document_type=document_type, include_extracted_identifiers=include_extracted_identifiers,
            include_deleted=include_deleted, page_size=page_size))
        rows = await self.repository.documents(group_id=group_id, agency_id=group.agency_id,
            document_type=document_type, include_extracted_identifiers=include_extracted_identifiers,
            cutoff=datetime.fromisoformat(state["cutoff"]), after=self.cursors.after(state), size=page_size)
        for row in rows:
            row["manual_type_approved"] = has_manual_document_type_approval(row.pop("match_reason"))
            confidence = row["match_confidence"]
            row["match_confidence"] = confidence if math.isfinite(confidence) and 0 <= confidence <= 1 else None
        result = self._result(rows, state, page_size, group)
        result["notice"] = "Metadata only. A stored/assigned document is not proof of passenger approval, WhatsApp delivery or a completed file download. Use protected artifact workflows for bytes."
        if include_extracted_identifiers:
            await record_sensitive_read(self.session, user=actor, kind="group_view", agency_id=group.agency_id,
                                        entity_id=group.id, count=len(result["items"]))
        return result

    async def list_batches(
        self, *, user_id: uuid.UUID, group_id: uuid.UUID, agency_id: uuid.UUID | None = None,
        document_type: str | None = None, include_deleted: bool = False,
        page_size: int = 50, cursor: str | None = None,
    ) -> dict[str, Any]:
        self._document_type(document_type)
        _, group = await self._scope(user_id, group_id, agency_id, page_size, include_deleted)
        state = self.cursors.read(cursor, dict(query="batches", user_id=user_id, group_id=group_id,
            agency_id=agency_id, document_type=document_type, include_deleted=include_deleted, page_size=page_size))
        rows = await self.repository.batches(group_id=group_id, agency_id=group.agency_id,
            document_type=document_type, cutoff=datetime.fromisoformat(state["cutoff"]),
            after=self.cursors.after(state), size=page_size)
        result = self._result(rows, state, page_size, group)
        result["notice"] = "Retained distribution batches and their stored upload/rejection/matching counters. These are not delivered-file or passenger counts. All batches are paginated, including earlier and incomplete batches."
        return result

    async def list_processing_jobs(
        self, *, user_id: uuid.UUID, group_id: uuid.UUID, agency_id: uuid.UUID | None = None,
        submission_id: uuid.UUID | None = None, status: str | None = None,
        include_deleted: bool = False, page_size: int = 50, cursor: str | None = None,
    ) -> dict[str, Any]:
        if status is not None and status not in {item.value for item in ProcessingJobStatus}:
            raise ValueError("Unsupported passport processing job status")
        _, group = await self._scope(user_id, group_id, agency_id, page_size, include_deleted)
        state = self.cursors.read(cursor, dict(query="processing", user_id=user_id, group_id=group_id,
            agency_id=agency_id, submission_id=submission_id, status=status,
            include_deleted=include_deleted, page_size=page_size))
        rows = await self.repository.processing_jobs(group_id=group_id, agency_id=group.agency_id,
            submission_id=submission_id, status=status, cutoff=datetime.fromisoformat(state["cutoff"]),
            after=self.cursors.after(state), size=page_size)
        for row in rows:
            row["current_stage"] = row["current_stage"] if row["current_stage"] in _JOB_STAGES else "unknown"
            progress = row["progress"]
            row["progress"] = progress if math.isfinite(progress) and 0 <= progress <= 1 else None
        result = self._result(rows, state, page_size, group)
        result["notice"] = "Passport extraction jobs only. Earlier revision success does not establish the current submission's result. Raw errors and storage locations are withheld; correlate the job ID through diagnostics. Reading progress never queues, cancels or retries work."
        return result
