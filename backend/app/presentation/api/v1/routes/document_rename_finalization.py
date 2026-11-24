"""Fresh actor admission, database staging and ambiguous-commit policy."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging.logger import get_logger
from app.domain.entities.entities import User
from app.infrastructure.database.models import (
    DocumentRenameItemModel,
)
from app.infrastructure.documents.storage_transfers import (
    finish_cleanup_despite_cancellation,
)
from app.presentation.api.v1.routes.document_rename_chunk_staging import stage_rename_chunk
from app.presentation.api.v1.routes.document_rename_upload_contracts import (
    PreparedRenameUpload,
    RenameFinalizationServices,
    StagedRenameUpload,
)
from app.presentation.api.v1.schemas.document_rename_schemas import (
    RenameDocumentBatchResponse,
)

logger = get_logger("app.presentation.api.v1.routes.document_rename")


async def finalize_rename_upload(
    prepared: PreparedRenameUpload,
    staged: StagedRenameUpload,
    current_user: User,
    session: AsyncSession,
    *,
    services: RenameFinalizationServices,
) -> RenameDocumentBatchResponse:
    agency_id = prepared.agency_id
    actor_id = prepared.actor_id
    expected_actor_role = prepared.expected_actor_role
    chunk_metadata = prepared.chunk_metadata
    batch_id = prepared.batch_id
    batch = staged.batch
    items = staged.items
    uploaded_keys = staged.uploaded_keys
    storage = staged.storage
    now = staged.now
    try:
        actor = await services.lock_actor(
            session,
            user_id=actor_id,
            agency_id=agency_id,
            expected_role=expected_actor_role,
            current_user=current_user,
        )
        complete = True
        if chunk_metadata is not None:
            batch, complete, replay_response = await stage_rename_chunk(
                prepared, staged, actor, session, services=services
            )
            if replay_response is not None:
                return replay_response
        batch.total_count += len(items)
        batch.visa_count += sum((1 for item in items if item.detected_type == "visa"))
        batch.ticket_count += sum((1 for item in items if item.detected_type == "flight_ticket"))
        batch.unknown_count += sum((1 for item in items if item.detected_type == "unknown"))
        batch.status = "completed" if complete else "processing"
        batch.updated_at = now
        session.add(batch)
        for item in items:
            session.add(item)
        await services.audit_factory(session).record(
            action="document_rename_completed" if complete else "document_rename_chunk_uploaded",
            entity_type="document_rename_batch",
            entity_id=str(batch.id),
            agency_id=agency_id,
            user_id=actor.id,
            actor_email=actor.email,
            metadata={
                "total_count": batch.total_count,
                "visa_count": batch.visa_count,
                "ticket_count": batch.ticket_count,
                "unknown_count": batch.unknown_count,
                "stored_count": len(uploaded_keys),
                "chunk_index": chunk_metadata.chunk_index if chunk_metadata else None,
            },
        )
        await session.flush()
    except BaseException:
        try:
            await session.rollback()
        finally:
            await finish_cleanup_despite_cancellation(
                services.cleanup(storage, uploaded_keys, agency_id=agency_id, batch_id=batch_id)
            )
        raise
    try:
        await session.commit()
    except Exception:
        # A failed COMMIT response does not prove rollback. Retain uploaded
        # objects that durable rows may reference for safe reconciliation.
        await session.rollback()
        logger.warning(
            "document_rename_commit_outcome_ambiguous",
            batch_id=str(batch_id),
            object_count=len(uploaded_keys),
        )
        raise
    if chunk_metadata is None:
        return await services.batch_response(batch, items)
    if getattr(batch, "status", "completed") != "completed":
        return await services.batch_response(batch, [])
    all_items_result = await session.execute(
        select(DocumentRenameItemModel)
        .where(
            DocumentRenameItemModel.batch_id == batch_id,
            DocumentRenameItemModel.agency_id == agency_id,
        )
        .order_by(DocumentRenameItemModel.renamed_filename.asc())
    )
    return await services.batch_response(batch, list(all_items_result.scalars().all()))
