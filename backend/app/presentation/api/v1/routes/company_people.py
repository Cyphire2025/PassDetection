"""Staff All data: tenant-bound cursors and lazy private retained evidence."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.access import COMPANY_ADMIN_ROLES, require_company
from app.application.companies.current_record import edit_current_record
from app.application.companies.directory_query import (
    DirectoryIndexChanged,
    DirectorySort,
    SubmissionFilter,
    company_directory_page,
)
from app.application.companies.people import (
    current_person,
    document_items,
    require_person,
)
from app.application.companies.people_contracts import (
    CurrentPerson,
    DocumentPage,
    PersonEdit,
    PersonPage,
)
from app.application.mcp.read_cursor import MCPReadCursor
from app.application.travellers.asset_policy import is_reviewable_asset
from app.application.travellers.history_schedule import schedule_company_history_initialization
from app.application.travellers.snapshot_access import retained_asset_authority
from app.core.config.settings import Settings, get_settings
from app.core.config.traveller_reuse import get_traveller_reuse_settings
from app.domain.entities.entities import User
from app.infrastructure.database.session import get_db_session
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentAssetModel as Asset,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentRevisionModel as Document,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerProfileModel as Person,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.security.traveller_reuse_crypto import (
    ReuseCryptoUnavailable,
    TravellerReuseCrypto,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.routes.company_source_documents import router as source_router
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf


def private_response(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


def crypto_dependency() -> TravellerReuseCrypto:
    try:
        return TravellerReuseCrypto(get_traveller_reuse_settings())
    except ReuseCryptoUnavailable as exc:
        raise HTTPException(503, "Retained traveller data is temporarily unavailable.") from exc


router = APIRouter(dependencies=[Depends(private_response), Depends(require_cookie_csrf)])
router.include_router(source_router)


@router.get("/{company_id}/people", response_model=PersonPage)
async def people_page(company_id: uuid.UUID, agency_id: uuid.UUID | None = None,
    search: str = Query(default="", max_length=120), cursor: str | None = Query(default=None, max_length=2048),
    page_size: int = Query(default=100, ge=1, le=100),
    sort: DirectorySort = Query(default="name_asc"), submissions: SubmissionFilter = Query(default="all"),
    user: User = Depends(require_role(list(COMPANY_ADMIN_ROLES))), session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings), crypto: TravellerReuseCrypto = Depends(crypto_dependency),
) -> PersonPage:
    company = await require_company(session, user=user, company_id=company_id, agency_id=agency_id)
    await schedule_company_history_initialization(session, company=company)
    try:
        return await company_directory_page(session, user=user, agency_id=company.agency_id,
            company_id=company.id, crypto=crypto, secret=settings.app_secret_key, search=search,
            sort=sort, submissions=submissions, cursor=cursor, page_size=page_size)
    except DirectoryIndexChanged as exc:
        raise HTTPException(409, {"code": "DIRECTORY_CHANGED", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/{company_id}/people/{person_id}/record", response_model=CurrentPerson)
async def person_record(company_id: uuid.UUID, person_id: uuid.UUID, agency_id: uuid.UUID | None = None,
    user: User = Depends(require_role(list(COMPANY_ADMIN_ROLES))), session: AsyncSession = Depends(get_db_session),
    crypto: TravellerReuseCrypto = Depends(crypto_dependency),
) -> CurrentPerson:
    company = await require_company(session, user=user, company_id=company_id, agency_id=agency_id)
    person = await require_person(session, user=user, agency_id=company.agency_id, company_id=company.id, person_id=person_id)
    await AuditLogRepository(session).record(action="traveller.staff_record_viewed", entity_type="traveller_profile",
        entity_id=str(person_id), agency_id=company.agency_id, user_id=user.id, metadata={"revision": person.revision})
    return await current_person(session, person, crypto, user=user)


@router.patch("/{company_id}/people/{person_id}/record", response_model=CurrentPerson)
async def update_person_record(company_id: uuid.UUID, person_id: uuid.UUID, body: PersonEdit,
    agency_id: uuid.UUID | None = None, user: User = Depends(require_role(list(COMPANY_ADMIN_ROLES))),
    session: AsyncSession = Depends(get_db_session), crypto: TravellerReuseCrypto = Depends(crypto_dependency),
) -> CurrentPerson:
    company = await require_company(session, user=user, company_id=company_id, agency_id=agency_id)
    person = await require_person(session, user=user, agency_id=company.agency_id, company_id=company.id,
        person_id=person_id, lock=True)
    await edit_current_record(session, person=person, body=body, actor_id=user.id, crypto=crypto)
    return await current_person(session, person, crypto, user=user)


@router.get("/{company_id}/people/{person_id}/documents", response_model=DocumentPage)
async def person_documents(company_id: uuid.UUID, person_id: uuid.UUID, agency_id: uuid.UUID | None = None,
    cursor: str | None = Query(default=None, max_length=2048), page_size: int = Query(default=20, ge=1, le=50),
    user: User = Depends(require_role(list(COMPANY_ADMIN_ROLES))), session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings), crypto: TravellerReuseCrypto = Depends(crypto_dependency),
) -> DocumentPage:
    company = await require_company(session, user=user, company_id=company_id, agency_id=agency_id)
    person = await require_person(session, user=user, agency_id=company.agency_id, company_id=company.id, person_id=person_id)
    codec = MCPReadCursor(settings.app_secret_key, "company-person-documents-v1")
    try:
        state = codec.read(cursor, {"actor": str(user.id), "agency": str(company.agency_id),
            "company": str(company.id), "person": str(person_id)})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    query = select(Document).where(Document.agency_id == company.agency_id, Document.company_id == company.id,
        Document.traveller_id == person.id, Document.created_at <= datetime.fromisoformat(state["cutoff"]))
    if after := codec.after(state):
        query = query.where((Document.created_at < after[0]) | ((Document.created_at == after[0]) & (Document.id < after[1])))
    rows = list((await session.scalars(query.order_by(Document.created_at.desc(), Document.id.desc()).limit(page_size + 1))).all())
    more, rows = len(rows) > page_size, rows[:page_size]
    return DocumentPage(items=await document_items(session, rows, person, crypto), has_more=more,
        next_cursor=codec.next(state, {"id": rows[-1].id, "created_at": rows[-1].created_at}) if more else None)


@router.get("/{company_id}/people/{person_id}/assets/{asset_id}")
async def person_document_asset(company_id: uuid.UUID, person_id: uuid.UUID, asset_id: uuid.UUID,
    agency_id: uuid.UUID | None = None, user: User = Depends(require_role(list(COMPANY_ADMIN_ROLES))),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    company = await require_company(session, user=user, company_id=company_id, agency_id=agency_id)
    await require_person(session, user=user, agency_id=company.agency_id, company_id=company.id, person_id=person_id)
    asset = await session.scalar(select(Asset).join(Person, (Person.id == Asset.traveller_id)
        & (Person.agency_id == Asset.agency_id) & (Person.company_id == Asset.company_id)).where(
        Asset.id == asset_id, Asset.agency_id == company.agency_id,
        Asset.company_id == company.id, Asset.traveller_id == person_id, retained_asset_authority()))
    if asset is None or not is_reviewable_asset(asset, datetime.now(UTC)) or asset.object_key is None:
        raise HTTPException(404, "Document unavailable")
    await AuditLogRepository(session).record(action="traveller.staff_document_viewed", entity_type="traveller_profile",
        entity_id=str(person_id), agency_id=company.agency_id, user_id=user.id, metadata={"asset_id": str(asset.id)})
    key, size, content_type = asset.object_key, asset.byte_size, asset.content_type
    await session.commit()
    return StreamingResponse(MinioStorageRepository().stream_file(key, start=0, expected_bytes=size),
        media_type=content_type, headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
            "Content-Length": str(size), "Content-Disposition": "inline; filename=retained-document", "Referrer-Policy": "no-referrer"})
