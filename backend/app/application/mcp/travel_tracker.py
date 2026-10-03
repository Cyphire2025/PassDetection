"""Reviewed tracker adapters with exact roster matching and durable export recovery."""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import uuid
from collections.abc import AsyncIterator
from functools import partial
from typing import Any

import anyio
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.travel_tracker import (
    TrackerMarkRequest,
    TrackerStatus,
    TrackerTrack,
)
from app.application.mcp.artifacts import CHUNK_BYTES, ArtifactError, MCPArtifactService
from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.change_context import require_change_actor
from app.application.mcp.contact_uploads import MCPContactUploadService
from app.application.mcp.export_capacity import admitted_export
from app.application.mcp.export_source_budget import ExportSourceBudget
from app.application.mcp.group_workbook_plan import require_native_source
from app.application.mcp.input_errors import MCPInputError
from app.application.mcp.operations import (
    MCPCreatedEntity,
    MCPDatabaseContext,
    MCPDatabaseOperation,
    MCPDatabaseResult,
    MCPOperationError,
    MCPOperationProgress,
    MCPOperationService,
)
from app.application.mcp.permissions import require_tool_access
from app.core.config.settings import Settings
from app.domain.exceptions.travel_tracker import TravelTrackerError
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.database.travel_tracker_model import TravelTrackerModel
from app.infrastructure.repositories.sensitive_read_audit import record_sensitive_read
from app.infrastructure.travel_tracker.service import TravelTrackerService
from app.infrastructure.travel_tracker.spreadsheets import (
    MAX_EXPORT_ROWS,
    TrackerSpreadsheetError,
    match_rows,
    read_rows,
)

MAX_WORKBOOK_BYTES = 32 * 1024 * 1024
MARK_POLICY = MCPToolPolicy(
    "set_travel_tracker_status", MCPCapability.CHANGE, frozenset({"update_travel_progress"})
)
IMPORT_POLICY = MCPToolPolicy(
    "apply_travel_tracker_workbook", MCPCapability.CHANGE, frozenset({"update_travel_progress"})
)
EXPORT_POLICY = MCPToolPolicy(
    "prepare_travel_tracker_export", MCPCapability.EXPORT, frozenset({"prepare_export"})
)


class TrackerCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    group_id: uuid.UUID
    update: TrackerMarkRequest


class TrackerWorkbookDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    group_id: uuid.UUID
    upload_id: str = Field(pattern=r"^gcmcp_contacts_[A-Za-z0-9_-]{64}$")
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    sheet_name: str = Field(min_length=1, max_length=31)
    track: TrackerTrack = "visa"
    marked: bool = Field(default=True, strict=True)


class TrackerWorkbookApply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft: TrackerWorkbookDraft
    expected_preview_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class TrackerExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    group_id: uuid.UUID
    track: TrackerTrack = "visa"
    status: TrackerStatus = "all"
    search: str | None = Field(default=None, max_length=160)


class TrackerExportCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    export: TrackerExportRequest
    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")


async def tracker_service(context: MCPDatabaseContext) -> TravelTrackerService:
    actor = await require_change_actor(context, None)
    return TravelTrackerService(context.session, actor, actor_already_fenced=True)


def tracker_input_error(exc: TravelTrackerError) -> MCPInputError:
    if exc.status_code == 409:
        return MCPInputError(
            "tracker_selection_changed",
            "The roster or filtered count changed. Read it again and review the current selection before applying.",
        )
    if exc.status_code in {403, 404}:
        return MCPInputError(
            "tracker_group_unavailable",
            "The selected group or passengers are unavailable under current access.",
        )
    return MCPInputError(
        "invalid_tracker_input",
        "Review the tracker filters, passenger identifiers and workbook limits. No progress was changed.",
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
        ).encode()
    ).hexdigest()


