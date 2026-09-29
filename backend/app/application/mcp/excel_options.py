"""Bounded complete Excel option discovery without workbook or history effects."""

from __future__ import annotations

import json
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.artifacts import ArtifactError
from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.excel_source_admission import admit_excel_sources
from app.application.mcp.export_capacity import admitted_export
from app.application.mcp.export_source_budget import ExportSourceBudget
from app.application.mcp.exports import (
    MAX_FIELDS,
    ExcelExportRequest,
    MCPExcelExportService,
    MCPExcelSupport,
)
from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.passports.excel_export_options import (
    ExcelOptionsSupport,
    project_excel_export_options,
)
from app.core.config.settings import Settings
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.repositories.operational_roster import operational_roster_member
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)

MAX_OPTIONS_BYTES = 512 * 1024


class ExcelExportOptionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agency_id: uuid.UUID
    group_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    selection: Literal["group", "selected_groups"] = "group"

    @model_validator(mode="after")
    def coherent_selection(self) -> ExcelExportOptionsRequest:
        if len(set(self.group_ids)) != len(self.group_ids):
            raise ValueError("Duplicate groups")
        if self.selection == "group" and len(self.group_ids) != 1:
            raise ValueError("Group options need exactly one group")
        return self


class MCPExcelOptionsService:
    def __init__(self, session: AsyncSession, settings: Settings, support: MCPExcelSupport):
        self.session, self.settings, self.support = session, settings, support
        self._exports = MCPExcelExportService(session, settings, support)

    @admitted_export
    async def inspect(self, principal: MCPPrincipal, request: ExcelExportOptionsRequest) -> dict[str, Any]:
        try:
            return await self._inspect_options(principal, request)
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) == "55P03":
                raise ArtifactError("Export option sources are busy; retry later", 503) from exc
            raise

    async def _inspect_options(
        self, principal: MCPPrincipal, request: ExcelExportOptionsRequest,
    ) -> dict[str, Any]:
        if "passport_excel" not in self.settings.mcp.export_families:
            raise ArtifactError("Excel options are unavailable in this deployment", 404)
        await self._exports.artifacts._authority(principal, "mcp:export", lock=True)
        budget = ExportSourceBudget(self.session, self.settings)
        actor, groups = await self._exports._scope(
            principal, ExcelExportRequest(**request.model_dump()), budget,
        )
        await admit_excel_sources(
            budget, agency_id=request.agency_id, group_ids=request.group_ids,
            submission_ids=None, baseline_export_id=None, include_workbook_sources=False,
        )
        if request.selection == "group":
            submissions = await self.support.group._current_group_export_submissions(
                self.session, group_id=request.group_ids[0], agency_id=request.agency_id,
                current_user=actor,
            )
        else:
            statement = AuthorizationPolicy.apply_passport_visibility_scope(
                select(PassportSubmissionModel).where(
                    PassportSubmissionModel.agency_id == request.agency_id,
                    PassportSubmissionModel.group_id.in_(request.group_ids),
                    PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
                    operational_roster_member(),
                ), actor,
            )
            rows = (await self.session.scalars(statement.order_by(PassportSubmissionModel.id)
                    .limit(budget.row_limit + 1).execution_options(populate_existing=True))).all()
            if len(rows) > budget.row_limit:
                raise ArtifactError("Export sources exceed the configured row limit", 413)
            submissions = [PassportSubmissionRepository._to_entity(row) for row in rows]
        rows_by_group = await self.support.group._export_whatsapp_match_rows(
            self.session, submissions, groups=groups,
        )
        options = project_excel_export_options(
            groups=groups, submissions=submissions, rows_by_group=rows_by_group,
            selection=request.selection,
            support=ExcelOptionsSupport(
                self.support.group._export_field_catalog,
                self.support.selected._combined_export_field_catalog,
                self.support.group._export_agency_match_field_catalog,
                self.support.group._international_airport_is_enabled,
            ),
        )
        if len(options.fields) > MAX_FIELDS or len(options.agency_match_fields) > MAX_FIELDS:
            raise ArtifactError("Excel options exceed the field limit", 413)
        result = {
            **request.model_dump(mode="json"), **options.model_dump(mode="json"),
            "agency_match_supported": request.selection == "group",
            "maximum_source_rows_per_family": budget.row_limit,
            "maximum_source_bytes": self.settings.mcp.export_source_byte_limit,
            "maximum_fields_per_catalog": MAX_FIELDS,
            "maximum_grouping_fields": MAX_FIELDS + 1,
            "completeness": "complete",
        }
        if len(json.dumps(result, ensure_ascii=True).encode("utf-8")) > MAX_OPTIONS_BYTES:
            raise ArtifactError("Excel options exceed the response limit", 413)
        return result
