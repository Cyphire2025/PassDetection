"""Durable document-assignment review XLSX; no assignment, approval or messaging effects."""

from __future__ import annotations

import asyncio
import hmac
import uuid
from collections.abc import AsyncIterator
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.artifacts import CHUNK_BYTES, ArtifactError, MCPArtifactService
from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.document_export_source import (
    MAX_DOCUMENT_ASSIGNMENTS,
    MAX_DOCUMENT_DELIVERIES,
    MAX_DOCUMENT_PASSENGERS,
    DocumentExcelSupport,
    lock_document_export_source,
)
from app.application.mcp.document_export_workbook import (
    DocumentReviewFilter,
    PreparedDocumentWorkbook,
    prepare_document_workbook,
)
from app.application.mcp.export_capacity import admitted_export
from app.application.mcp.operations import (
    MCPCreatedEntity,
    MCPDatabaseContext,
    MCPDatabaseOperation,
    MCPDatabaseResult,
    MCPOperationError,
    MCPOperationProgress,
    MCPOperationService,
)
from app.application.use_cases.passports.excel_snapshot import ExcelSnapshotTooLarge
from app.core.config.settings import Settings
from app.domain.entities.entities import User
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.export.workbook_capacity import WorkbookCapacityError

DOCUMENT_EXPORT_POLICY = MCPToolPolicy(
    "prepare_document_assignment_export", MCPCapability.EXPORT, frozenset({"prepare_export"})
)
MAX_WORKBOOK_BYTES = 32 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024


class DocumentExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agency_id: uuid.UUID
    group_id: uuid.UUID
    document_type: Literal[
        "visa",
        "flight_ticket",
        "flight_ticket_arrival",
        "flight_ticket_domestic",
        "flight_ticket_domestic_arrival",
        "other",
    ]
    review_filter: DocumentReviewFilter = "all"
    search: str = Field(default="", max_length=200)


class DocumentExportCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    export: DocumentExportRequest
    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")


