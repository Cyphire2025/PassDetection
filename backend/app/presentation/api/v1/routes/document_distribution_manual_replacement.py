"""Retain a replaced passenger assignment and its full delivery/file history."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.infrastructure.database.models import (
    DistributedDocumentModel,
    DocumentWhatsAppDeliveryModel,
    UserModel,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.routes.document_distribution_replacements import (
    ReplacementDocumentVersion,
    _document_version,
)
from app.presentation.api.v1.routes.document_distribution_storage import (
    _released_document_passenger_ids,
)


async def supersede_passenger_documents(
    session: AsyncSession, *, agency_id: uuid.UUID, group_id: uuid.UUID,
    document_type: str, passenger_id: uuid.UUID, versions: list[ReplacementDocumentVersion],
    replacement_id: uuid.UUID, actor: UserModel | User,
) -> tuple[uuid.UUID, ...]:
    ids = [version.id for version in versions]
    existing = list((await session.scalars(select(DistributedDocumentModel).where(
        DistributedDocumentModel.id.in_(ids), DistributedDocumentModel.agency_id == agency_id,
        DistributedDocumentModel.group_id == group_id, DistributedDocumentModel.document_type == document_type,
        DistributedDocumentModel.passenger_id == passenger_id,
        DistributedDocumentModel.match_status != "superseded",
    ).order_by(DistributedDocumentModel.id).with_for_update().execution_options(populate_existing=True))).all())
    observed = {document.id: _document_version(document.updated_at) for document in existing}
    if observed != {version.id: version.updated_at for version in versions}:
        raise HTTPException(status_code=409, detail="This saved PDF changed. Refresh the list and select it again.")
    active = await session.scalar(select(DocumentWhatsAppDeliveryModel.id).where(
        DocumentWhatsAppDeliveryModel.distributed_document_id.in_(ids),
        DocumentWhatsAppDeliveryModel.agency_id == agency_id,
        DocumentWhatsAppDeliveryModel.group_id == group_id,
        DocumentWhatsAppDeliveryModel.status.in_({"queued", "processing", "delivery_unknown"}),
    ).with_for_update().limit(1))
    if active is not None:
        raise HTTPException(status_code=409, detail="Resolve this PDF's active or uncertain WhatsApp delivery before replacing it.")
    released = await _released_document_passenger_ids(session, agency_id=agency_id,
        group_id=group_id, document_ids=ids)
    for document in existing:
        document.match_status = "superseded"
        document.updated_at = datetime.now(UTC)
    await AuditLogRepository(session).record(
        action="document_distribution_passenger_document_replaced", entity_type="distributed_document",
        entity_id=str(replacement_id), agency_id=agency_id, user_id=actor.id, actor_email=actor.email,
        metadata={"group_id": str(group_id), "passenger_id": str(passenger_id),
            "document_type": document_type, "previous_document_ids": list(map(str, ids)),
            "replacement_document_id": str(replacement_id), "previous_files_and_deliveries_retained": True},
    )
    return released