async def preview_workbook(
    context: MCPDatabaseContext, settings: Settings, draft: TrackerWorkbookDraft
) -> dict[str, Any]:
    await require_tool_access(
        context.session,
        settings,
        context.principal.grant_id,
        "preview_travel_tracker_workbook",
        "mcp:upload",
    )
    source = MCPContactUploadService(context.session, settings, purpose="group_workbook")
    try:
        row = await source.get(context.principal, draft.upload_id)
        if not hmac.compare_digest(row.sha256, draft.source_sha256):
            raise ArtifactError("Workbook source changed")
        await require_native_source(context, row, draft.group_id)
        service = await tracker_service(context)
        group = await service._group(draft.group_id, lock=True)
        if group.agency_id != row.agency_id:
            raise ArtifactError("Workbook target changed")
        sheet = next(
            (item for item in row.workbook_snapshot["sheets"] if item["name"] == draft.sheet_name),
            None,
        )
        if sheet is None:
            raise ArtifactError("Worksheet is unavailable")

        # The canonical ingress scanned this immutable source and retained literal
        # values. Parse the explicitly selected sheet; do not fetch URLs or files.
        def parse() -> list[dict[str, Any]]:
            buffer = io.StringIO(newline="")
            csv.writer(buffer).writerows(sheet["rows"])
            return read_rows(buffer.getvalue().encode("utf-8"), "staged.csv")

        records = await anyio.to_thread.run_sync(parse)
        passengers = (
            await context.session.execute(service._roster(group).limit(MAX_EXPORT_ROWS + 1))
        ).all()
        if len(passengers) > MAX_EXPORT_ROWS:
            raise TrackerSpreadsheetError("Tracker matching capacity exceeded")
        preview = await anyio.to_thread.run_sync(
            partial(
                match_rows,
                records,
                [person for person, _ in passengers],
                track=draft.track,
                marked=draft.marked,
            )
        )
    except (ArtifactError, TrackerSpreadsheetError, MCPOperationError) as exc:
        raise MCPInputError(
            "tracker_workbook_unavailable",
            "Use an unexpired native group workbook for this exact group. Select a worksheet with Name, Passport Number or Passenger ID and at most 1,000 passenger rows.",
        ) from exc
    except TravelTrackerError as exc:
        raise tracker_input_error(exc) from exc
    await record_sensitive_read(
        context.session,
        user=service.user,
        kind="group_view",
        agency_id=group.agency_id,
        entity_id=group.id,
        count=len(passengers),
    )
    result = preview.model_dump(mode="json")
    return {
        **result,
        "draft": draft.model_dump(mode="json"),
        "preview_hash": _digest({"draft": draft.model_dump(mode="json"), "preview": result}),
        "content_trust": "untrusted_business_data",
    }