class MCPDocumentExportService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        support: DocumentExcelSupport,
        *,
        artifacts: MCPArtifactService | None = None,
    ):
        self.session, self.settings, self.support = session, settings, support
        self.artifacts = artifacts or MCPArtifactService(session, settings)

    async def _scope(
        self, principal: MCPPrincipal, request: DocumentExportRequest
    ) -> tuple[User, ClientGroupModel]:
        await self.artifacts._authority(principal, "mcp:export", lock=True)
        if self.session.bind is not None and self.session.bind.dialect.name == "postgresql":
            await self.session.execute(text("SET LOCAL lock_timeout = '250ms'"))
        actor = await self.artifacts._group(
            principal, request.agency_id, request.group_id, "export"
        )
        group = await self.session.scalar(
            select(ClientGroupModel)
            .where(
                ClientGroupModel.id == request.group_id,
                ClientGroupModel.agency_id == request.agency_id,
            )
            .with_for_update(nowait=True)
            .execution_options(populate_existing=True)
        )
        if group is None or group.deleted_at or group.status == "deleted":
            raise ArtifactError("Group was not found", 404)
        return actor, group

    @admitted_export
    async def prepare(
        self, principal: MCPPrincipal, request: DocumentExportRequest
    ) -> PreparedDocumentWorkbook:
        try:
            actor, group = await self._scope(principal, request)
            source = await lock_document_export_source(
                self.session,
                support=self.support,
                actor=actor,
                group=group,
                document_type=request.document_type,
            )
            return prepare_document_workbook(
                support=self.support,
                source=source,
                group_name=group.name,
                document_type=request.document_type,
                review_filter=request.review_filter,
                search=request.search,
                maximum_snapshot_bytes=MAX_SNAPSHOT_BYTES,
            )
        except ExcelSnapshotTooLarge as exc:
            raise ArtifactError("Document export snapshot exceeds its size limit", 413) from exc
        except WorkbookCapacityError as exc:
            raise ArtifactError(str(exc), 413) from exc
        except DBAPIError as exc:
            self._database_error(exc)
            raise

    @admitted_export
    async def inspect(
        self, principal: MCPPrincipal, request: DocumentExportRequest
    ) -> dict[str, Any]:
        prepared = await self.prepare(principal, request)
        return {
            "export": request.model_dump(mode="json"),
            "expected_revision": prepared.revision,
            "passenger_count": prepared.passenger_count,
            "assignment_count": prepared.assignment_count,
            "exported_count": prepared.exported_count,
            "history_checkpoint": False,
            "assignments_changed": 0,
            "messages_queued": 0,
            "maximum_source_passengers": MAX_DOCUMENT_PASSENGERS,
            "maximum_assignment_rows": MAX_DOCUMENT_ASSIGNMENTS,
            "maximum_delivery_rows": MAX_DOCUMENT_DELIVERIES,
            "maximum_workbook_bytes": MAX_WORKBOOK_BYTES,
            "maximum_snapshot_bytes": MAX_SNAPSHOT_BYTES,
            "maximum_cell_characters": 32767,
        }

    @staticmethod
    def _database_error(exc: DBAPIError) -> None:
        if getattr(exc.orig, "sqlstate", None) == "55P03":
            raise ArtifactError("Document export sources are busy; resume later", 503) from exc

    @staticmethod
    def _revision(prepared: PreparedDocumentWorkbook, expected: str) -> None:
        if not hmac.compare_digest(prepared.revision, expected):
            raise MCPOperationError("export_revision_changed")

    @admitted_export
    async def generate(self, *, access_token: str, operation_id: uuid.UUID) -> dict[str, Any]:
        try:
            return await self._generate(access_token=access_token, operation_id=operation_id)
        except DBAPIError as exc:
            self._database_error(exc)
            raise

    async def _generate(self, *, access_token: str, operation_id: uuid.UUID) -> dict[str, Any]:
        operations = MCPOperationService(self.session, self.settings)
        principal = await operations._authorize(access_token, "mcp:export")
        operation = await self.session.scalar(
            select(MCPOperationModel)
            .where(
                MCPOperationModel.id == operation_id,
                MCPOperationModel.user_id == principal.user_id,
                MCPOperationModel.operation_name == DOCUMENT_EXPORT_POLICY.name,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if operation is None or operation.initial_result is None:
            raise MCPOperationError("operation_not_found")
        command = DocumentExportCommand.model_validate(operation.initial_result["data"])
        await self._scope(principal, command.export)
        if operation.status == "succeeded":
            identifiers = [
                entry["entity_id"]
                for entry in operation.created_entities
                if entry["entity_type"] == "mcp_artifact"
            ]
            if len(identifiers) != 1:
                raise MCPOperationError("operation_receipt_unavailable")
            metadata = await self.artifacts.recover_export(principal, uuid.UUID(identifiers[0]))
            return {"operation_id": str(operation.id), "status": "succeeded", "artifact": metadata}
        if operation.status != "queued":
            raise MCPOperationError("export_not_resumable")
        prepared = await self.prepare(principal, command.export)
        self._revision(prepared, command.expected_revision)
        # The shared preparation drains its native worker on cancellation. Capacity
        # is retained until that worker exits, even when the deadline is reached.
        try:
            async with asyncio.timeout(120):
                content = await prepared.render(maximum_output_bytes=MAX_WORKBOOK_BYTES)
        except WorkbookCapacityError as exc:
            raise ArtifactError(str(exc), 413) from exc
        if len(content) > MAX_WORKBOOK_BYTES:
            raise ArtifactError("Document workbook exceeds its size limit", 413)
        self._revision(await self.prepare(principal, command.export), command.expected_revision)

        async def body() -> AsyncIterator[bytes]:
            for offset in range(0, len(content), CHUNK_BYTES):
                yield content[offset : offset + CHUNK_BYTES]

        metadata = await self.artifacts.prepare_export(
            principal,
            agency_id=command.export.agency_id,
            group_id=command.export.group_id,
            purpose="document_assignments_excel",
            filename=prepared.filename,
            body=body(),
        )
        self._revision(await self.prepare(principal, command.export), command.expected_revision)
        artifact = await self.artifacts.get(principal, str(metadata["artifact_id"]), lock=True)
        await operations.record_progress(
            operation_id=operation.id,
            expected_revision=operation.revision,
            update=MCPOperationProgress(
                status="succeeded",
                progress=1,
                stage="prepared_for_delivery",
                created_entities=(
                    MCPCreatedEntity("mcp_artifact", str(artifact.id), "/admin/mcp"),
                ),
            ),
        )
        return {"operation_id": str(operation.id), "status": "succeeded", "artifact": metadata}


def document_export_operation(
    settings: Settings, support: DocumentExcelSupport
) -> MCPDatabaseOperation:
    async def mutate(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        command = DocumentExportCommand.model_validate(payload)
        service = MCPDocumentExportService(context.session, settings, support)
        prepared = await service.prepare(context.principal, command.export)
        service._revision(prepared, command.expected_revision)
        return MCPDatabaseResult(command.model_dump(mode="json"), status="queued")

    async def authorize(context: MCPDatabaseContext, receipt: dict[str, Any]) -> None:
        command = DocumentExportCommand.model_validate(receipt["data"])
        await MCPDocumentExportService(context.session, settings, support)._scope(
            context.principal, command.export
        )

    return MCPDatabaseOperation(DOCUMENT_EXPORT_POLICY, mutate, authorize)
