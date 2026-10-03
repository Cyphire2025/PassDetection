"""Project the canonical queue under a rollback-only preparation savepoint."""

from __future__ import annotations

import uuid
from collections import Counter
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app.application.mcp.credentials import utc
from app.application.mcp.document_delivery_capacity import document_delivery_within_capacity
from app.application.mcp.document_delivery_dto import MCPDocumentDeliveryDraft
from app.application.mcp.document_delivery_sources import document_source
from app.application.mcp.operations import MCPDatabaseContext, MCPOperationError
from app.application.mcp.whatsapp_intents import snapshot_hash
from app.application.use_cases.whatsapp.document_templates import render_document_message
from app.core.config.settings import Settings
from app.infrastructure.database.models import (
    ClientGroupModel,
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.infrastructure.whatsapp.template_settings import TEMPLATE_SETTINGS_MEMO
from app.presentation.api.v1.routes.document_distribution_delivery import (
    queue_document_whatsapp_broadcast,
)
from app.presentation.api.v1.routes.document_distribution_scope import (
    _get_visible_document_batch,
    _lock_active_document_scope,
)
from app.presentation.api.v1.schemas.document_distribution_schemas import (
    DocumentDeliveryPreviewRecipient,
    DocumentDeliveryPreviewResponse,
    SendDocumentBroadcastRequest,
    SendDocumentBroadcastResponse,
)


async def document_delivery_snapshot(
    context: MCPDatabaseContext, payload: dict[str, Any], settings: Settings,
    *, expected_hash: str | None = None,
) -> tuple[dict[str, Any], SendDocumentBroadcastResponse]:
    try:
        draft = MCPDocumentDeliveryDraft.model_validate(payload)
    except (ValidationError, ValueError) as exc:
        raise MCPOperationError("invalid_document_delivery_draft") from exc
    user = await UserRepository(context.session).get_by_id(context.principal.user_id)
    if user is None:
        raise MCPOperationError("document_delivery_unavailable")
    batch = await _get_visible_document_batch(context.session, batch_id=draft.batch_id, current_user=user)
    if batch is None or batch.agency_id != draft.agency_id or batch.group_id != draft.group_id:
        raise MCPOperationError("document_delivery_scope_mismatch")
    try:
        await _lock_active_document_scope(context.session, current_user=user,
                                         group_id=draft.group_id, agency_id=draft.agency_id,
                                         identity_already_locked=True)
    except HTTPException as exc:
        raise MCPOperationError("document_delivery_scope_unavailable") from exc
    if not await document_delivery_within_capacity(context.session, agency_id=draft.agency_id,
            group_id=draft.group_id, document_type=batch.document_type):
        raise MCPOperationError("document_delivery_preview_capacity_exceeded")
    snapshot: dict[str, Any] = {}

    async def guard(batch: DocumentDistributionBatchModel, group: ClientGroupModel,
                    preview: DocumentDeliveryPreviewResponse, rows: list[DocumentDeliveryPreviewRecipient],
                    documents: dict[uuid.UUID, DistributedDocumentModel]) -> None:
        if (batch.agency_id != draft.agency_id or batch.group_id != draft.group_id
                or group.agency_id != draft.agency_id or batch.status != "saved"
                or group.deleted_at is not None or group.status in {"archived", "deleted"}):
            raise MCPOperationError("document_delivery_scope_mismatch")
        if set(documents) != set(draft.document_ids) or len(rows) != len(draft.document_ids):
            raise MCPOperationError("document_delivery_selection_changed")
        if any(document.content_type != "application/pdf" or document.match_status != "matched"
               or not document.storage_key for document in documents.values()):
            raise MCPOperationError("document_delivery_source_unavailable")
        batches = list((await context.session.scalars(
            select(DocumentDistributionBatchModel).where(
                DocumentDistributionBatchModel.id.in_({item.batch_id for item in documents.values()}),
                DocumentDistributionBatchModel.agency_id == draft.agency_id,
                DocumentDistributionBatchModel.group_id == draft.group_id,
                DocumentDistributionBatchModel.status == "saved",
            ).order_by(DocumentDistributionBatchModel.id).execution_options(populate_existing=True)
        )).all())
        if {item.id for item in batches} != {item.batch_id for item in documents.values()}:
            raise MCPOperationError("document_delivery_source_unavailable")
        excluded = [row for row in preview.recipients if row.document_id not in set(draft.document_ids)]
        snapshot.update({
            "schema_version": 1, "agency_id": str(draft.agency_id), "group_id": str(group.id),
            "group_name": group.name, "document_batch_id": str(batch.id),
            "document_type": batch.document_type, "request": draft.model_dump(mode="json"),
            "preview_token": preview.preview_token,
            "template_name": preview.template_name, "language": settings.whatsapp_template_language,
            "body_parameters": [draft.message_content_1, draft.message_content_2],
            "rendered_message": render_document_message(message_content_1=draft.message_content_1,
                                                         message_content_2=draft.message_content_2),
            "sources": [document_source(documents[key]) for key in sorted(documents, key=str)],
            "source_batches": [{"id": str(item.id), "revision": utc(item.updated_at).isoformat(),
                                "document_type": item.document_type} for item in batches],
            "recipients": [{
                "document_id": str(row.document_id), "passenger_id": str(row.passenger_id),
                "passenger_name": row.passenger_name, "passport_number": row.passport_number,
                "filename": row.document_filename, "document_type": row.document_type,
                "recipient_id": str(row.recipient_id) if row.recipient_id else None,
                "broadcast_id": str(row.broadcast_group_id), "broadcast_name": row.broadcast_name,
                "phone_number": row.phone_number, "phone_source": row.phone_source,
            } for row in sorted(rows, key=lambda row: str(row.document_id))],
            "exclusions": {"count": len(excluded),
                           "reasons": dict(sorted(Counter(row.reason for row in excluded).items())),
                           "travellers_without_document": preview.summary.excluded_without_document},
            "source_binding": "Exact saved object reference and database revision; no file-byte checksum is claimed.",
        })
        if expected_hash is not None and snapshot_hash(snapshot) != expected_hash:
            raise MCPOperationError("document_delivery_preview_changed")

    async def project() -> tuple[dict[str, Any], SendDocumentBroadcastResponse]:
        context.session.info.pop(TEMPLATE_SETTINGS_MEMO, None)
        try:
            response = await queue_document_whatsapp_broadcast(
                draft.batch_id,
                SendDocumentBroadcastRequest(document_ids=draft.document_ids,
                    message_content_1=draft.message_content_1, message_content_2=draft.message_content_2),
                current_user=user, session=context.session, before_queue=guard,
                identity_already_locked=True,
            )
        except HTTPException as exc:
            raise MCPOperationError("document_delivery_unavailable") from exc
        if response.queued_count != len(draft.document_ids):
            raise MCPOperationError("document_delivery_selection_changed")
        return snapshot, response

    if expected_hash is not None:
        return await project()
    # Preparation exercises canonical eligibility without persisting any queue,
    # retry claim, or audit. No storage, broker or provider request occurs here.
    async with context.session.begin_nested() as savepoint:
        result = await project()
        await savepoint.rollback()
        return result
