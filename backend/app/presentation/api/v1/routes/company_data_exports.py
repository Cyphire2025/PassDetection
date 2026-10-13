"""Private durable export receipts; browser downloads stream without public URLs."""

import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.access import COMPANY_ADMIN_ROLES, require_company
from app.application.companies.data_exports import (
    ExportRequest,
    ExportStatus,
    request_export,
    require_export,
    status_response,
)
from app.application.mcp.read_cursor import MCPReadCursor
from app.core.config.settings import Settings, get_settings
from app.domain.entities.entities import User
from app.infrastructure.database.company_data_export_models import CompanyDataExportJobModel as Job
from app.infrastructure.database.company_data_export_models import (
    CompanyDataExportPartModel as Part,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.routes.company_people import private_response
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter(dependencies=[Depends(private_response), Depends(require_cookie_csrf)])


class ExportPage(BaseModel):
    items: list[ExportStatus]
    next_cursor: str | None
    has_more: bool


class ExportPart(BaseModel):
    id: uuid.UUID
    part_number: int
    filename: str
    content_type: str
    byte_size: int
    record_count: int


class ExportPartPage(BaseModel):
    items: list[ExportPart]
    next_cursor: int | None
    has_more: bool


def part_response(part: Part) -> ExportPart:
    extension = "xlsx" if part.part_kind == "workbook" else "zip"
    return ExportPart(id=part.id, part_number=part.part_number,
        filename=f"company-data-{part.job_id}-part-{part.part_number}.{extension}",
        content_type=part.content_type, byte_size=part.byte_size, record_count=part.record_count)


@router.post("/{company_id}/data-exports", response_model=ExportStatus, status_code=202)
async def create_export(company_id: uuid.UUID, body: ExportRequest, agency_id: uuid.UUID | None = None,
    user: User = Depends(require_role(list(COMPANY_ADMIN_ROLES))), session: AsyncSession = Depends(get_db_session),
) -> ExportStatus:
    return status_response(await request_export(session, user=user, agency_id=agency_id, company_id=company_id, body=body))


@router.get("/{company_id}/data-exports", response_model=ExportPage)
async def list_exports(company_id: uuid.UUID, agency_id: uuid.UUID | None = None,
    cursor: str | None = Query(default=None, max_length=2048), page_size: int = Query(default=10, ge=1, le=50),
    user: User = Depends(require_role(list(COMPANY_ADMIN_ROLES))), session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> ExportPage:
    company = await require_company(session, user=user, agency_id=agency_id, company_id=company_id)
    codec = MCPReadCursor(settings.app_secret_key, "company-data-export-jobs-v1")
    try:
        state = codec.read(cursor, {"actor": str(user.id), "agency": str(company.agency_id), "company": str(company.id)})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    query = select(Job).where(Job.agency_id == company.agency_id, Job.company_id == company.id,
        Job.requested_by_user_id == user.id, Job.created_at <= datetime.fromisoformat(state["cutoff"]))
    if after := codec.after(state):
        query = query.where((Job.created_at < after[0]) | ((Job.created_at == after[0]) & (Job.id < after[1])))
    rows = list((await session.scalars(query.order_by(Job.created_at.desc(), Job.id.desc()).limit(page_size + 1))).all())
    more, rows = len(rows) > page_size, rows[:page_size]
    return ExportPage(items=[status_response(row) for row in rows], has_more=more,
        next_cursor=codec.next(state, {"id": rows[-1].id, "created_at": rows[-1].created_at}) if more else None)


@router.get("/{company_id}/data-exports/{job_id}", response_model=ExportStatus)
async def get_export(company_id: uuid.UUID, job_id: uuid.UUID, agency_id: uuid.UUID | None = None,
    user: User = Depends(require_role(list(COMPANY_ADMIN_ROLES))), session: AsyncSession = Depends(get_db_session),
) -> ExportStatus:
    return status_response(await require_export(session, user=user, agency_id=agency_id, company_id=company_id, job_id=job_id))


@router.get("/{company_id}/data-exports/{job_id}/parts", response_model=ExportPartPage)
async def export_parts(company_id: uuid.UUID, job_id: uuid.UUID, agency_id: uuid.UUID | None = None,
    cursor: int = Query(default=0, ge=0), page_size: int = Query(default=25, ge=1, le=100),
    user: User = Depends(require_role(list(COMPANY_ADMIN_ROLES))), session: AsyncSession = Depends(get_db_session),
) -> ExportPartPage:
    job = await require_export(session, user=user, agency_id=agency_id, company_id=company_id, job_id=job_id)
    if job.status != "succeeded":
        raise HTTPException(409, "The export is not ready.")
    rows = list((await session.scalars(select(Part).where(Part.agency_id == job.agency_id,
        Part.company_id == job.company_id, Part.job_id == job.id, Part.part_kind.in_(("workbook", "images")),
        Part.part_number > cursor, Part.purged_at.is_(None)).order_by(Part.part_number).limit(page_size + 1))).all())
    more, rows = len(rows) > page_size, rows[:page_size]
    return ExportPartPage(items=[part_response(row) for row in rows], has_more=more,
        next_cursor=rows[-1].part_number if more else None)


@router.get("/{company_id}/data-exports/{job_id}/parts/{part_id}/download")
async def download_export_part(company_id: uuid.UUID, job_id: uuid.UUID, part_id: uuid.UUID,
    agency_id: uuid.UUID | None = None, user: User = Depends(require_role(list(COMPANY_ADMIN_ROLES))),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    job = await require_export(session, user=user, agency_id=agency_id, company_id=company_id, job_id=job_id)
    part = await session.scalar(select(Part).where(Part.id == part_id, Part.job_id == job.id,
        Part.agency_id == job.agency_id, Part.company_id == job.company_id, Part.part_kind.in_(("workbook", "images")), Part.purged_at.is_(None)))
    if job.status != "succeeded" or part is None:
        raise HTTPException(404, "Export file unavailable")
    response = part_response(part)
    key, size, media = part.object_key, part.byte_size, part.content_type
    await session.commit()
    return StreamingResponse(MinioStorageRepository().stream_file(key, start=0, expected_bytes=size),
        media_type=media, headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
            "Content-Length": str(size), "Content-Disposition": f'attachment; filename="{response.filename}"',
            "Referrer-Policy": "no-referrer"})


@router.get("/{company_id}/data-exports/{job_id}/manifest")
async def export_manifest(company_id: uuid.UUID, job_id: uuid.UUID, agency_id: uuid.UUID | None = None,
    user: User = Depends(require_role(list(COMPANY_ADMIN_ROLES))), session: AsyncSession = Depends(get_db_session),
) -> Response:
    job = await require_export(session, user=user, agency_id=agency_id, company_id=company_id, job_id=job_id)
    if job.status != "succeeded":
        raise HTTPException(409, "The export is not ready.")
    # The top-level manifest contains no PII or object locators. Full image
    # lineage lives in each bounded ZIP manifest; parts are independently paged.
    content = {"format_version": 1, "job": status_response(job).model_dump(mode="json"),
        "parts_endpoint": f"/companies/{company_id}/data-exports/{job_id}/parts", "part_page_size": 25,
        "document_lineage": "Each ZIP contains manifest.json with traveller, document, version, side and checksum."}
    return Response(json.dumps(content), media_type="application/json", headers={"Cache-Control": "private, no-store",
        "Content-Disposition": f'attachment; filename="company-export-{job_id}-manifest.json"'})
