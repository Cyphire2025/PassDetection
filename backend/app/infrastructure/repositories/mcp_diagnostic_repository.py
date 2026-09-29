"""Selected retained diagnostic fields; never raw audit payloads or job errors."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import AuditLogModel, PassportProcessingJobModel


class MCPDiagnosticRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def audit_records(
        self, *, start: datetime, end: datetime, limit: int,
        audit_id: uuid.UUID | None, request_id: str | None,
        job_id: uuid.UUID | None, event_id: uuid.UUID | None,
    ) -> list[dict[str, Any]]:
        model = AuditLogModel
        statement = select(model.id, model.created_at, model.action, model.entity_type,
                           model.entity_id, model.result,
                           model.metadata_json["failure_category"].as_string().label("failure_category")).where(
                               model.created_at >= start, model.created_at <= end)
        if audit_id is not None:
            statement = statement.where(model.id == audit_id)
        if request_id is not None:
            statement = statement.where(model.metadata_json["request_id"].as_string() == request_id)
        if job_id is not None:
            statement = statement.where(or_(model.entity_id == str(job_id),
                                             model.metadata_json["job_id"].as_string() == str(job_id)))
        if event_id is not None:
            statement = statement.where(model.metadata_json["event_id"].as_string() == str(event_id))
        result = await self.session.execute(statement.order_by(model.created_at.desc(), model.id.desc()).limit(limit + 1))
        return [dict(row) for row in result.mappings()]

    async def passport_jobs(
        self, *, start: datetime, end: datetime, limit: int, job_id: uuid.UUID | None,
    ) -> list[dict[str, Any]]:
        model = PassportProcessingJobModel
        statement = select(model.id, model.submission_id, model.status, model.attempts,
                           model.max_attempts, model.progress, model.cancel_requested,
                           model.created_at, model.updated_at, model.started_at,
                           model.finished_at).where(model.updated_at >= start, model.updated_at <= end)
        if job_id is not None:
            statement = statement.where(model.id == job_id)
        result = await self.session.execute(statement.order_by(model.updated_at.desc(), model.id.desc()).limit(limit + 1))
        return [dict(row) for row in result.mappings()]
