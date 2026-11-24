"""GC common-document directory, staging entry points and ordering."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.sync_journal import append_mobile_sync_change
from app.domain.entities.entities import User
from app.infrastructure.database.gc_mobile_models import (
    GCCommonDocumentModel,
)
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes.gc_app_common_staging import (
    _store_common_document_version,
)
from app.presentation.api.v1.routes.gc_app_content_projection import (
    _common_document_response,
)
from app.presentation.api.v1.routes.gc_app_content_scope import (
    GC_CONTENT_ROLES,
    _admin_access_context,
    _content_audit,
    _require_access_revision,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    CommonDocumentCategory,
    CommonDocumentReorderRequest,
    CommonDocumentResponse,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


@router.get(
    "/groups/{group_id}/common-documents",
    response_model=list[CommonDocumentResponse],
)
async def list_common_documents(
    group_id: uuid.UUID,
    agency_id: uuid.UUID | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 200,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[CommonDocumentResponse]:
    access, _group = await _admin_access_context(
        session, current_user, group_id, agency_id=agency_id, lock=False
    )
    items = list(
        (
            await session.execute(
                select(GCCommonDocumentModel)
                .where(
                    GCCommonDocumentModel.gc_group_access_id == access.id,
                    GCCommonDocumentModel.status.in_(("draft", "published")),
                )
                .order_by(
                    GCCommonDocumentModel.sort_order.asc(),
                    GCCommonDocumentModel.logical_document_id.asc(),
                    GCCommonDocumentModel.version.desc(),
                )
                .offset(offset)
                .limit(limit)
            )
        ).scalars()
    )
    return [_common_document_response(item) for item in items]


@router.post(
    "/groups/{group_id}/common-documents",
    response_model=CommonDocumentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_cookie_csrf)],
)
async def upload_common_document(
    group_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    category: CommonDocumentCategory = Form(...),
    display_name: str = Form(..., min_length=1, max_length=255),
    offline_available: bool = Form(default=True),
    expected_access_revision: int = Form(..., ge=1),
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> CommonDocumentResponse:
    return await _store_common_document_version(
        session,
        request=request,
        current_user=current_user,
        group_id=group_id,
        agency_id=agency_id,
        expected_access_revision=expected_access_revision,
        file=file,
        category=category,
        display_name=display_name,
        offline_available=offline_available,
    )


@router.put(
    "/groups/{group_id}/common-documents/reorder",
    response_model=list[CommonDocumentResponse],
    dependencies=[Depends(require_cookie_csrf)],
)
async def reorder_common_documents(
    group_id: uuid.UUID,
    body: CommonDocumentReorderRequest,
    request: Request,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[CommonDocumentResponse]:
    access, _group = await _admin_access_context(
        session, current_user, group_id, agency_id=agency_id, lock=True
    )
    _require_access_revision(access, body.expected_access_revision)
    unique_ids = list(dict.fromkeys(body.ordered_document_ids))
    documents = list(
        (
            await session.execute(
                select(GCCommonDocumentModel)
                .where(
                    GCCommonDocumentModel.gc_group_access_id == access.id,
                    GCCommonDocumentModel.id.in_(unique_ids),
                    GCCommonDocumentModel.status.in_(("draft", "published")),
                )
                .with_for_update()
            )
        ).scalars()
    )
    if len(documents) != len(unique_ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Document order contains unavailable items",
        )
    by_id = {item.id: item for item in documents}
    now = datetime.now(tz=UTC)
    for sort_order, document_id in enumerate(unique_ids):
        by_id[document_id].sort_order = sort_order
        by_id[document_id].updated_at = now
    access.common_document_version += 1
    access.manifest_version += 1
    access.revision += 1
    access.updated_by_user_id = current_user.id
    access.updated_at = now
    await append_mobile_sync_change(
        session,
        access=access,
        entity_type="common_document_order",
        entity_id=None,
        operation="upsert",
        version=access.common_document_version,
        changed_by_user_id=current_user.id,
        payload={"resource_path": f"/api/v1/mobile/trips/{group_id}/common-documents"},
    )
    await _content_audit(
        session,
        request,
        current_user,
        access,
        action="gc_app.common_documents_reordered",
        entity_type="gc_group_access",
        entity_id=access.id,
    )
    return [_common_document_response(by_id[item]) for item in unique_ids]


@router.post(
    "/groups/{group_id}/common-documents/{document_id}/replace",
    response_model=CommonDocumentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_cookie_csrf)],
)
async def replace_common_document(
    group_id: uuid.UUID,
    document_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    category: CommonDocumentCategory = Form(...),
    display_name: str = Form(..., min_length=1, max_length=255),
    offline_available: bool = Form(default=True),
    expected_access_revision: int = Form(..., ge=1),
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(require_role(GC_CONTENT_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> CommonDocumentResponse:
    return await _store_common_document_version(
        session,
        request=request,
        current_user=current_user,
        group_id=group_id,
        agency_id=agency_id,
        expected_access_revision=expected_access_revision,
        file=file,
        category=category,
        display_name=display_name,
        offline_available=offline_available,
        replace_document_id=document_id,
    )