def tracker_mark_operation() -> MCPDatabaseOperation:
    async def mutate(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        command = TrackerCommand.model_validate(payload)
        service = await tracker_service(context)
        try:
            result = await service.mark(command.group_id, command.update, commit=False)
        except TravelTrackerError as exc:
            raise tracker_input_error(exc) from exc
        return MCPDatabaseResult(
            {
                "group_id": str(command.group_id),
                "track": command.update.track,
                "marked": command.update.marked,
                **result.model_dump(mode="json"),
            }
        )

    async def authorize(context: MCPDatabaseContext, receipt: dict[str, Any]) -> None:
        try:
            await (await tracker_service(context))._group(uuid.UUID(receipt["data"]["group_id"]))
        except TravelTrackerError as exc:
            raise tracker_input_error(exc) from exc

    return MCPDatabaseOperation(MARK_POLICY, mutate, authorize)


def tracker_import_operation(settings: Settings) -> MCPDatabaseOperation:
    async def mutate(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        command = TrackerWorkbookApply.model_validate(payload)
        preview = await preview_workbook(context, settings, command.draft)
        if not hmac.compare_digest(preview["preview_hash"], command.expected_preview_hash):
            raise MCPInputError(
                "tracker_preview_changed",
                "The matching result changed. Review a fresh workbook preview before applying it.",
            )
        if not preview["passenger_ids"]:
            raise MCPInputError(
                "tracker_no_matches",
                "The worksheet has no unique matches. Review unmatched and ambiguous rows first.",
            )
        service = await tracker_service(context)
        try:
            result = await service.mark(
                command.draft.group_id,
                TrackerMarkRequest(
                    track=command.draft.track,
                    marked=command.draft.marked,
                    passenger_ids=preview["passenger_ids"],
                ),
                commit=False,
            )
        except TravelTrackerError as exc:
            raise tracker_input_error(exc) from exc
        return MCPDatabaseResult(
            {
                "group_id": str(command.draft.group_id),
                "track": command.draft.track,
                "marked": command.draft.marked,
                "preview_hash": command.expected_preview_hash,
                **result.model_dump(mode="json"),
            }
        )

    async def authorize(context: MCPDatabaseContext, receipt: dict[str, Any]) -> None:
        await require_tool_access(
            context.session,
            settings,
            context.principal.grant_id,
            "preview_travel_tracker_workbook",
            "mcp:upload",
        )
        await (await tracker_service(context))._group(uuid.UUID(receipt["data"]["group_id"]))

    return MCPDatabaseOperation(IMPORT_POLICY, mutate, authorize)


class MCPTravelTrackerExportService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        artifacts: MCPArtifactService | None = None,
    ) -> None:
        self.session, self.settings = session, settings
        self.artifacts = artifacts or MCPArtifactService(session, settings)

    async def scope(
        self, principal: MCPPrincipal, request: TrackerExportRequest
    ) -> tuple[TravelTrackerService, ClientGroupModel]:
        await require_tool_access(
            self.session, self.settings, principal.grant_id, EXPORT_POLICY.name, "mcp:export"
        )
        service = await tracker_service(MCPDatabaseContext(self.session, principal, uuid.uuid4()))
        try:
            group = await service._group(request.group_id, lock=True)
        except TravelTrackerError as exc:
            raise tracker_input_error(exc) from exc
        await self.artifacts._group(principal, group.agency_id, group.id, "export")
        return service, group

    @admitted_export
    async def inspect(
        self, principal: MCPPrincipal, request: TrackerExportRequest
    ) -> dict[str, Any]:
        service, group = await self.scope(principal, request)
        statement = service._filter(
            service._roster(group),
            track=request.track,
            status=request.status,
            search=request.search,
        )
        # Admit/lock scalar identifiers and database-side byte aggregates before
        # JSON passenger/custom fields enter Python. The parent group fence also
        # blocks cooperative roster/mark writers and FK additions during render.
        budget = ExportSourceBudget(self.session, self.settings)
        await budget.retain(ClientGroupModel, ClientGroupModel.id == group.id, update=True)
        selected = statement.with_only_columns(PassportSubmissionModel.id)
        identifiers = await budget.retain(
            PassportSubmissionModel, PassportSubmissionModel.id.in_(selected), update=True
        )
        await budget.retain(
            TravelTrackerModel,
            TravelTrackerModel.passenger_id.in_(identifiers),
            TravelTrackerModel.group_id == group.id,
        )
        rows = (
            await self.session.execute(
                statement.order_by(PassportSubmissionModel.id)
                .limit(self.settings.mcp.export_source_row_limit + 1)
                .execution_options(populate_existing=True)
            )
        ).all()
        if len(rows) > self.settings.mcp.export_source_row_limit:
            raise MCPInputError(
                "tracker_export_capacity",
                "Narrow this MCP export to the configured source row limit; the website supports larger group exports.",
            )

        def values(model: Any) -> dict[str, Any] | None:
            return (
                {column.key: getattr(model, column.key) for column in model.__table__.columns}
                if model
                else None
            )

        snapshot = {
            "group": values(group),
            "passengers": [[values(person), values(progress)] for person, progress in rows],
            "export": request.model_dump(mode="json"),
        }
        encoded = json.dumps(
            snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
        ).encode()
        if len(encoded) > self.settings.mcp.export_source_byte_limit:
            raise MCPInputError(
                "tracker_export_capacity",
                "Narrow this MCP export to the configured source byte limit.",
            )
        return {
            "export": request.model_dump(mode="json"),
            "expected_revision": hashlib.sha256(encoded).hexdigest(),
            "passenger_count": len(rows),
            "maximum_source_rows": self.settings.mcp.export_source_row_limit,
            "maximum_source_bytes": self.settings.mcp.export_source_byte_limit,
            "history_checkpoint": False,
        }

    @admitted_export
    async def generate(self, *, access_token: str, operation_id: uuid.UUID) -> dict[str, Any]:
        operations = MCPOperationService(self.session, self.settings)
        principal = await operations._authorize(
            access_token, "mcp:export", tool_name="generate_travel_tracker_export"
        )
        row = await self.session.scalar(
            select(MCPOperationModel)
            .where(
                MCPOperationModel.id == operation_id,
                MCPOperationModel.user_id == principal.user_id,
                MCPOperationModel.operation_name == EXPORT_POLICY.name,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None or row.initial_result is None:
            raise MCPOperationError("operation_not_found")
        command = TrackerExportCommand.model_validate(row.initial_result["data"])
        service, group = await self.scope(principal, command.export)
        if row.status == "succeeded":
            identifiers = [
                entry["entity_id"]
                for entry in row.created_entities
                if entry["entity_type"] == "mcp_artifact"
            ]
            if len(identifiers) != 1:
                raise MCPOperationError("operation_receipt_unavailable")
            return {
                "operation_id": str(row.id),
                "status": "succeeded",
                "artifact": await self.artifacts.recover_export(
                    principal, uuid.UUID(identifiers[0])
                ),
            }
        if row.status != "queued":
            raise MCPOperationError("export_not_resumable")

        async def revision() -> None:
            current = await self.inspect(principal, command.export)
            if not hmac.compare_digest(current["expected_revision"], command.expected_revision):
                raise MCPInputError(
                    "tracker_export_changed",
                    "The roster, progress or passenger details changed. Inspect and review a new export before preparing it.",
                )

        await revision()
        content, filename = await service.export(
            group.id,
            track=command.export.track,
            status=command.export.status,
            search=command.export.search,
        )
        if len(content) > MAX_WORKBOOK_BYTES:
            raise ArtifactError("Tracker workbook exceeds the 32 MiB limit", 413)
        await revision()

        async def body() -> AsyncIterator[bytes]:
            for offset in range(0, len(content), CHUNK_BYTES):
                yield content[offset : offset + CHUNK_BYTES]

        metadata = await self.artifacts.prepare_export(
            principal,
            agency_id=group.agency_id,
            group_id=group.id,
            purpose="travel_tracker_excel",
            filename=filename,
            body=body(),
        )
        await revision()
        artifact = await self.artifacts.get(principal, str(metadata["artifact_id"]), lock=True)
        await operations.record_progress(
            operation_id=row.id,
            expected_revision=row.revision,
            update=MCPOperationProgress(
                status="succeeded",
                progress=1,
                stage="prepared_for_delivery",
                created_entities=(
                    MCPCreatedEntity("mcp_artifact", str(artifact.id), "/admin/mcp"),
                ),
            ),
        )
        return {"operation_id": str(row.id), "status": "succeeded", "artifact": metadata}


def tracker_export_operation(settings: Settings) -> MCPDatabaseOperation:
    async def mutate(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        command = TrackerExportCommand.model_validate(payload)
        observed = await MCPTravelTrackerExportService(context.session, settings).inspect(
            context.principal, command.export
        )
        if not hmac.compare_digest(observed["expected_revision"], command.expected_revision):
            raise MCPInputError(
                "tracker_export_changed",
                "The selected export changed. Inspect and review the current selection again.",
            )
        return MCPDatabaseResult(command.model_dump(mode="json"), status="queued")

    async def authorize(context: MCPDatabaseContext, receipt: dict[str, Any]) -> None:
        command = TrackerExportCommand.model_validate(receipt["data"])
        await MCPTravelTrackerExportService(context.session, settings).scope(
            context.principal, command.export
        )

    return MCPDatabaseOperation(EXPORT_POLICY, mutate, authorize)
