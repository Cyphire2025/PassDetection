"""Private, tenant-scoped company logos and group banners with crash-safe writes."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.access import (
    COMPANY_LOOKUP_ROLES,
    company_agency_scope,
    require_company,
)
from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import (
    AuthorizationError,
    ConflictError,
    EntityNotFoundError,
    StorageError,
)
from app.infrastructure.database.gc_mobile_models import ClientOrganizationModel
from app.infrastructure.database.models import ClientGroupModel, StorageCleanupJobModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.documents.storage_cleanup import stage_storage_cleanup_job
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.security.upload_security import (
    UploadSecurityContext,
    UploadSecurityEvidenceError,
    UploadSecurityService,
)
from app.infrastructure.security.upload_validator import MalwareScannerUnavailableError
from app.infrastructure.storage.branding_urls import BrandingKind, branding_image_url, image_version
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()
MAX_IMAGE_BYTES = 8 * 1024 * 1024
ImageOwner = ClientOrganizationModel | ClientGroupModel


class BrandingImageResponse(BaseModel):
    url: str | None
    revision: int | None = None


def _key(owner: ImageOwner) -> str | None:
    return owner.logo_image_key if isinstance(owner, ClientOrganizationModel) else owner.banner_image_key


async def _owner(session: AsyncSession, user: User, kind: BrandingKind, owner_id: uuid.UUID,
                 agency_id: uuid.UUID | None, *, manage: bool = False, lock: bool = False) -> ImageOwner:
    if kind == "company-logo":
        if manage:
            return await require_company(session, user=user, company_id=owner_id, agency_id=agency_id, lock=lock)
        if user.role not in COMPANY_LOOKUP_ROLES:
            raise AuthorizationError()
        query = select(ClientOrganizationModel).where(
            ClientOrganizationModel.id == owner_id,
            ClientOrganizationModel.agency_id == company_agency_scope(user, agency_id),
            ClientOrganizationModel.status != "deleted",
        )
        company = await session.scalar(query)
        if company is None:
            raise EntityNotFoundError("Company", str(owner_id))
        return company
    query_group = select(ClientGroupModel).where(ClientGroupModel.id == owner_id, ClientGroupModel.status != "deleted")
    if lock:
        query_group = query_group.with_for_update().execution_options(populate_existing=True)
    group = await session.scalar(query_group)
    if group is None:
        raise EntityNotFoundError("Group", str(owner_id))
    if agency_id is not None and group.agency_id != agency_id:
        raise AuthorizationError("Agency scope mismatch")
    policy = AuthorizationPolicy(session)
    if manage:
        await policy.require_manage_group(user, group)
    else:
        await policy.require_view_group(user, group)
    return group


def _check_version(owner: ImageOwner, expected: str) -> None:
    if image_version(_key(owner)) != expected:
        raise ConflictError("This image changed. Refresh the company or group and try again.")


async def _publish(session: AsyncSession, user: User, owner: ImageOwner, kind: BrandingKind,
                   new_key: str | None) -> BrandingImageResponse:
    old_key = _key(owner)
    if isinstance(owner, ClientOrganizationModel):
        owner.logo_image_key = new_key
        owner.revision += 1
        owner.updated_by_user_id = user.id
        owner.updated_at = datetime.now(UTC)
    else:
        owner.banner_image_key = new_key
    stage_storage_cleanup_job(session, agency_id=owner.agency_id, source="branding_image",
        context_id=str(owner.id), storage_keys=[old_key] if old_key else [])
    await AuditLogRepository(session).record(action="branding.image_removed" if new_key is None else "branding.image_updated",
        entity_type=kind, entity_id=str(owner.id), agency_id=owner.agency_id,
        user_id=user.id, actor_email=user.email, metadata={"kind": kind})
    await session.flush()
    return BrandingImageResponse(url=branding_image_url(kind, owner.id, owner.agency_id, new_key),
        revision=owner.revision if isinstance(owner, ClientOrganizationModel) else None)


@router.get("/{kind}/{owner_id}", response_class=Response,
            responses={200: {"content": {"image/jpeg": {}}, "description": "Company logo or group banner"}})
async def read_image(kind: BrandingKind, owner_id: uuid.UUID, agency_id: uuid.UUID | None = None,
                     v: str = Query(default="", max_length=36),
                     user: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_db_session)) -> Response:
    owner = await _owner(session, user, kind, owner_id, agency_id)
    key = _key(owner)
    if not key or (v and v != image_version(key)):
        raise HTTPException(404, "Image not found")
    await session.commit()
    content = await MinioStorageRepository().get_file(key)
    return Response(content=content, media_type="image/jpeg", headers={
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
        "Content-Disposition": 'inline; filename="workspace-image.jpg"',
    })


@router.put("/{kind}/{owner_id}", response_model=BrandingImageResponse, dependencies=[Depends(require_cookie_csrf)])
async def upload_image(kind: BrandingKind, owner_id: uuid.UUID, file: UploadFile = File(),
                       expected_version: str = Form(default="", max_length=36), agency_id: uuid.UUID | None = None,
                       user: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_db_session)) -> BrandingImageResponse:
    owner = await _owner(session, user, kind, owner_id, agency_id, manage=True)
    _check_version(owner, expected_version)
    # Release the authorization read connection before scanning. The owner and
    # image version are checked again under a row lock before attachment.
    await session.commit()
    content = await file.read(MAX_IMAGE_BYTES + 1)
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "Choose a JPG, PNG or WebP image up to 8 MB.")
    try:
        async with asyncio.timeout(45):
            validated = await UploadSecurityService().validate_image(content=content, filename=file.filename,
                declared_content_type=file.content_type, max_bytes=MAX_IMAGE_BYTES,
                max_dimension=1024 if kind == "company-logo" else 2560,
                allowed_source_formats=frozenset({"JPEG", "PNG", "WEBP"}),
                context=UploadSecurityContext("workspace_branding", agency_id=owner.agency_id, user_id=user.id))
    except (MalwareScannerUnavailableError, UploadSecurityEvidenceError, TimeoutError) as exc:
        raise HTTPException(503, "Image upload is temporarily unavailable. Please try again.", headers={"Retry-After": "30"}) from exc
    key = f"branding/{owner.agency_id}/{kind}/{owner.id}/{uuid.uuid4()}.jpg"
    # A committed delayed tombstone owns the object before I/O. A crash or a
    # failed attachment leaves it eligible for the existing cleanup worker.
    job = stage_storage_cleanup_job(session, agency_id=owner.agency_id, source="branding_image",
        context_id=str(owner.id), storage_keys=[key], not_before=datetime.now(UTC) + timedelta(hours=1))
    assert job is not None
    job_id = job.id
    await session.commit()
    try:
        async with asyncio.timeout(45):
            await MinioStorageRepository().upload_file(validated.content, key, validated.content_type)
    except (StorageError, TimeoutError) as exc:
        raise HTTPException(503, "Image storage is temporarily unavailable. Please try again.", headers={"Retry-After": "30"}) from exc
    owner = await _owner(session, user, kind, owner_id, agency_id, manage=True, lock=True)
    _check_version(owner, expected_version)
    result = await _publish(session, user, owner, kind, key)
    await session.execute(delete(StorageCleanupJobModel).where(StorageCleanupJobModel.id == job_id))
    await session.commit()
    return result


@router.delete("/{kind}/{owner_id}", response_model=BrandingImageResponse, dependencies=[Depends(require_cookie_csrf)])
async def remove_image(kind: BrandingKind, owner_id: uuid.UUID, agency_id: uuid.UUID | None = None,
                       expected_version: str = Query(default="", max_length=36),
                       user: User = Depends(get_current_active_user), session: AsyncSession = Depends(get_db_session)) -> BrandingImageResponse:
    owner = await _owner(session, user, kind, owner_id, agency_id, manage=True, lock=True)
    _check_version(owner, expected_version)
    return await _publish(session, user, owner, kind, None)
