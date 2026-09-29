"""Durable group tracking XLSX snapshots without passport-history changes."""

from __future__ import annotations

import asyncio
import hmac
import uuid
from collections.abc import AsyncIterator
from typing import Any

import anyio
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.artifacts import CHUNK_BYTES, ArtifactError, MCPArtifactService
from app.application.mcp.authorization import MCPPrincipal
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
from app.application.mcp.tracking_export_source import (
    MAX_TRACKING_BROADCASTS,
    MAX_TRACKING_ROWS,
    linked_broadcasts,
    lock_tracking_source,
)
from app.application.use_cases.passports.prepare_group_excel import PreparedGroupExcel
from app.application.use_cases.passports.prepare_tracking_excel import (
    TrackingExcelSupport,
    TrackingStatus,
    prepare_tracking_excel,
)
from app.core.config.settings import Settings
from app.domain.entities.entities import ClientGroup, User
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import ClientGroupModel
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository

TRACKING_POLICY = MCPToolPolicy(
    "prepare_tracking_export", MCPCapability.EXPORT, frozenset({"prepare_export"})
)
MAX_WORKBOOK_BYTES = 32 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
MAX_FIELDS = 256
_GENERATIONS = anyio.CapacityLimiter(1)


class TrackingExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agency_id: uuid.UUID
    group_id: uuid.UUID
    status: TrackingStatus = "all"
    broadcast_id: uuid.UUID | None = None


class TrackingExportCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    export: TrackingExportRequest
    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")


