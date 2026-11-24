"""Read and verify one complete durable audit integrity scope."""

from __future__ import annotations

import uuid
from typing import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import AuditChainHeadModel, AuditLogModel
from app.infrastructure.repositories.audit_log_integrity import (
    audit_integrity_scope,
    audit_log_result,
)
from app.infrastructure.repositories.audit_log_types import AuditChainVerification


async def verify_audit_chain(
    session: AsyncSession,
    agency_id: uuid.UUID | None,
    *,
    entry_hash: Callable[..., str],
) -> AuditChainVerification:
    scope_key = audit_integrity_scope(agency_id)
    rows = list(
        (
            await session.execute(
                select(AuditLogModel)
                .where(
                    AuditLogModel.integrity_version == 1,
                    AuditLogModel.integrity_scope == scope_key,
                )
                .order_by(AuditLogModel.integrity_sequence, AuditLogModel.id)
            )
        ).scalars()
    )
    expected_previous = "0" * 64
    expected_sequence = 1
    for row in rows:
        if row.integrity_sequence != expected_sequence:
            return AuditChainVerification(
                scope_key=scope_key,
                valid=False,
                verified_entries=expected_sequence - 1,
                first_invalid_sequence=expected_sequence,
                reason="sequence_gap",
            )
        if row.previous_hash != expected_previous:
            return AuditChainVerification(
                scope_key=scope_key,
                valid=False,
                verified_entries=expected_sequence - 1,
                first_invalid_sequence=expected_sequence,
                reason="previous_hash_mismatch",
            )
        calculated = entry_hash(
            scope_key=scope_key,
            sequence=expected_sequence,
            previous_hash=expected_previous,
            record_id=row.id,
            agency_id=row.agency_id,
            user_id=row.user_id,
            actor_email=row.actor_email,
            action=row.action,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            ip_address=row.ip_address,
            result=audit_log_result(row),
            metadata=row.metadata_json or {},
            created_at=row.created_at,
        )
        if row.entry_hash != calculated:
            return AuditChainVerification(
                scope_key=scope_key,
                valid=False,
                verified_entries=expected_sequence - 1,
                first_invalid_sequence=expected_sequence,
                reason="entry_hash_mismatch",
            )
        expected_previous = calculated
        expected_sequence += 1

    head = await session.scalar(
        select(AuditChainHeadModel).where(AuditChainHeadModel.scope_key == scope_key)
    )
    if rows and (
        head is None
        or head.last_sequence != expected_sequence - 1
        or head.last_hash != expected_previous
    ):
        return AuditChainVerification(
            scope_key=scope_key,
            valid=False,
            verified_entries=len(rows),
            first_invalid_sequence=expected_sequence,
            reason="chain_head_mismatch",
        )
    if not rows and head is not None and (head.last_sequence != 0 or head.last_hash != "0" * 64):
        return AuditChainVerification(
            scope_key=scope_key,
            valid=False,
            verified_entries=0,
            first_invalid_sequence=1,
            reason="nonempty_chain_head_without_entries",
        )
    return AuditChainVerification(
        scope_key=scope_key,
        valid=True,
        verified_entries=len(rows),
        first_invalid_sequence=None,
        reason=None,
    )
