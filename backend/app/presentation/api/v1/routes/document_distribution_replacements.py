"""Versioned same-filename replacement within the upload transaction."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.passenger_change_propagation import propagate_mobile_passenger_change
from app.infrastructure.database.models import (
    DistributedDocumentModel,
    DocumentWhatsAppDeliveryModel,
)
from app.infrastructure.documents.distribution_capacity import (
    MAX_DISTRIBUTION_ASSIGNMENT_ROWS_PER_SCOPE,
)
from app.infrastructure.documents.storage_cleanup import stage_storage_cleanup_jobs
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.document_uploads import bounded_upload_filename
from app.presentation.api.v1.routes.document_distribution_queries import (
    _refresh_distribution_batches,
)
from app.presentation.api.v1.routes.document_distribution_storage import (
    _released_document_passenger_ids,
)

MAX_FILENAME_REPLACEMENTS_LENGTH = 512 * 1024


class ReplacementDocumentVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: uuid.UUID
    updated_at: datetime

    @field_validator("updated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Document versions must include a timezone")
        return value.astimezone(UTC)


class FilenameReplacement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1, max_length=255)
    documents: list[ReplacementDocumentVersion] = Field(
        min_length=1, max_length=MAX_DISTRIBUTION_ASSIGNMENT_ROWS_PER_SCOPE
    )


def parse_filename_replacements(
    value: str | None, *, incoming_filenames: list[str]
) -> dict[str, FilenameReplacement]:
    names = [bounded_upload_filename(name) for name in incoming_filenames]
    if len(names) != len(set(names)):
        raise HTTPException(
            status_code=409,
            detail="Several selected PDFs have the same filename. Choose which copy to keep first.",
        )
    if not value:
        return {}
    if len(value) > MAX_FILENAME_REPLACEMENTS_LENGTH:
        raise HTTPException(status_code=413, detail="The filename replacement selection is too large")
    try:
        replacements = TypeAdapter(list[FilenameReplacement]).validate_json(value)
    except ValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail="The filename replacement selection is invalid. Refresh the document list.",
        ) from exc
    if len(replacements) > len(names):
        raise HTTPException(status_code=400, detail="Unexpected filename replacement selection")
    by_name: dict[str, FilenameReplacement] = {}
    all_ids: set[uuid.UUID] = set()
    for item in replacements:
        key = bounded_upload_filename(item.filename)
        ids = {document.id for document in item.documents}
        if (
            key != item.filename
            or key not in names
            or key in by_name
            or len(ids) != len(item.documents)
            or ids & all_ids
        ):
            raise HTTPException(status_code=400, detail="The filename replacement selection is invalid")
        by_name[key] = item
        all_ids.update(ids)
    if len(all_ids) > MAX_DISTRIBUTION_ASSIGNMENT_ROWS_PER_SCOPE:
        raise HTTPException(status_code=413, detail="The filename replacement selection is too large")
    return by_name


def replacement_chunk_fingerprint(
    fingerprint: str | None, replacements: dict[str, FilenameReplacement]
) -> str | None:
    if fingerprint is None or not replacements:
        return fingerprint
    decisions = [
        {
            "filename": filename,
            "documents": [
                {"id": str(document.id), "updated_at": document.updated_at.isoformat()}
                for document in sorted(item.documents, key=lambda row: str(row.id))
            ],
        }
        for filename, item in sorted(replacements.items())
    ]
    encoded = json.dumps(decisions, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(
        f"{fingerprint}\x00filename-replacements-v1\x00{encoded}".encode()
    ).hexdigest()


def _document_version(value: datetime) -> datetime:
    # PostgreSQL returns timezone-aware values; naive SQLite/local timestamps
    # represent UTC in this application's model defaults.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def apply_filename_replacements(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    document_type: str,
    new_documents: list[DistributedDocumentModel],
    replacements: dict[str, FilenameReplacement],
    actor_id: uuid.UUID,
    actor_email: str | None,
) -> tuple[uuid.UUID, ...]:
    """Replace only successfully stored/matched files, preserving delivery history.

    Caller holds current actor/group, lane advisory and scope batch locks. New
    document rows are not yet added to the session; failure rolls back both old
    deletion and new insertion in the canonical ingestion compensation boundary.
    """
    if not new_documents:
        return ()
    names = {bounded_upload_filename(document.original_filename) for document in new_documents}
    # Bounded complete scope read also recognizes older saved names with the
    # same canonical spelling; comparison remains exact and case-sensitive.
    result = await session.execute(
        select(DistributedDocumentModel)
        .where(
            DistributedDocumentModel.agency_id == agency_id,
            DistributedDocumentModel.group_id == group_id,
            DistributedDocumentModel.document_type == document_type,
        )
        .order_by(DistributedDocumentModel.id)
        .limit(MAX_DISTRIBUTION_ASSIGNMENT_ROWS_PER_SCOPE + 1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    existing = list(result.scalars().all())
    if len(existing) > MAX_DISTRIBUTION_ASSIGNMENT_ROWS_PER_SCOPE:
        raise HTTPException(status_code=409, detail="This document list exceeds its supported limit")
    by_name: dict[str, list[DistributedDocumentModel]] = {}
    for document in existing:
        key = bounded_upload_filename(document.original_filename)
        if key in names:
            by_name.setdefault(key, []).append(document)
    to_remove: list[DistributedDocumentModel] = []
    for filename in sorted(names):
        current = by_name.get(filename, [])
        decision = replacements.get(filename)
        if not current and decision is None:
            continue
        observed = {document.id: _document_version(document.updated_at) for document in current}
        expected = (
            {document.id: document.updated_at for document in decision.documents}
            if decision is not None
            else {}
        )
        if not current or decision is None or observed != expected:
            raise HTTPException(
                status_code=409,
                detail=(
                    f'A saved PDF named "{filename}" changed or needs a replacement choice. '
                    "Refresh the document list and choose Replace or Keep original again."
                ),
            )
        to_remove.extend(current)
    if not to_remove:
        return ()
    incoming_batch_ids = {document.batch_id for document in new_documents}
    if any(document.batch_id in incoming_batch_ids for document in to_remove):
        raise HTTPException(
            status_code=409,
            detail=(
                "The same filename was already uploaded in this session. "
                "Start a new upload to replace it."
            ),
        )
    ids = [document.id for document in to_remove]
    active_delivery = await session.scalar(
        select(DocumentWhatsAppDeliveryModel.id)
        .where(
            DocumentWhatsAppDeliveryModel.agency_id == agency_id,
            DocumentWhatsAppDeliveryModel.group_id == group_id,
            DocumentWhatsAppDeliveryModel.distributed_document_id.in_(ids),
            DocumentWhatsAppDeliveryModel.status.in_({"queued", "processing", "delivery_unknown"}),
        )
        .order_by(DocumentWhatsAppDeliveryModel.id)
        .with_for_update()
        .limit(1)
    )
    if active_delivery is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "A same-name PDF has an active or uncertain WhatsApp delivery. "
                "Resolve that delivery before replacing it."
            ),
        )
    released = await _released_document_passenger_ids(
        session,
        agency_id=agency_id,
        group_id=group_id,
        document_ids=ids,
    )
    keys = sorted({document.storage_key for document in to_remove})
    still_used = set(
        (await session.scalars(
            select(DistributedDocumentModel.storage_key).where(
                DistributedDocumentModel.storage_key.in_(keys),
                DistributedDocumentModel.id.notin_(ids),
            )
        )).all()
    )
    jobs = stage_storage_cleanup_jobs(
        session,
        agency_id=agency_id,
        source="document_distribution_replace",
        context_id=f"{group_id}:{document_type}:" + ",".join(sorted(map(str, ids))),
        storage_keys=[key for key in keys if key not in still_used],
    )
    affected_batches = {document.batch_id for document in to_remove}
    for document in to_remove:
        await session.delete(document)
    await session.flush()
    await _refresh_distribution_batches(
        session,
        batch_ids=affected_batches,
        agency_id=agency_id,
        group_id=group_id,
        now=datetime.now(tz=UTC),
    )
    if released:
        await propagate_mobile_passenger_change(
            session,
            agency_id=agency_id,
            group_id=group_id,
            passenger_submission_ids=released,
            actor_user_id=actor_id,
            operation="delete",
            change_kind="documents",
            reconcile_identities=False,
        )
    await AuditLogRepository(session).record(
        action="document_distribution_filenames_replaced",
        entity_type="client_group",
        entity_id=str(group_id),
        agency_id=agency_id,
        user_id=actor_id,
        actor_email=actor_email,
        metadata={
            "document_type": document_type,
            "upload_id": str(new_documents[0].batch_id),
            "replaced_document_ids": sorted(map(str, ids)),
            "replacement_document_ids": sorted(
                str(document.id)
                for document in new_documents
                if bounded_upload_filename(document.original_filename) in by_name
            ),
            "replaced_file_count": len(by_name),
        },
    )
    # Delivery ledger rows retain all original snapshots via ON DELETE SET NULL;
    # neither delivery statuses nor prior provider IDs transfer to the new PDFs.
    return tuple(job.id for job in jobs)
