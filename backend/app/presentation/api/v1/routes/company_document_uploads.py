"""Bounded scanned staff image upload into a durable immutable version receipt."""

import asyncio
import hashlib
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.access import COMPANY_ADMIN_ROLES, require_company
from app.application.companies.document_publication import publish_document_upload
from app.application.companies.document_upload import prepare_document_upload
from app.application.companies.people import current_person, require_person
from app.application.companies.people_contracts import CurrentPerson, DocumentUpload
from app.application.travellers.asset_policy import MAX_PRIVATE_DOCUMENT_BYTES
from app.domain.entities.entities import User
from app.infrastructure.database.session import get_db_session
from app.infrastructure.security.traveller_reuse_crypto import TravellerReuseCrypto
from app.infrastructure.security.upload_security import UploadSecurityContext, UploadSecurityService
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.routes.company_people import crypto_dependency, private_response
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter(dependencies=[Depends(private_response), Depends(require_cookie_csrf)])


@router.post("/{company_id}/people/{person_id}/documents", response_model=CurrentPerson, status_code=201)
async def upload_document_version(company_id: uuid.UUID, person_id: uuid.UUID,
    metadata: str = Form(max_length=4096), file: UploadFile = File(), agency_id: uuid.UUID | None = None,
    user: User = Depends(require_role(list(COMPANY_ADMIN_ROLES))), session: AsyncSession = Depends(get_db_session),
    crypto: TravellerReuseCrypto = Depends(crypto_dependency),
) -> CurrentPerson:
    try:
        body = DocumentUpload.model_validate_json(metadata)
    except PydanticValidationError as exc:
        raise HTTPException(422, "Document metadata is invalid.") from exc
    company = await require_company(session, user=user, agency_id=agency_id, company_id=company_id)
    await require_person(session, user=user, agency_id=company.agency_id, company_id=company.id, person_id=person_id)
    await session.commit()
    # Existing malware and native decoder admission remain authoritative.
    content = await file.read(MAX_PRIVATE_DOCUMENT_BYTES + 1)
    if not content or len(content) > MAX_PRIVATE_DOCUMENT_BYTES:
        raise HTTPException(413, "Upload an image of at most 20 MiB.")
    async with asyncio.timeout(45):
        validated = await UploadSecurityService().validate_image(content=content, filename=file.filename,
            declared_content_type=file.content_type, max_bytes=MAX_PRIVATE_DOCUMENT_BYTES,
            allowed_source_formats=frozenset({"JPEG", "PNG", "WEBP"}),
            context=UploadSecurityContext("company_current_document", agency_id=company.agency_id, user_id=user.id))
    checksum = hashlib.sha256(validated.content).hexdigest()
    company = await require_company(session, user=user, agency_id=agency_id, company_id=company_id)
    person = await require_person(session, user=user, agency_id=company.agency_id,
        company_id=company.id, person_id=person_id, lock=True)
    target = await prepare_document_upload(session, person=person, actor_id=user.id, body=body,
        checksum=checksum, size=len(validated.content), media=validated.content_type, crypto=crypto)
    # The object owner/receipt commits first. A lost upload response can retry
    # this same request without creating another revision or an orphan object.
    await session.commit()
    if not target.already_available:
        async with asyncio.timeout(45):
            await MinioStorageRepository().upload_file(validated.content, target.key, validated.content_type)
        company = await require_company(session, user=user, agency_id=agency_id, company_id=company_id)
        person = await require_person(session, user=user, agency_id=company.agency_id,
            company_id=company.id, person_id=person_id, lock=True)
        await publish_document_upload(session, person=person, asset_id=target.asset_id, actor_id=user.id, crypto=crypto)
    person = await require_person(session, user=user, agency_id=company.agency_id,
        company_id=company.id, person_id=person_id)
    return await current_person(session, person, crypto)
