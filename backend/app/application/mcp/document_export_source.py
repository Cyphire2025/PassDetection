"""Bound and freeze only the group document-review data used by the workbook."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.artifacts import ArtifactError
from app.domain.entities.entities import PassportSubmission, User
from app.infrastructure.database.models import (
    ClientGroupModel,
    DistributedDocumentModel,
    DocumentWhatsAppDeliveryModel,
    PassportSubmissionModel,
)
from app.infrastructure.documents.distribution_capacity import (
    MAX_DISTRIBUTION_ASSIGNMENT_ROWS_PER_SCOPE,
)

MAX_DOCUMENT_PASSENGERS = 1500
MAX_DOCUMENT_ASSIGNMENTS = MAX_DISTRIBUTION_ASSIGNMENT_ROWS_PER_SCOPE
MAX_DOCUMENT_DELIVERIES = 6000


@dataclass(frozen=True)
class DocumentExcelSupport:
    passengers: Callable[..., Any]
    document_response: Callable[..., Any]
    review_rows: Callable[..., Any]
    export_rows: Callable[..., Any]
    filename: Callable[..., Any]


@dataclass(frozen=True)
class DocumentExportSource:
    passengers: list[PassportSubmission]
    documents: list[DistributedDocumentModel]
    deliveries: list[Any]
    snapshot: dict[str, Any]


def _values(row: Any) -> dict[str, Any]:
    return {column.key: getattr(row, column.key) for column in row.__table__.columns}


async def lock_document_export_source(
    session: AsyncSession,
    *,
    support: DocumentExcelSupport,
    actor: User,
    group: ClientGroupModel,
    document_type: str,
) -> DocumentExportSource:
    # The caller holds group UPDATE, fencing new children through their FKs.
    # NOWAIT avoids cycles with older document/delivery-first writers.
    passports = list(
        (
            await session.scalars(
                select(PassportSubmissionModel)
                .where(
                    PassportSubmissionModel.group_id == group.id,
                    PassportSubmissionModel.agency_id == group.agency_id,
                )
                .order_by(PassportSubmissionModel.id)
                .limit(MAX_DOCUMENT_PASSENGERS + 1)
                .with_for_update(read=True, nowait=True)
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    if len(passports) > MAX_DOCUMENT_PASSENGERS:
        raise ArtifactError("Document export exceeds its passenger-source limit", 413)
    documents = list(
        (
            await session.scalars(
                select(DistributedDocumentModel)
                .where(
                    DistributedDocumentModel.group_id == group.id,
                    DistributedDocumentModel.agency_id == group.agency_id,
                    DistributedDocumentModel.document_type == document_type,
                )
                .order_by(DistributedDocumentModel.id)
                .limit(MAX_DOCUMENT_ASSIGNMENTS + 1)
                .with_for_update(nowait=True)
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    if len(documents) > MAX_DOCUMENT_ASSIGNMENTS:
        raise ArtifactError("Document export exceeds its assignment limit", 413)
    identifiers = {row.id for row in passports}
    if any(
        row.passenger_id is not None and row.passenger_id not in identifiers for row in documents
    ):
        raise ArtifactError("Document assignment is outside the current group", 409)
    # The canonical review sorts by newest creation then ID, independently of
    # our deterministic row-lock order. Storage identity affects PDF counts.
    documents.sort(key=lambda row: (row.created_at, row.id), reverse=True)
    fields = (
        DocumentWhatsAppDeliveryModel.id,
        DocumentWhatsAppDeliveryModel.distributed_document_id,
        DocumentWhatsAppDeliveryModel.status,
        DocumentWhatsAppDeliveryModel.status_updated_at,
        DocumentWhatsAppDeliveryModel.created_at,
        DocumentWhatsAppDeliveryModel.phone_number,
    )
    result = await session.execute(
        select(*fields)
        .where(
            DocumentWhatsAppDeliveryModel.group_id == group.id,
            DocumentWhatsAppDeliveryModel.agency_id == group.agency_id,
            DocumentWhatsAppDeliveryModel.distributed_document_id.in_(
                [row.id for row in documents]
            ),
        )
        .order_by(DocumentWhatsAppDeliveryModel.id)
        .limit(MAX_DOCUMENT_DELIVERIES + 1)
        .with_for_update(read=True, nowait=True)
    )
    # Do not load provider IDs, template bodies, error text or credentials.
    deliveries = [SimpleNamespace(**dict(row._mapping)) for row in result]
    if len(deliveries) > MAX_DOCUMENT_DELIVERIES:
        raise ArtifactError("Document export exceeds its delivery-source limit", 413)
    passengers = await support.passengers(group.id, current_user=actor, session=session)
    return DocumentExportSource(
        passengers,
        documents,
        deliveries,
        {
            "group": _values(group),
            "passports": [_values(row) for row in passports],
            "documents": [_values(row) for row in documents],
            "deliveries": [vars(row) for row in deliveries],
        },
    )
