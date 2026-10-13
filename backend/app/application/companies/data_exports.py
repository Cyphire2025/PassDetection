"""Request/authorization boundary for durable, private company data exports."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import literal, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.access import require_company
from app.application.companies.source_documents import indexing_pending
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import AuthorizationError, ConflictError, EntityNotFoundError
from app.domain.services.traveller_verification import utc
from app.infrastructure.database.company_data_export_models import CompanyDataExportJobModel as Job
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["excel", "images"]
    idempotency_key: str = Field(min_length=1, max_length=128)


class ExportStatus(BaseModel):
    id: uuid.UUID
    kind: str
    status: str
    processed_count: int
    part_count: int
    created_at: datetime
    expires_at: datetime
    error_code: str | None


def status_response(job: Job) -> ExportStatus:
    return ExportStatus(id=job.id, kind=job.kind, status="expired" if utc(job.expires_at) <= datetime.now(UTC) else job.status, processed_count=job.processed_count,
        part_count=(int(job.status == "succeeded") if job.kind == "excel" else job.part_count),
        created_at=job.created_at, expires_at=job.expires_at, error_code=job.last_error_code)


async def request_export(session: AsyncSession, *, user: User, agency_id: uuid.UUID | None,
    company_id: uuid.UUID, body: ExportRequest,
) -> Job:
    # Company lock serializes admission and idempotency, not the actual work.
    company = await require_company(session, user=user, agency_id=agency_id, company_id=company_id, lock=True)
    previous = await session.scalar(select(Job).where(Job.agency_id == company.agency_id,
        Job.company_id == company.id, Job.requested_by_user_id == user.id, Job.idempotency_key == body.idempotency_key))
    if previous:
        if previous.kind != body.kind:
            raise ConflictError("The request key was already used for another export.")
        return previous
    if await indexing_pending(session, company.agency_id, company.id):
        raise ConflictError("Saved records are still being prepared. Request an export when indexing finishes.")
    queued = list((await session.scalars(select(Job.id).where(Job.agency_id == company.agency_id,
        Job.company_id == company.id, Job.status.in_((literal("queued", literal_execute=True),
            literal("running", literal_execute=True)))).limit(2))).all())
    if len(queued) >= 2:
        raise ConflictError("Two exports are already pending for this client. Wait for them to finish.")
    now = datetime.now(UTC)
    job = Job(agency_id=company.agency_id, company_id=company.id, requested_by_user_id=user.id,
        kind=body.kind, phase="people" if body.kind == "excel" else "retained_images",
        idempotency_key=body.idempotency_key, company_revision=company.revision,
        created_at=now, available_at=now, expires_at=now + timedelta(days=2))
    session.add(job)
    await session.flush()
    await AuditLogRepository(session).record(action="company.data_export_requested", entity_type="client_organization",
        entity_id=str(company.id), agency_id=company.agency_id, user_id=user.id,
        metadata={"job_id": str(job.id), "kind": body.kind})
    return job


async def require_export(session: AsyncSession, *, user: User, company_id: uuid.UUID,
    agency_id: uuid.UUID | None, job_id: uuid.UUID,
) -> Job:
    company = await require_company(session, user=user, agency_id=agency_id, company_id=company_id)
    job = await session.scalar(select(Job).where(Job.id == job_id, Job.agency_id == company.agency_id,
        Job.company_id == company.id, Job.requested_by_user_id == user.id))
    if job is None:
        raise EntityNotFoundError("Export", job_id)
    if job.company_revision != company.revision or utc(job.expires_at) <= datetime.now(UTC):
        raise AuthorizationError("This export is no longer available. Request a fresh export.")
    return job


async def invalidate_company_exports(session: AsyncSession, agency_id: uuid.UUID,
    company_id: uuid.UUID, *, pending_only: bool = False,
) -> None:
    query = update(Job).where(Job.agency_id == agency_id, Job.company_id == company_id,
        Job.status.in_(("queued", "running") if pending_only else ("queued", "running", "succeeded")))
    await session.execute(query.values(status="cancelled", last_error_code="source_authority_changed"))
