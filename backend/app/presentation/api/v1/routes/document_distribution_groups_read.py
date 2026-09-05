"""Document distribution: groups read."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import User, UserRole
from app.domain.value_objects.travel_document_taxonomy import (
    DOCUMENT_TYPES,
    DOMESTIC_ONWARD_DOCUMENT_TYPE,
    DOMESTIC_RETURN_DOCUMENT_TYPE,
    INTERNATIONAL_ONWARD_DOCUMENT_TYPE,
    INTERNATIONAL_RETURN_DOCUMENT_TYPE,
    OTHER_DOCUMENT_TYPE,
    VISA_DOCUMENT_TYPE,
    document_type_label,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    PassportSubmissionModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.export.document_assignment_excel_exporter import (
    build_document_assignment_workbook,
)
from app.infrastructure.repositories.operational_roster import operational_roster_member
from app.presentation.api.v1.routes.document_distribution_queries import _all_group_documents
from app.presentation.api.v1.routes.document_distribution_responses import _batch_response
from app.presentation.api.v1.routes.document_distribution_scope import (
    _get_authorized_group,
    _group_passengers,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    _document_assignment_export_rows,
    _safe_filename,
    _submitted_statuses,
)
from app.presentation.api.v1.schemas.document_distribution_schemas import (
    DocumentBatchResponse,
    DocumentGroupResponse,
)
from app.presentation.dependencies.auth import get_current_active_user

router = APIRouter()


@router.get("/groups", response_model=list[DocumentGroupResponse])
async def list_document_groups(
    search: Annotated[str | None, Query(max_length=160)] = None,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[DocumentGroupResponse]:
    if not current_user.agency_id or current_user.role == UserRole.AGENCY_COORDINATOR:
        return []

    stmt = select(ClientGroupModel).where(ClientGroupModel.agency_id == current_user.agency_id)
    stmt = stmt.where(ClientGroupModel.status.notin_(["archived", "deleted"]))
    stmt = AuthorizationPolicy.apply_group_visibility_scope(stmt, current_user)
    normalized_search = search.strip() if search else ""
    if normalized_search:
        passenger_group_ids = select(PassportSubmissionModel.group_id).where(
            PassportSubmissionModel.agency_id == current_user.agency_id,
            PassportSubmissionModel.status.in_(_submitted_statuses()),
            operational_roster_member(),
            PassportSubmissionModel.client_name.icontains(
                normalized_search,
                autoescape=True,
            ),
        )
        stmt = stmt.where(
            or_(
                ClientGroupModel.name.icontains(normalized_search, autoescape=True),
                ClientGroupModel.destination.icontains(
                    normalized_search,
                    autoescape=True,
                ),
                ClientGroupModel.id.in_(passenger_group_ids),
            )
        )
    stmt = stmt.order_by(ClientGroupModel.created_at.desc())
    result = await session.execute(stmt)
    groups = result.scalars().all()

    assigned_counts: dict[tuple[uuid.UUID, str], int] = {}
    if groups:
        assigned_count_result = await session.execute(
            select(
                DistributedDocumentModel.group_id,
                DistributedDocumentModel.document_type,
                func.count(func.distinct(DistributedDocumentModel.passenger_id)),
            )
            .join(
                PassportSubmissionModel,
                PassportSubmissionModel.id == DistributedDocumentModel.passenger_id,
            )
            .where(
                DistributedDocumentModel.agency_id == current_user.agency_id,
                DistributedDocumentModel.group_id.in_([group.id for group in groups]),
                DistributedDocumentModel.document_type.in_(tuple(DOCUMENT_TYPES)),
                PassportSubmissionModel.group_id == DistributedDocumentModel.group_id,
                PassportSubmissionModel.status.in_(_submitted_statuses()),
                operational_roster_member(),
            )
            .group_by(
                DistributedDocumentModel.group_id,
                DistributedDocumentModel.document_type,
            )
        )
        assigned_counts = {
            (group_id, document_type): int(count or 0)
            for group_id, document_type, count in assigned_count_result.all()
        }

    passenger_counts: dict[uuid.UUID, int] = {}
    if groups:
        passenger_count_result = await session.execute(
            select(
                PassportSubmissionModel.group_id,
                func.count(PassportSubmissionModel.id),
            )
            .where(
                PassportSubmissionModel.agency_id == current_user.agency_id,
                PassportSubmissionModel.group_id.in_([group.id for group in groups]),
                PassportSubmissionModel.status.in_(_submitted_statuses()),
                operational_roster_member(),
            )
            .group_by(PassportSubmissionModel.group_id)
        )
        passenger_counts = {
            group_id: int(count or 0) for group_id, count in passenger_count_result.all()
        }

    responses: list[DocumentGroupResponse] = []
    for group in groups:
        responses.append(
            DocumentGroupResponse(
                group_id=group.id,
                group_name=group.name,
                group_status=group.status,
                destination=group.destination,
                travel_date=group.travel_date.isoformat() if group.travel_date else None,
                total_passengers=passenger_counts.get(group.id, 0),
                visa_assigned_count=assigned_counts.get((group.id, VISA_DOCUMENT_TYPE), 0),
                flight_ticket_assigned_count=assigned_counts.get(
                    (group.id, INTERNATIONAL_ONWARD_DOCUMENT_TYPE),
                    0,
                ),
                flight_ticket_arrival_assigned_count=assigned_counts.get(
                    (group.id, INTERNATIONAL_RETURN_DOCUMENT_TYPE),
                    0,
                ),
                flight_ticket_domestic_assigned_count=assigned_counts.get(
                    (group.id, DOMESTIC_ONWARD_DOCUMENT_TYPE),
                    0,
                ),
                flight_ticket_domestic_arrival_assigned_count=assigned_counts.get(
                    (group.id, DOMESTIC_RETURN_DOCUMENT_TYPE),
                    0,
                ),
                other_assigned_count=assigned_counts.get((group.id, OTHER_DOCUMENT_TYPE), 0),
            )
        )
    return responses


async def _load_document_review(
    group_id: uuid.UUID,
    document_type: str,
    *,
    current_user: User,
    session: AsyncSession,
) -> tuple[ClientGroupModel, DocumentBatchResponse]:
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported document type"
        )
    group = await _get_authorized_group(
        group_id,
        current_user=current_user,
        session=session,
    )
    passengers = await _group_passengers(group_id, current_user=current_user, session=session)
    result = await session.execute(
        select(DocumentDistributionBatchModel)
        .where(
            DocumentDistributionBatchModel.group_id == group_id,
            DocumentDistributionBatchModel.agency_id == group.agency_id,
            DocumentDistributionBatchModel.document_type == document_type,
        )
        .order_by(DocumentDistributionBatchModel.created_at.desc())
        .limit(1)
    )
    batch = result.scalar_one_or_none()
    documents = await _all_group_documents(
        session,
        group_id=group_id,
        agency_id=group.agency_id,
        document_type=document_type,
    )
    return (
        group,
        await _batch_response(
            session=session,
            group_id=group_id,
            agency_id=group.agency_id,
            document_type=document_type,
            passengers=passengers,
            batch=batch,
            documents=documents,
        ),
    )


@router.get("/groups/{group_id}/{document_type}", response_model=DocumentBatchResponse)
async def get_document_review(
    group_id: uuid.UUID,
    document_type: str,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> DocumentBatchResponse:
    _, review = await _load_document_review(
        group_id,
        document_type,
        current_user=current_user,
        session=session,
    )
    return review


@router.get("/groups/{group_id}/{document_type}/export.xlsx")
async def export_document_assignments(
    group_id: uuid.UUID,
    document_type: str,
    review_filter: Annotated[
        Literal["all", "assigned", "missing", "sent", "not_sent"],
        Query(alias="filter"),
    ] = "all",
    search: Annotated[str, Query(max_length=200)] = "",
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    group, review = await _load_document_review(
        group_id,
        document_type,
        current_user=current_user,
        session=session,
    )
    filter_labels = {
        "all": "All",
        "assigned": "Assigned",
        "missing": "Missing",
        "sent": "Sent",
        "not_sent": "Not sent",
    }
    rows = _document_assignment_export_rows(
        review.review_rows,
        review_filter=review_filter,
        search_query=search,
    )
    workbook = build_document_assignment_workbook(
        group_name=group.name,
        document_label=document_type_label(document_type),
        filter_label=filter_labels[review_filter],
        search_query=search,
        rows=rows,
    )
    filename = (
        _safe_filename(f"{group.name}-{document_type}-{review_filter}-document-assignments")
        + ".xlsx"
    )
    return StreamingResponse(
        workbook,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
