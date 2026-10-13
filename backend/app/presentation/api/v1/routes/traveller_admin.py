"""Explicit company-admin enrollment, matching preview and reuse withdrawal."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.access import (
    COMPANY_ADMIN_ROLES,
    require_company,
    visible_company_groups,
)
from app.application.travellers.enrollment import (
    EnrollmentError,
    EnrollmentRequest,
    enroll_submission,
)
from app.application.travellers.reconciliation import enqueue_reconciliation
from app.application.travellers.retention import revoke_retained_profile
from app.core.config.traveller_reuse import get_traveller_reuse_settings
from app.domain.entities.entities import User
from app.infrastructure.database.gc_mobile_models import ClientOrganizationModel
from app.infrastructure.database.models import ClientGroupModel, PassportSubmissionModel
from app.infrastructure.database.search_expressions import (
    passport_search_fields,
    substring_predicate,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.database.traveller_reuse_models import (
    TravellerMatchCaseModel,
    TravellerProfileModel,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.security.traveller_reuse_crypto import (
    ReuseCryptoUnavailable,
    TravellerReuseCrypto,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "private, no-store"


router = APIRouter(dependencies=[Depends(_no_store), Depends(require_cookie_csrf)])


class EnrollmentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_submission_id: uuid.UUID
    expected_extraction_revision: int = Field(ge=0)
    expected_group_revision: int = Field(ge=1)
    permission_evidence_reference: str = Field(min_length=3, max_length=500)
    idempotency_key: str = Field(min_length=1, max_length=128)
    traveller_id: uuid.UUID | None = None
    expected_profile_revision: int | None = Field(default=None, ge=1)
    change_kind: Literal["initial", "renewal", "scan", "correction"] = "initial"
    reviewed_issuing_country: str | None = Field(default=None, min_length=3, max_length=3)
    reviewed_document_type: str | None = Field(default=None, min_length=1, max_length=16)
    reviewed_context_confirmed: bool = False
    candidate_association_confirmed: bool = False


class EnrollmentResponse(BaseModel):
    traveller_id: uuid.UUID
    passport_id: uuid.UUID
    document_revision_id: uuid.UUID
    copies_pending: int


class EnrollmentSourceItem(BaseModel):
    id: uuid.UUID
    display_name: str
    status: str
    extraction_revision: int
    candidate_traveller_id: uuid.UUID | None = None
    candidate_display_name: str | None = None
    candidate_profile_revision: int | None = None
    candidate_change_kind: Literal["renewal", "scan", "correction"] | None = None


class EnrollmentSourcePage(BaseModel):
    items: list[EnrollmentSourceItem]
    next_cursor: str | None
    expected_group_revision: int


class MatchPreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=128)


class MatchPreviewResponse(BaseModel):
    job_id: uuid.UUID
    status: str


class WithdrawalBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)


async def _require_visible_group(session: AsyncSession, user: User, company: ClientOrganizationModel, group_id: uuid.UUID) -> None:
    visible = visible_company_groups(user, company.agency_id, company.id).with_only_columns(ClientGroupModel.id)
    if await session.scalar(visible.where(ClientGroupModel.id == group_id)) is None:
        raise HTTPException(404, "Group unavailable")


@router.get("/{company_id}/groups/{group_id}/travellers/enrollment-sources", response_model=EnrollmentSourcePage)
async def list_enrollment_sources(
    company_id: uuid.UUID, group_id: uuid.UUID, agency_id: uuid.UUID | None = None,
    search: str = Query(default="", max_length=120), cursor: uuid.UUID | None = None,
    page_size: int = Query(default=25, ge=1, le=50),
    user: User = Depends(require_role(list(COMPANY_ADMIN_ROLES))), session: AsyncSession = Depends(get_db_session),
) -> EnrollmentSourcePage:
    """Selective keyset page; no count, source fields or document URLs loaded."""
    company = await require_company(session, user=user, company_id=company_id, agency_id=agency_id)
    group_revision = await session.scalar(visible_company_groups(user, company.agency_id, company.id)
        .where(ClientGroupModel.id == group_id).with_only_columns(ClientGroupModel.company_revision))
    if group_revision is None:
        raise HTTPException(404, "Group unavailable")
    query = select(PassportSubmissionModel.id, PassportSubmissionModel.client_name,
        PassportSubmissionModel.status, PassportSubmissionModel.extraction_revision).where(
        PassportSubmissionModel.agency_id == company.agency_id,
        PassportSubmissionModel.group_id == group_id,
        PassportSubmissionModel.status.in_(("staff_approved", "confirmed")),
    )
    term = search.strip().casefold()
    if term:
        if len(term) < 3:
            raise HTTPException(422, "Enter at least three search characters.")
        query = query.where(substring_predicate(term, fields=(PassportSubmissionModel.client_name,),
            indexed_fields=passport_search_fields()))
    if cursor is not None:
        query = query.where(PassportSubmissionModel.id > cursor)
    rows = (await session.execute(query.order_by(PassportSubmissionModel.id).limit(page_size + 1))).all()
    visible = rows[:page_size]
    candidates = (await session.execute(select(TravellerMatchCaseModel, TravellerProfileModel.display_name_ciphertext,
        TravellerProfileModel.revision).join(TravellerProfileModel,
            (TravellerProfileModel.id == TravellerMatchCaseModel.traveller_id)
            & (TravellerProfileModel.company_id == TravellerMatchCaseModel.company_id)
            & (TravellerProfileModel.agency_id == TravellerMatchCaseModel.agency_id)).where(
        TravellerMatchCaseModel.agency_id == company.agency_id, TravellerMatchCaseModel.company_id == company.id,
        TravellerMatchCaseModel.group_id == group_id, TravellerMatchCaseModel.source_kind == "passport_submission",
        TravellerMatchCaseModel.source_row_key.in_([str(row.id) for row in visible]),
        TravellerMatchCaseModel.reason_code == "authorized_replacement_candidate",
        TravellerMatchCaseModel.status == "provisional", TravellerProfileModel.status == "active",
        TravellerProfileModel.deleted_at.is_(None)).limit(page_size))).all() if visible else []
    by_source = {case.source_row_key: (case, name, revision) for case, name, revision in candidates}
    try:
        crypto = TravellerReuseCrypto(get_traveller_reuse_settings()) if candidates else None
    except ReuseCryptoUnavailable as exc:
        raise HTTPException(503, "Retained traveller review is unavailable.") from exc
    items = []
    for row in visible:
        item = EnrollmentSourceItem(id=row.id, display_name=row.client_name,
            status=row.status, extraction_revision=row.extraction_revision)
        candidate = by_source.get(str(row.id))
        if candidate is not None:
            case, name, current_revision = candidate
            if (case.evidence.get("profile_revision") == current_revision
                    and case.evidence.get("group_revision") == group_revision):
                item.candidate_traveller_id = case.traveller_id
                item.candidate_profile_revision = current_revision
                item.candidate_change_kind = case.evidence.get("change_kind")
                try:
                    item.candidate_display_name = crypto.decrypt(name) if crypto and name else None
                except ReuseCryptoUnavailable as exc:
                    raise HTTPException(503, "Retained traveller review is unavailable.") from exc
        items.append(item)
    return EnrollmentSourcePage(items=items,
        next_cursor=str(visible[-1].id) if len(rows) > page_size else None,
        expected_group_revision=group_revision)


@router.post("/{company_id}/groups/{group_id}/travellers/enroll", response_model=EnrollmentResponse, status_code=202)
async def enroll_retained_submission(
    company_id: uuid.UUID, group_id: uuid.UUID, body: EnrollmentBody, agency_id: uuid.UUID | None = None,
    user: User = Depends(require_role(list(COMPANY_ADMIN_ROLES))), session: AsyncSession = Depends(get_db_session),
) -> EnrollmentResponse:
    company = await require_company(session, user=user, company_id=company_id, agency_id=agency_id)
    await _require_visible_group(session, user, company, group_id)
    try:
        crypto = TravellerReuseCrypto(get_traveller_reuse_settings())
        result = await enroll_submission(session, EnrollmentRequest(
            agency_id=company.agency_id, company_id=company.id, group_id=group_id,
            submission_id=body.source_submission_id, actor_id=user.id,
            expected_group_revision=body.expected_group_revision,
            expected_extraction_revision=body.expected_extraction_revision,
            permission_evidence_reference=body.permission_evidence_reference,
            idempotency_key=body.idempotency_key, traveller_id=body.traveller_id,
            expected_profile_revision=body.expected_profile_revision, change_kind=body.change_kind,
            reviewed_issuing_country=body.reviewed_issuing_country,
            reviewed_document_type=body.reviewed_document_type,
            reviewed_context_confirmed=body.reviewed_context_confirmed,
            candidate_association_confirmed=body.candidate_association_confirmed,
        ), crypto)
    except EnrollmentError as exc:
        raise HTTPException(409, {"code": str(exc), "message": "Review the saved evidence or refresh the record before retrying."}) from exc
    except ReuseCryptoUnavailable as exc:
        raise HTTPException(503, "Retained document processing is not configured.") from exc
    await AuditLogRepository(session).record(action="traveller.document_enrolled", entity_type="traveller_profile",
        entity_id=str(result.traveller_id), agency_id=company.agency_id, user_id=user.id,
        metadata={"revision_id": str(result.document_revision_id), "change_kind": body.change_kind})
    return EnrollmentResponse(traveller_id=result.traveller_id, passport_id=result.passport_id,
        document_revision_id=result.document_revision_id, copies_pending=result.copies_pending)


@router.post("/{company_id}/groups/{group_id}/travellers/matching-preview", response_model=MatchPreviewResponse, status_code=202)
async def create_matching_preview(
    company_id: uuid.UUID, group_id: uuid.UUID, body: MatchPreviewBody, agency_id: uuid.UUID | None = None,
    user: User = Depends(require_role(list(COMPANY_ADMIN_ROLES))), session: AsyncSession = Depends(get_db_session),
) -> MatchPreviewResponse:
    company = await require_company(session, user=user, company_id=company_id, agency_id=agency_id)
    await _require_visible_group(session, user, company, group_id)
    job = await enqueue_reconciliation(session, agency_id=company.agency_id, company_id=company.id,
        group_id=group_id, idempotency_key=body.idempotency_key)
    await AuditLogRepository(session).record(action="traveller.matching_preview_requested", entity_type="client_group",
        entity_id=str(group_id), agency_id=company.agency_id, user_id=user.id, metadata={"job_id": str(job.id)})
    return MatchPreviewResponse(job_id=job.id, status=job.status)


@router.post("/{company_id}/travellers/{traveller_id}/withdraw-reuse", status_code=202)
async def withdraw_traveller_reuse(
    company_id: uuid.UUID, traveller_id: uuid.UUID, body: WithdrawalBody, agency_id: uuid.UUID | None = None,
    user: User = Depends(require_role(list(COMPANY_ADMIN_ROLES))), session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    company = await require_company(session, user=user, company_id=company_id, agency_id=agency_id)
    if not await revoke_retained_profile(session, agency_id=company.agency_id, company_id=company.id,
        traveller_id=traveller_id, expected_revision=body.expected_revision):
        raise HTTPException(409, "Traveller revision changed or the record is unavailable.")
    await AuditLogRepository(session).record(action="traveller.reuse_withdrawn", entity_type="traveller_profile",
        entity_id=str(traveller_id), agency_id=company.agency_id, user_id=user.id,
        metadata={"previous_revision": body.expected_revision})
    return {"status": "revoked", "document_deletion": "queued"}
