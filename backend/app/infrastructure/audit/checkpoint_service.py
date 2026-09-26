"""Verify persisted chains against independent signed anchors before publishing."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.interfaces.audit_integrity_sink import (
    AuditIntegrityCheckpoint,
    AuditIntegritySink,
)
from app.infrastructure.audit.checkpoint_codec import AuditIntegrityError
from app.infrastructure.database.models import AuditChainHeadModel, AuditLogModel
from app.infrastructure.repositories.audit_log_repository import audit_entry_hash, audit_log_result


async def verify_and_publish(session: AsyncSession, sink: AuditIntegritySink, *, publish: bool) -> dict[str, int]:
    """Use a read-only REPEATABLE READ transaction for a stable database snapshot.

    External anchors are checked first, including scopes no longer present in
    the database. No new checkpoint is published if an existing anchor or any
    complete chain disagrees. Streaming avoids loading event history into RAM.
    """
    anchors = 0
    anchored_scopes: set[str] = set()
    async for checkpoint in sink.checkpoints():
        stored_hash = await session.scalar(select(AuditLogModel.entry_hash).where(
            AuditLogModel.integrity_scope == checkpoint.scope_key,
            AuditLogModel.integrity_version == checkpoint.integrity_version,
            AuditLogModel.integrity_sequence == checkpoint.last_sequence,
        ))
        if stored_hash != checkpoint.last_hash:
            raise AuditIntegrityError("database_disagrees_with_independent_anchor")
        anchors += 1
        anchored_scopes.add(checkpoint.scope_key)
    if not publish and anchors == 0:
        raise AuditIntegrityError("no_independent_anchors")
    heads = list((await session.scalars(select(AuditChainHeadModel).order_by(AuditChainHeadModel.scope_key))).all())
    # A removed chain head must not hide orphaned entries from verification.
    orphan = await session.scalar(select(AuditLogModel.id).outerjoin(
        AuditChainHeadModel, AuditChainHeadModel.scope_key == AuditLogModel.integrity_scope,
    ).where(AuditLogModel.integrity_version == 1, AuditChainHeadModel.scope_key.is_(None)).limit(1))
    if orphan is not None:
        raise AuditIntegrityError("audit_entries_without_chain_head")
    pending = []
    entries = 0
    for head in heads:
        sequence, previous = 0, "0" * 64
        rows = await session.stream_scalars(select(AuditLogModel).where(
            AuditLogModel.integrity_scope == head.scope_key,
            AuditLogModel.integrity_version == 1,
        ).order_by(AuditLogModel.integrity_sequence).execution_options(yield_per=500))
        async for row in rows:
            sequence += 1
            if row.integrity_sequence != sequence or row.previous_hash != previous:
                raise AuditIntegrityError("audit_chain_sequence_or_link_invalid")
            calculated = audit_entry_hash(
                scope_key=head.scope_key, sequence=sequence, previous_hash=previous,
                record_id=row.id, agency_id=row.agency_id, user_id=row.user_id,
                actor_email=row.actor_email, action=row.action, entity_type=row.entity_type,
                entity_id=row.entity_id, ip_address=row.ip_address, result=audit_log_result(row),
                metadata=row.metadata_json or {}, created_at=row.created_at,
            )
            if row.entry_hash != calculated:
                raise AuditIntegrityError("audit_chain_content_invalid")
            previous = calculated
        if head.integrity_version != 1 or head.last_sequence != sequence or head.last_hash != previous:
            raise AuditIntegrityError("audit_chain_head_invalid")
        entries += sequence
        if sequence:
            if not publish and head.scope_key not in anchored_scopes:
                raise AuditIntegrityError("nonempty_audit_scope_has_no_independent_anchor")
            pending.append(AuditIntegrityCheckpoint(head.scope_key, 1, sequence, previous, datetime.now(UTC)))
    if publish:
        for checkpoint in pending:
            await sink.publish(checkpoint)
    return {"verified_anchors": anchors, "verified_chains": len(heads), "verified_entries": entries,
            "published_checkpoints": len(pending) if publish else 0}
