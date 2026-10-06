"""Review and save classified/matched documents without ever dispatching delivery."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import FastAPI, HTTPException
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.change_context import require_change_group
from app.application.mcp.operations import (
    MCPDatabaseContext,
    MCPDatabaseOperation,
    MCPDatabaseResult,
    MCPOperationError,
)
from app.application.mcp.pdf_ingestion import DocumentLane
from app.core.config.settings import Settings
from app.domain.entities.entities import User
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.infrastructure.database.models import (
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
)
from app.presentation.api.v1.routes.document_distribution_save import save_document_lane
from app.presentation.mcp.dashboard_write_support import public_failure, safe_result, scoped_actor
from app.presentation.mcp.invocation import invoke_operation, invoke_read


class DocumentAssignmentSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agency_id: UUID
    group_id: UUID
    document_type: DocumentLane


class DocumentAssignmentSave(DocumentAssignmentSelection):
    inspected_revision: str = Field(pattern="^[0-9a-f]{64}$")
    assignments_reviewed: Literal[True] = Field(description="User reviewed classified files, passenger matches and unresolved files. Saving does not send any document.")


async def assignment_snapshot(context: MCPDatabaseContext, selection: DocumentAssignmentSelection, *, lock: bool) -> tuple[User, list[DocumentDistributionBatchModel], list[DistributedDocumentModel], dict[str, Any], str]:
    actor = await scoped_actor(context, selection.agency_id)
    await require_change_group(context, actor, selection.group_id, selection.agency_id, exclusive=lock)
    queries: list[Select[Any]] = [select(model).where(model.agency_id == selection.agency_id,
        model.group_id == selection.group_id, model.document_type == selection.document_type).order_by(model.id).limit(1001)
        for model in (DocumentDistributionBatchModel, DistributedDocumentModel)]
    if lock:
        queries = [query.with_for_update().execution_options(populate_existing=True) for query in queries]
    batches = list((await context.session.scalars(queries[0])).all())
    documents = list((await context.session.scalars(queries[1])).all())
    if len(batches) > 1000 or len(documents) > 1000:
        raise MCPOperationError("document_assignment_source_limit")
    snapshot = safe_result({"agency_id": selection.agency_id, "group_id": selection.group_id, "document_type": selection.document_type,
        "batches": [{"id": row.id, "status": row.status, "updated_at": row.updated_at,
            "uploaded_count": row.uploaded_count, "rejected_count": row.rejected_count, "matched_count": row.matched_count} for row in batches],
        "assignments": [{"document_id": row.id, "batch_id": row.batch_id, "passenger_id": row.passenger_id,
            "filename": row.original_filename, "detected_type": row.detected_type, "match_status": row.match_status,
            "match_confidence": row.match_confidence, "updated_at": row.updated_at} for row in documents]})
    revision = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    return actor, batches, documents, snapshot, revision


def document_assignment_operation() -> MCPDatabaseOperation:
    async def mutate(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        selection = DocumentAssignmentSave.model_validate(payload)
        actor, batches, documents, _, revision = await assignment_snapshot(context, selection, lock=True)
        if revision != selection.inspected_revision:
            raise MCPOperationError("document_assignment_revision_changed")
        if not batches:
            raise MCPOperationError("document_assignment_lane_empty")
        if any(row.status == "processing" for row in batches):
            raise MCPOperationError("document_assignment_processing")
        try:
            await save_document_lane(batch_id=batches[0].id, current_user=actor, session=context.session)
        except HTTPException as exc:
            raise public_failure(exc) from exc
        return MCPDatabaseResult({"agency_id": str(selection.agency_id), "group_id": str(selection.group_id), "document_type": selection.document_type,
            "batch_ids": [str(row.id) for row in batches], "document_count": len(documents),
            "assigned_count": sum(row.passenger_id is not None for row in documents), "status": "saved", "documents_sent": 0,
            "notice": "The reviewed lane is saved. Unresolved files remain unassigned; no messages or documents were sent."})

    async def authorize(context: MCPDatabaseContext, receipt: dict[str, Any]) -> None:
        data = receipt["data"]
        actor = await scoped_actor(context, UUID(data["agency_id"]))
        await require_change_group(context, actor, UUID(data["group_id"]), UUID(data["agency_id"]))
        ids = set((await context.session.scalars(select(DocumentDistributionBatchModel.id).where(
            DocumentDistributionBatchModel.id.in_([UUID(value) for value in data["batch_ids"]]),
            DocumentDistributionBatchModel.group_id == UUID(data["group_id"]), DocumentDistributionBatchModel.agency_id == UUID(data["agency_id"]),
            DocumentDistributionBatchModel.document_type == data["document_type"],
        ))).all())
        if ids != {UUID(value) for value in data["batch_ids"]}:
            raise MCPOperationError("document_assignment_receipt_unavailable")

    return MCPDatabaseOperation(MCPToolPolicy("save_document_assignments", MCPCapability.CHANGE, frozenset({"save_reviewed_assignments"})), mutate, authorize)


def register_document_assignment_tools(server: MCPServer, app: FastAPI, settings: Settings) -> None:
    definition = document_assignment_operation()
    app.state.mcp_operations[definition.policy.name] = definition
    @server.tool(meta={"capability": "mcp:change"}, annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False))
    async def inspect_document_assignments(selection: DocumentAssignmentSelection) -> dict[str, Any]:
        """Review the complete bounded document lane before saving, including classifications, passenger matches and unresolved files. Never force a match or infer manual approval. No messages/documents are sent."""
        async def read(session: AsyncSession, principal: MCPPrincipal) -> dict[str, Any]:
            _, batches, documents, snapshot, revision = await assignment_snapshot(MCPDatabaseContext(session, principal, UUID(int=0)), selection, lock=False)
            return {"preview": snapshot, "inspected_revision": revision, "processing": any(row.status == "processing" for row in batches),
                "unassigned_count": sum(row.passenger_id is None for row in documents), "confirmation_required": True, "documents_sent": 0}
        return await invoke_read(app, settings, MCPToolPolicy("inspect_document_assignments", MCPCapability.CHANGE, frozenset({"read"})), read)

    @server.tool(meta={"capability": "mcp:change"}, annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False))
    async def save_document_assignments(selection: DocumentAssignmentSave, idempotency_key: Annotated[str, Field(min_length=16, max_length=256)]) -> dict[str, Any]:
        """Save only the exact reviewed group/lane and unchanged inspection revision. Explain unresolved or rejected files and obtain the user's review. Existing canonical passenger matches are retained. Saving never sends; document delivery is a separate final-confirmation workflow. Retry exact input using the same key."""
        return await invoke_operation(app, settings, definition, idempotency_key=idempotency_key, payload=selection.model_dump(mode="json"))
