"""Lazy original source attachments when historical identity context is incomplete."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.access import (
    COMPANY_ADMIN_ROLES,
    require_company,
    visible_company_groups,
)
from app.application.companies.people import require_person
from app.application.companies.people_contracts import SourceDocument, SourceDocumentPage
from app.application.companies.source_chronology import source_page_cursor
from app.application.companies.source_documents import (
    SOURCE_SIDES,
    require_source,
    source_document_key,
)
from app.application.mcp.read_cursor import MCPReadCursor
from app.application.travellers.asset_policy import (
    MAX_PRIVATE_DOCUMENT_BYTES,
    PRIVATE_DOCUMENT_TYPES,
)
from app.core.config.settings import Settings, get_settings
from app.domain.entities.entities import OFFICE_VISIBLE_PASSPORT_STATUS_VALUES, User
from app.infrastructure.database.models import ClientGroupModel as Group
from app.infrastructure.database.models import PassportSubmissionModel as Submission
from app.infrastructure.database.session import get_db_session
from app.infrastructure.database.traveller_reuse_models import TravellerMatchCaseModel as MatchCase
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter(dependencies=[Depends(require_cookie_csrf)])


@router.get("/{company_id}/people/{person_id}/sources", response_model=SourceDocumentPage)
async def person_sources(company_id: uuid.UUID, person_id: uuid.UUID, agency_id: uuid.UUID | None = None,
    cursor: str | None = Query(default=None, max_length=2048), page_size: int = Query(default=20, ge=1, le=50),
    user: User = Depends(require_role(list(COMPANY_ADMIN_ROLES))), session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> SourceDocumentPage:
    company = await require_company(session, user=user, company_id=company_id, agency_id=agency_id)
    await require_person(session, user=user, agency_id=company.agency_id, company_id=company.id, person_id=person_id)
    codec = MCPReadCursor(settings.app_secret_key, "company-person-sources-v2")
    try:
        state = codec.read(cursor, {"actor": str(user.id), "agency": str(company.agency_id),
            "company": str(company.id), "person": str(person_id)})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    groups = visible_company_groups(user, company.agency_id, company.id).with_only_columns(Group.id)
    query = select(MatchCase, Group.name).join(Group, Group.id == MatchCase.group_id).where(
        MatchCase.agency_id == company.agency_id, MatchCase.company_id == company.id,
        MatchCase.traveller_id == person_id, MatchCase.group_id.in_(groups),
        MatchCase.source_kind == "passport_submission", MatchCase.status == "resolved",
        MatchCase.created_at <= datetime.fromisoformat(state["cutoff"]))
    if after := codec.after(state):
        seek = ((MatchCase.source_created_at < after[0])
            | ((MatchCase.source_created_at == after[0]) & (MatchCase.id < after[1]))
            | MatchCase.source_created_at.is_(None))
        if state.get("unknown_source_date"):
            seek = MatchCase.source_created_at.is_(None) & (MatchCase.id < after[1])
        query = query.where(seek)
    cases = list((await session.execute(query.order_by(MatchCase.source_created_at.desc().nullslast(), MatchCase.id.desc())
        .limit(page_size + 1))).all())
    more, cases = len(cases) > page_size, cases[:page_size]
    # One bounded batch; malformed historical references fail closed.
    ids = []
    for case, _ in cases:
        try:
            ids.append(uuid.UUID(case.source_row_key))
        except ValueError:
            continue
    sources = {str(row.id): row for row in (await session.execute(select(Submission.id, Submission.group_id,
        Submission.created_at, Submission.extraction_revision,
        *(getattr(Submission, column) for column in SOURCE_SIDES.values())).where(
        Submission.id.in_(ids), Submission.agency_id == company.agency_id, Submission.group_id.in_(groups),
        Submission.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES)))).all()}
    items = []
    for case, group_name in cases:
        source = sources.get(case.source_row_key)
        if source is not None and source.group_id == case.group_id:
            items.append(SourceDocument(id=source.id, group_id=source.group_id, group_name=group_name,
                created_at=source.created_at, revision_number=source.extraction_revision,
                available_sides=[side for side, column in SOURCE_SIDES.items() if getattr(source, column)]))
    return SourceDocumentPage(items=items, has_more=more,
        next_cursor=source_page_cursor(codec, state, cases, more))


@router.get("/{company_id}/people/{person_id}/sources/{source_id}/assets/{side}")
async def person_source_asset(company_id: uuid.UUID, person_id: uuid.UUID, source_id: uuid.UUID,
    side: str, agency_id: uuid.UUID | None = None, user: User = Depends(require_role(list(COMPANY_ADMIN_ROLES))),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    company = await require_company(session, user=user, company_id=company_id, agency_id=agency_id)
    await require_person(session, user=user, agency_id=company.agency_id, company_id=company.id, person_id=person_id)
    source = await require_source(session, user=user, agency_id=company.agency_id, company_id=company.id,
        person_id=person_id, source_id=source_id)
    key = await source_document_key(session, source, side)
    await AuditLogRepository(session).record(action="traveller.staff_source_document_viewed", entity_type="traveller_profile",
        entity_id=str(person_id), agency_id=company.agency_id, user_id=user.id,
        metadata={"source_id": str(source_id), "side": side})
    await session.commit()
    storage = MinioStorageRepository()
    metadata = await storage.stat_file(key)
    if metadata.content_type not in PRIVATE_DOCUMENT_TYPES or not 0 < metadata.size_bytes <= MAX_PRIVATE_DOCUMENT_BYTES:
        raise HTTPException(404, "Document unavailable")
    return StreamingResponse(storage.stream_file(key, start=0, expected_bytes=metadata.size_bytes),
        media_type=metadata.content_type, headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
            "Content-Length": str(metadata.size_bytes), "Content-Disposition": "inline; filename=source-document",
            "Referrer-Policy": "no-referrer"})
