"""Recoverable Excel generation with a committed DB-only request receipt.

Generation is a separate, caller-committed transaction. It never runs inside an
MCPOperation callback. Private storage may retain an orphan after rollback; its
lifecycle expires only transfer copies. Expired successful exports never rebuild.
"""

from __future__ import annotations

import asyncio
import hmac
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

import anyio
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.artifacts import CHUNK_BYTES, ArtifactError, MCPArtifactService
from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.excel_source_admission import admit_excel_sources
from app.application.mcp.export_capacity import admitted_export
from app.application.mcp.export_source_budget import ExportSourceBudget
from app.application.mcp.operations import (
    MCPCreatedEntity,
    MCPDatabaseContext,
    MCPDatabaseOperation,
    MCPDatabaseResult,
    MCPOperationError,
    MCPOperationProgress,
    MCPOperationService,
)
from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.passports.excel_snapshot import ExcelSnapshotTooLarge
from app.application.use_cases.passports.prepare_group_excel import (
    ExcelPreparationSupport,
    PreparedGroupExcel,
    prepare_group_excel,
)
from app.application.use_cases.passports.prepare_selected_excel import (
    SelectedExcelSupport,
    prepare_selected_groups_excel,
    prepare_selected_passports_excel,
)
from app.core.config.settings import Settings
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES, User
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import (
    ClientGroupModel,
    PassportSubmissionModel,
)
from app.infrastructure.export.workbook_capacity import WorkbookCapacityError
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.operational_roster import operational_roster_member
from app.infrastructure.repositories.passport_export_history_repository import (
    PassportExportHistoryRepository,
)
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)

EXCEL_POLICY = MCPToolPolicy(
    "prepare_excel_export", MCPCapability.EXPORT, frozenset({"prepare_export"})
)
_GENERATIONS = anyio.CapacityLimiter(2)
MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
MAX_FIELDS = 256
MAX_WORKBOOK_CELLS = 250_000
MAX_WORKBOOK_COLUMNS = 320
MAX_WORKBOOK_BYTES = 32 * 1024 * 1024
RENDER_TIMEOUT_SECONDS = 120


class ExcelExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    agency_id: uuid.UUID
    group_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    selection: Literal["group", "selected_groups", "selected_passports"] = "group"
    submission_ids: list[uuid.UUID] = Field(default_factory=list, max_length=1500)
    mode: Literal["all", "incremental"] = "all"
    baseline_export_id: uuid.UUID | None = None
    supplemental_fields: list[str] | None = Field(default=None, max_length=256)
    group_by_field: str | None = Field(default=None, max_length=180)
    agency_match_field: str | None = Field(default=None, max_length=180)

    @model_validator(mode="after")
    def coherent_selection(self) -> ExcelExportRequest:
        if len(set(self.group_ids)) != len(self.group_ids):
            raise ValueError("Duplicate groups")
        if self.selection == "group" and len(self.group_ids) != 1:
            raise ValueError("Group export needs exactly one group")
        if self.selection != "group" and (
            self.mode != "all" or self.baseline_export_id or self.agency_match_field
        ):
            raise ValueError("Selected exports do not support incremental or agency matching")
        if (self.mode == "incremental") != (self.baseline_export_id is not None):
            raise ValueError("Incremental exports require a completed baseline")
        if self.selection == "selected_passports":
            if not self.submission_ids or self.supplemental_fields or self.group_by_field:
                raise ValueError("Selected passport export needs explicit IDs and fixed columns")
        elif self.submission_ids:
            raise ValueError("Submission IDs only apply to selected passport export")
        if len(set(self.submission_ids)) != len(self.submission_ids):
            raise ValueError("Duplicate passports")
        if self.supplemental_fields is not None and any(
            not key or len(key) > 180 or "," in key for key in self.supplemental_fields
        ):
            raise ValueError("Invalid field key")
        return self


class ExcelExportCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    export: ExcelExportRequest
    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")


@dataclass(frozen=True)
class MCPExcelSupport:
    group: ExcelPreparationSupport
    selected: SelectedExcelSupport


class MCPExcelExportService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        support: MCPExcelSupport,
        *,
        artifacts: MCPArtifactService | None = None,
    ):
        self.session, self.settings, self.support = session, settings, support
        self.artifacts = artifacts or MCPArtifactService(session, settings)

    async def _scope(
        self, principal: MCPPrincipal, request: ExcelExportRequest,
        budget: ExportSourceBudget | None = None,
    ) -> tuple[User, list[Any]]:
        # Reject oversized metadata before _group or any full group ORM read.
        budget = budget or ExportSourceBudget(self.session, self.settings)
        identifiers = await budget.retain(
            ClientGroupModel,
            ClientGroupModel.id.in_(request.group_ids),
            ClientGroupModel.agency_id == request.agency_id,
            ClientGroupModel.deleted_at.is_(None),
            ClientGroupModel.status != "deleted",
            update=True,
        )
        if set(identifiers) != set(request.group_ids):
            raise ArtifactError("Group was not found", 404)
        # Every requested pair remains explicit; no partial filtering of missing groups.
        actor: User | None = None
        groups_by_id = {}
        for identifier in sorted(request.group_ids):
            actor = await self.artifacts._group(principal, request.agency_id, identifier, "export")
            row = await self.session.scalar(
                select(ClientGroupModel)
                .where(
                    ClientGroupModel.id == identifier,
                    ClientGroupModel.agency_id == request.agency_id,
                )
                .with_for_update(nowait=True)
                .execution_options(populate_existing=True)
            )
            if row is None or row.deleted_at or row.status == "deleted":
                raise ArtifactError("Group was not found", 404)
            groups_by_id[identifier] = ClientGroupRepository._to_entity(row)
        assert actor is not None
        return actor, [groups_by_id[identifier] for identifier in request.group_ids]

    @admitted_export
    async def prepare(
        self,
        principal: MCPPrincipal,
        request: ExcelExportRequest,
    ) -> PreparedGroupExcel:
        try:
            return await self._prepare(principal, request)
        except ExcelSnapshotTooLarge as exc:
            raise ArtifactError(str(exc), 413) from exc
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) == "55P03":
                raise ArtifactError(
                    "Export sources are busy; resume this operation later", 503
                ) from exc
            raise

    async def _prepare(
        self,
        principal: MCPPrincipal,
        request: ExcelExportRequest,
    ) -> PreparedGroupExcel:
        await self.artifacts._authority(principal, "mcp:export", lock=True)
        budget = ExportSourceBudget(self.session, self.settings)
        actor, groups = await self._scope(principal, request, budget)
        await admit_excel_sources(
            budget,
            agency_id=request.agency_id,
            group_ids=request.group_ids,
            submission_ids=(
                request.submission_ids if request.selection == "selected_passports" else None
            ),
            baseline_export_id=request.baseline_export_id,
        )
        stmt = select(PassportSubmissionModel).where(
            PassportSubmissionModel.agency_id == request.agency_id,
            PassportSubmissionModel.group_id.in_(request.group_ids),
            PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
            operational_roster_member(),
        )
        if request.selection == "selected_passports":
            stmt = stmt.where(PassportSubmissionModel.id.in_(request.submission_ids))
        stmt = AuthorizationPolicy.apply_passport_visibility_scope(stmt, actor)
        models = (
            await self.session.scalars(
                stmt.order_by(PassportSubmissionModel.id)
                .limit(budget.row_limit + 1)
                .with_for_update(read=True, nowait=True)
                .execution_options(populate_existing=True)
            )
        ).all()
        if len(models) > budget.row_limit:
            raise ArtifactError("Export sources exceed the configured row limit", 413)
        submissions = [PassportSubmissionRepository._to_entity(model) for model in models]
        if request.selection == "group":
            return await prepare_group_excel(
                self.session,
                support=self.support.group,
                current_user=actor,
                agency_id=request.agency_id,
                group=groups[0],
                export_mode=request.mode,
                baseline_export_id=request.baseline_export_id,
                supplemental_fields=(
                    ",".join(request.supplemental_fields)
                    if request.supplemental_fields is not None
                    else None
                ),
                group_by_field=request.group_by_field,
                agency_match_field=request.agency_match_field,
                maximum_fields=MAX_FIELDS,
                maximum_snapshot_bytes=MAX_SNAPSHOT_BYTES,
            )
        if request.selection == "selected_passports":
            if {member.id for member in submissions} != set(request.submission_ids):
                raise ArtifactError("One or more selected passports are unavailable", 404)
            return await prepare_selected_passports_excel(
                self.session,
                support=self.support.selected,
                submissions=submissions,
                agency_id=request.agency_id,
                maximum_snapshot_bytes=MAX_SNAPSHOT_BYTES,
            )
        return await prepare_selected_groups_excel(
            self.session,
            support=self.support.selected,
            groups=groups,
            submissions=submissions,
            agency_id=request.agency_id,
            supplemental_fields=request.supplemental_fields or [],
            group_by_field=request.group_by_field,
            maximum_fields=MAX_FIELDS,
            maximum_snapshot_bytes=MAX_SNAPSHOT_BYTES,
        )

    @admitted_export
    async def inspect(self, principal: MCPPrincipal, request: ExcelExportRequest) -> dict[str, Any]:
        prepared = await self.prepare(principal, request)
        return {
            "export": request.model_dump(mode="json"),
            "expected_revision": prepared.revision,
            "passenger_count": len(prepared.submissions),
            "pending_recipient_count": len(prepared.render_arguments.get("pending_rows", [])),
            "fields": prepared.field_catalog,
            "history_checkpoint": request.selection == "group",
            "maximum_source_rows_per_family": self.settings.mcp.export_source_row_limit,
            "maximum_source_bytes": self.settings.mcp.export_source_byte_limit,
            "maximum_snapshot_bytes": MAX_SNAPSHOT_BYTES,
            "maximum_fields": MAX_FIELDS,
            "maximum_workbook_cells": MAX_WORKBOOK_CELLS,
            "maximum_workbook_columns": MAX_WORKBOOK_COLUMNS,
            "maximum_workbook_bytes": MAX_WORKBOOK_BYTES,
        }

    @admitted_export
    async def generate(self, *, access_token: str, operation_id: uuid.UUID) -> dict[str, Any]:
        """Caller commits this separately from execute(); all remote I/O is here."""
        borrower = object()
        try:
            _GENERATIONS.acquire_on_behalf_of_nowait(borrower)
        except anyio.WouldBlock as exc:
            raise ArtifactError("Export generation capacity is busy; retry later", 503) from exc
        try:
            return await self._generate(access_token=access_token, operation_id=operation_id)
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) == "55P03":
                raise ArtifactError(
                    "Export sources are busy; resume this operation later", 503
                ) from exc
            raise
        finally:
            _GENERATIONS.release_on_behalf_of(borrower)

    async def _generate(self, *, access_token: str, operation_id: uuid.UUID) -> dict[str, Any]:
        operations = MCPOperationService(self.session, self.settings)
        principal = await operations._authorize(access_token, "mcp:export", tool_name="generate_excel_export")
        row = await self.session.scalar(
            select(MCPOperationModel)
            .where(
                MCPOperationModel.id == operation_id,
                MCPOperationModel.user_id == principal.user_id,
                MCPOperationModel.operation_name == EXCEL_POLICY.name,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None or row.initial_result is None:
            raise MCPOperationError("operation_not_found")
        command = ExcelExportCommand.model_validate(row.initial_result["data"])
        await self._scope(principal, command.export)
        if row.status == "succeeded":
            identifiers = [
                entity["entity_id"]
                for entity in row.created_entities
                if entity["entity_type"] == "mcp_artifact"
            ]
            if len(identifiers) != 1:
                raise MCPOperationError("operation_receipt_unavailable")
            result = await self.artifacts.recover_export(principal, uuid.UUID(identifiers[0]))
            return {"operation_id": str(row.id), "status": "succeeded", "artifact": result}
        if row.status != "queued":
            raise MCPOperationError("export_not_resumable")
        prepared = await self.prepare(principal, command.export)
        self._revision(prepared, command.expected_revision)
        try:
            async with asyncio.timeout(RENDER_TIMEOUT_SECONDS):
                content = await prepared.render(
                    maximum_cells=MAX_WORKBOOK_CELLS,
                    maximum_columns=MAX_WORKBOOK_COLUMNS,
                    maximum_output_bytes=MAX_WORKBOOK_BYTES,
                )
        except WorkbookCapacityError as exc:
            raise ArtifactError(str(exc), 413) from exc
        if len(content) > MAX_WORKBOOK_BYTES:
            raise ArtifactError("Workbook exceeds its output limit", 413)
        # Re-read all render inputs after the off-thread render before retaining a checkpoint.
        self._revision(await self.prepare(principal, command.export), command.expected_revision)
        history = None
        if prepared.history_fields:
            history = await PassportExportHistoryRepository(self.session).record(
                **{
                    **prepared.history_fields,
                    "artifact_metadata": {
                        **prepared.history_fields["artifact_metadata"],
                        "workbook_bytes": len(content),
                    },
                },
                request_id=row.id,
            )

        async def body() -> AsyncIterator[bytes]:
            for offset in range(0, len(content), CHUNK_BYTES):
                yield content[offset : offset + CHUNK_BYTES]

        metadata = await self.artifacts.prepare_export(
            principal,
            agency_id=command.export.agency_id,
            group_id=command.export.group_ids[0],
            purpose="passport_excel",
            filename="passport-export.xlsx",
            body=body(),
            export_history_id=history.id if history else None,
            association_groups=[
                {"agency_id": str(command.export.agency_id), "group_id": str(group_id)}
                for group_id in command.export.group_ids
            ],
        )
        self._revision(await self.prepare(principal, command.export), command.expected_revision)
        artifact = await self.artifacts.get(principal, str(metadata["artifact_id"]), lock=True)
        await operations.record_progress(
            operation_id=row.id,
            expected_revision=row.revision,
            update=MCPOperationProgress(
                status="succeeded",
                progress=1.0,
                stage="prepared_for_delivery",
                created_entities=(
                    MCPCreatedEntity("mcp_artifact", str(artifact.id), "/admin/mcp"),
                ),
            ),
        )
        return {"operation_id": str(row.id), "status": "succeeded", "artifact": metadata}

    @staticmethod
    def _revision(prepared: PreparedGroupExcel, expected: str) -> None:
        if not hmac.compare_digest(prepared.revision, expected):
            raise MCPOperationError("export_revision_changed")


def excel_export_operation(settings: Settings, support: MCPExcelSupport) -> MCPDatabaseOperation:
    async def mutate(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        command = ExcelExportCommand.model_validate(payload)
        service = MCPExcelExportService(context.session, settings, support)
        prepared = await service.prepare(context.principal, command.export)
        service._revision(prepared, command.expected_revision)
        return MCPDatabaseResult(command.model_dump(mode="json"), status="queued")

    async def authorize(context: MCPDatabaseContext, receipt: dict[str, Any]) -> None:
        command = ExcelExportCommand.model_validate(receipt["data"])
        await MCPExcelExportService(context.session, settings, support)._scope(
            context.principal,
            command.export,
        )

    return MCPDatabaseOperation(EXCEL_POLICY, mutate, authorize)