class MCPTrackingExportService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        support: TrackingExcelSupport,
        *,
        artifacts: MCPArtifactService | None = None,
    ):
        self.session, self.settings, self.support = session, settings, support
        self.artifacts = artifacts or MCPArtifactService(session, settings)

    async def _scope(
        self,
        principal: MCPPrincipal,
        request: TrackingExportRequest,
    ) -> tuple[User, ClientGroup, list[uuid.UUID]]:
        await self.artifacts._authority(principal, "mcp:export", lock=True)
        if self.session.bind is not None and self.session.bind.dialect.name == "postgresql":
            await self.session.execute(text("SET LOCAL lock_timeout = '250ms'"))
        actor = await self.artifacts._group(
            principal, request.agency_id, request.group_id, "export"
        )
        row = await self.session.scalar(
            select(ClientGroupModel)
            .where(
                ClientGroupModel.id == request.group_id,
                ClientGroupModel.agency_id == request.agency_id,
            )
            .with_for_update(nowait=True)
            .execution_options(populate_existing=True)
        )
        if row is None or row.deleted_at or row.status == "deleted":
            raise ArtifactError("Group was not found", 404)
        group = ClientGroupRepository._to_entity(row)
        linked = await linked_broadcasts(self.session, group)
        if not linked or request.broadcast_id is not None and request.broadcast_id not in linked:
            raise ArtifactError("The tracking broadcast selection is no longer linked", 409)
        return actor, group, linked

    @admitted_export
    async def prepare(
        self,
        principal: MCPPrincipal,
        request: TrackingExportRequest,
    ) -> PreparedGroupExcel:
        try:
            actor, group, linked = await self._scope(principal, request)
            submissions = await lock_tracking_source(
                self.session, actor=actor, group=group, broadcasts=linked
            )
            return await prepare_tracking_excel(
                self.session,
                support=self.support,
                group=group,
                submissions=submissions,
                tracking_status=request.status,
                broadcast_id=request.broadcast_id,
                maximum_fields=MAX_FIELDS,
                maximum_snapshot_bytes=MAX_SNAPSHOT_BYTES,
            )
        except DBAPIError as exc:
            self._database_error(exc)
            raise

    @admitted_export
    async def inspect(
        self, principal: MCPPrincipal, request: TrackingExportRequest
    ) -> dict[str, Any]:
        prepared = await self.prepare(principal, request)
        return {
            "export": request.model_dump(mode="json"),
            "expected_revision": prepared.revision,
            "passenger_count": len(prepared.submissions),
            "pending_recipient_count": len(prepared.render_arguments["pending_rows"]),
            "fields": prepared.field_catalog,
            "history_checkpoint": False,
            "maximum_source_rows": MAX_TRACKING_ROWS,
            "maximum_linked_broadcasts": MAX_TRACKING_BROADCASTS,
            "maximum_workbook_bytes": MAX_WORKBOOK_BYTES,
            "maximum_snapshot_bytes": MAX_SNAPSHOT_BYTES,
            "maximum_fields": MAX_FIELDS,
        }

    @staticmethod
    def _database_error(exc: DBAPIError) -> None:
        if getattr(exc.orig, "sqlstate", None) == "55P03":
            raise ArtifactError("Tracking sources are busy; resume later", 503) from exc

    @staticmethod
    def _revision(prepared: PreparedGroupExcel, expected: str) -> None:
        if not hmac.compare_digest(prepared.revision, expected):
            raise MCPOperationError("export_revision_changed")

    @admitted_export
    async def generate(self, *, access_token: str, operation_id: uuid.UUID) -> dict[str, Any]:
        borrower = object()
        try:
            _GENERATIONS.acquire_on_behalf_of_nowait(borrower)
        except anyio.WouldBlock as exc:
            raise ArtifactError("Tracking generation capacity is busy; resume later", 503) from exc
        try:
            return await self._generate(access_token=access_token, operation_id=operation_id)
        except DBAPIError as exc:
            self._database_error(exc)
            raise
        finally:
            _GENERATIONS.release_on_behalf_of(borrower)

    async def _generate(self, *, access_token: str, operation_id: uuid.UUID) -> dict[str, Any]:
        operations = MCPOperationService(self.session, self.settings)
        principal = await operations._authorize(access_token, "mcp:export")
        operation = await self.session.scalar(
            select(MCPOperationModel)
            .where(
                MCPOperationModel.id == operation_id,
                MCPOperationModel.user_id == principal.user_id,
                MCPOperationModel.operation_name == TRACKING_POLICY.name,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if operation is None or operation.initial_result is None:
            raise MCPOperationError("operation_not_found")
        command = TrackingExportCommand.model_validate(operation.initial_result["data"])
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
        # PreparedGroupExcel drains its native worker on cancellation. Capacity
        # is retained until that worker exits, even when the deadline is reached.
        async with asyncio.timeout(120):
            content = await prepared.render()
        if len(content) > MAX_WORKBOOK_BYTES:
            raise ArtifactError("Tracking workbook exceeds its size limit", 413)
        self._revision(await self.prepare(principal, command.export), command.expected_revision)

        async def body() -> AsyncIterator[bytes]:
            for offset in range(0, len(content), CHUNK_BYTES):
                yield content[offset : offset + CHUNK_BYTES]

        metadata = await self.artifacts.prepare_export(
            principal,
            agency_id=command.export.agency_id,
            group_id=command.export.group_id,
            purpose="whatsapp_tracking_excel",
            filename=f"whatsapp-tracking-{command.export.status}.xlsx",
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


def tracking_export_operation(
    settings: Settings, support: TrackingExcelSupport
) -> MCPDatabaseOperation:
    async def mutate(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        command = TrackingExportCommand.model_validate(payload)
        service = MCPTrackingExportService(context.session, settings, support)
        prepared = await service.prepare(context.principal, command.export)
        service._revision(prepared, command.expected_revision)
        return MCPDatabaseResult(command.model_dump(mode="json"), status="queued")

    async def authorize(context: MCPDatabaseContext, receipt: dict[str, Any]) -> None:
        command = TrackingExportCommand.model_validate(receipt["data"])
        await MCPTrackingExportService(context.session, settings, support)._scope(
            context.principal, command.export
        )

    return MCPDatabaseOperation(TRACKING_POLICY, mutate, authorize)
