"""Bounded retained export metadata; no artifact, recovery or completion authority."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPAuthorizationService, MCPPrincipal
from app.application.mcp.credentials import MCPAuthError, utc
from app.application.mcp.read_cursor import MCPReadCursor
from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.passports.export_history_projection import (
    project_history_item,
    project_history_people,
)
from app.core.config.settings import Settings
from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import AuthorizationError
from app.domain.value_objects.passport_export_history import (
    PassportExportKind,
    validated_export_history_ids,
    validated_export_history_people,
    validated_export_kind,
)
from app.infrastructure.database.models import PassportExportHistoryModel
from app.infrastructure.repositories.mcp_export_history_read_repository import (
    MAX_CHECKPOINT_PEOPLE,
    HistorySourceLimit,
    MCPExportHistoryReadRepository,
)
from app.infrastructure.repositories.sensitive_read_audit import record_sensitive_read
from app.infrastructure.repositories.user_repository import UserRepository

MAX_RESPONSE_BYTES = 512 * 1024


class ExportHistoryReadError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@asynccontextmanager
async def _bounded_read() -> AsyncIterator[None]:
    try:
        async with asyncio.timeout(5):
            yield
    except HistorySourceLimit as exc:
        raise ExportHistoryReadError("history_limit") from exc
    except TimeoutError as exc:
        raise ExportHistoryReadError("history_busy") from exc
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) in {"55P03", "57014"}:
            raise ExportHistoryReadError("history_busy") from exc
        raise


class MCPExportHistoryReadService:
    def __init__(self, session: AsyncSession, settings: Settings):
        self.session, self.settings = session, settings
        self.cursors = MCPReadCursor(settings.app_secret_key, "mcp-export-history-v1")

    async def _scope(self, principal: MCPPrincipal, agency_id: uuid.UUID, group_id: uuid.UUID,
                     include_deleted: bool, page_size: int) -> tuple[User, MCPExportHistoryReadRepository]:
        if type(page_size) is not int or not 1 <= page_size <= 100:
            raise ExportHistoryReadError("history_invalid_request")
        authority = MCPAuthorizationService(self.session, self.settings)
        grant = await authority.require_grant(principal.grant_id, lock=True)
        authority.require_capability(grant, "mcp:read")
        if grant.user_id != principal.user_id:
            raise MCPAuthError()
        actor = await UserRepository(self.session).get_by_id(principal.user_id)
        if actor is None:
            raise MCPAuthError()
        repository = MCPExportHistoryReadRepository(self.session, self.settings.mcp.export_source_byte_limit)
        group = await repository.group(agency_id, group_id)
        if group is None or (not include_deleted and (group.deleted_at is not None or group.status == "deleted")):
            raise ExportHistoryReadError("history_unavailable")
        try:
            await AuthorizationPolicy(self.session).require_export_data(actor, group)
        except AuthorizationError as exc:
            raise MCPAuthError("access_denied", 403) from exc
        return actor, repository

    async def _finish(self, result: dict[str, Any], actor: User, agency_id: uuid.UUID,
                      group_id: uuid.UUID, personal: bool) -> dict[str, Any]:
        result.update(agency_id=str(agency_id), group_id=str(group_id), format_version=1,
            status="completed", personal_details_included=personal,
            maximum_checkpoint_people=MAX_CHECKPOINT_PEOPLE,
            maximum_current_roster_ids=MAX_CHECKPOINT_PEOPLE,
            maximum_checkpoint_source_bytes=self.settings.mcp.export_source_byte_limit,
            maximum_response_bytes=MAX_RESPONSE_BYTES)
        if len(json.dumps(result, ensure_ascii=True).encode()) > MAX_RESPONSE_BYTES:
            raise ExportHistoryReadError("history_limit")
        if personal:
            await record_sensitive_read(self.session, user=actor, kind="group_view", agency_id=agency_id,
                entity_id=group_id, count=len(result["items"]))
        return result

    async def list_history(self, principal: MCPPrincipal, *, agency_id: uuid.UUID, group_id: uuid.UUID,
                           kind: PassportExportKind, page_size: int = 25, cursor: str | None = None,
                           include_personal_details: bool = False, include_deleted: bool = False) -> dict[str, Any]:
        async with _bounded_read():
            actor, repository = await self._scope(principal, agency_id, group_id, include_deleted, page_size)
            try:
                validated_export_kind(kind)
                state = self.cursors.read(cursor, dict(user_id=principal.user_id, agency_id=agency_id,
                    group_id=group_id, kind=kind, page_size=page_size,
                    personal=include_personal_details, deleted=include_deleted))
            except ValueError as exc:
                raise ExportHistoryReadError("history_invalid_request") from exc
            current_ids = await repository.current_ids(agency_id, group_id, actor)
            if len(current_ids) > MAX_CHECKPOINT_PEOPLE:
                raise ExportHistoryReadError("history_limit")
            predicates = repository.scope(agency_id, group_id, actor.id if actor.role == UserRole.AGENCY_STAFF else None)
            predicates += [PassportExportHistoryModel.export_kind == kind,
                PassportExportHistoryModel.completed_at <= datetime.fromisoformat(state["cutoff"])]
            total = await repository.history_count(predicates)
            identifiers = await repository.page_ids(predicates, after=self.cursors.after(state), size=page_size)
            rows = await repository.checkpoints(identifiers[:page_size], predicates,
                details=False, personal=include_personal_details)
            items = []
            for row in rows:
                row.created_at, row.completed_at = utc(row.created_at), utc(row.completed_at)
                if isinstance(row.snapshot_submission_ids, list) and len(row.snapshot_submission_ids) > MAX_CHECKPOINT_PEOPLE:
                    raise ExportHistoryReadError("history_limit")
                try:
                    baseline = validated_export_history_ids(row, field_name="snapshot_submission_ids")
                    compatible, new_count = True, len(current_ids - baseline)
                except ValueError:
                    compatible, new_count = False, 0
                try:
                    items.append(project_history_item(row, compatible=compatible,
                        new_submission_count=new_count).model_dump(mode="json"))
                except ValueError as exc:
                    raise ExportHistoryReadError("history_integrity") from exc
            more = len(identifiers) > page_size
            if more and not rows:
                raise ExportHistoryReadError("history_busy")
            return await self._finish(dict(items=items, export_kind=kind, total_count=total,
                current_submission_count=len(current_ids), page_size=page_size, has_more=more,
                next_cursor=self.cursors.next(state, {"id": rows[-1].id, "created_at": rows[-1].completed_at}) if more else None,
                completed_before=state["cutoff"], completeness="partial" if more else "complete",
                consistency="Completion-cutoff keyset; counts and source membership are live. Incompatible checkpoints have unknown new-submission counts (reported as zero)."),
                actor, agency_id, group_id, include_personal_details)

    async def get_history(self, principal: MCPPrincipal, *, agency_id: uuid.UUID, group_id: uuid.UUID,
                          history_id: uuid.UUID, page: int = 1, page_size: int = 50,
                          include_personal_details: bool = False, include_deleted: bool = False) -> dict[str, Any]:
        async with _bounded_read():
            actor, repository = await self._scope(principal, agency_id, group_id, include_deleted, page_size)
            if type(page) is not int or not 1 <= page <= MAX_CHECKPOINT_PEOPLE + 1:
                raise ExportHistoryReadError("history_invalid_request")
            rows = await repository.checkpoints([history_id], repository.scope(agency_id, group_id,
                actor.id if actor.role == UserRole.AGENCY_STAFF else None), details=True, personal=False)
            if not rows:
                raise ExportHistoryReadError("history_unavailable")
            row = rows[0]
            if any(isinstance(value, list) and len(value) > MAX_CHECKPOINT_PEOPLE
                   for value in (row.exported_submission_ids, row.exported_people_snapshot)):
                raise ExportHistoryReadError("history_limit")
            try:
                people = validated_export_history_people(row)
                kind = validated_export_kind(row.export_kind)
                if row.completed_at is None:
                    raise ValueError()
            except ValueError as exc:
                raise ExportHistoryReadError("history_integrity") from exc
            selected = people[(page - 1) * page_size:page * page_size]
            available = await repository.available_ids(agency_id, group_id,
                [uuid.UUID(str(person["submission_id"])) for person in selected])
            return await self._finish(dict(history_id=str(history_id), export_kind=kind,
                created_at=row.created_at.isoformat(), completed_at=row.completed_at.isoformat(),
                exported_count=row.exported_count, pending_recipient_count=row.pending_recipient_count,
                page=page, page_size=page_size, total_pages=(len(people) + page_size - 1) // page_size,
                has_more=page * page_size < len(people), completeness="partial" if page > 1 or len(people) > page_size else "complete",
                items=[person.model_dump(mode="json") for person in project_history_people(selected, available,
                    include_personal_details=include_personal_details)],
                consistency="Frozen exported-person order and optional details; record_available means a same-agency/group source row exists now, not file availability or recovery authority."),
                actor, agency_id, group_id, include_personal_details)
