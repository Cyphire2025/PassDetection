"""Durable audit writes and tenant-scoped reads; public compatibility facade."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import AuditChainHeadModel, AuditLogModel
from app.infrastructure.repositories.audit_chain_verification import verify_audit_chain
from app.infrastructure.repositories.audit_log_integrity import audit_entry_hash as audit_entry_hash
from app.infrastructure.repositories.audit_log_integrity import (
    audit_integrity_scope as audit_integrity_scope,
)
from app.infrastructure.repositories.audit_log_integrity import audit_log_result as audit_log_result
from app.infrastructure.repositories.audit_log_paging import (
    _apply_filters,
    _decode_cursor,
    _encode_cursor,
)
from app.infrastructure.repositories.audit_log_types import (
    AuditChainVerification as AuditChainVerification,
)
from app.infrastructure.repositories.audit_log_types import AuditLogFilters as AuditLogFilters
from app.infrastructure.repositories.audit_log_types import AuditLogPage as AuditLogPage
from app.infrastructure.repositories.audit_log_types import AuditResult as AuditResult
from app.infrastructure.repositories.audit_log_types import (
    InvalidAuditCursorError as InvalidAuditCursorError,
)
from app.infrastructure.repositories.audit_log_types import _AuditCursor as _AuditCursor
from app.infrastructure.repositories.audit_log_values import (
    _canonical_audit_value as _canonical_audit_value,
)
from app.infrastructure.repositories.audit_log_values import _cursor_value as _cursor_value
from app.infrastructure.repositories.audit_log_values import _escape_like as _escape_like
from app.infrastructure.repositories.audit_log_values import _require_aware as _require_aware
from app.infrastructure.repositories.audit_log_values import _utc as _utc


class AuditLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        action: str,
        entity_type: str,
        agency_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        actor_email: str | None = None,
        entity_id: str | None = None,
        ip_address: str | None = None,
        result: AuditResult = "success",
        metadata: dict[str, Any] | None = None,
    ) -> AuditLogModel:
        record_id = uuid.uuid4()
        created_at = datetime.now(tz=UTC)
        scope_key = audit_integrity_scope(agency_id)
        await self._session.execute(
            pg_insert(AuditChainHeadModel)
            .values(
                scope_key=scope_key,
                agency_id=agency_id,
                integrity_version=1,
                last_sequence=0,
                last_hash="0" * 64,
                created_at=created_at,
                updated_at=created_at,
            )
            .on_conflict_do_nothing(index_elements=["scope_key"])
        )
        chain_head = (
            await self._session.execute(
                select(AuditChainHeadModel)
                .where(AuditChainHeadModel.scope_key == scope_key)
                .with_for_update()
            )
        ).scalar_one()
        sequence = chain_head.last_sequence + 1
        previous_hash = chain_head.last_hash
        entry_hash = audit_entry_hash(
            scope_key=scope_key,
            sequence=sequence,
            previous_hash=previous_hash,
            record_id=record_id,
            agency_id=agency_id,
            user_id=user_id,
            actor_email=actor_email,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            ip_address=ip_address,
            result=result,
            metadata=metadata or {},
            created_at=created_at,
        )
        model = AuditLogModel(
            id=record_id,
            agency_id=agency_id,
            user_id=user_id,
            actor_email=actor_email,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            ip_address=ip_address,
            result=result,
            metadata_json=metadata or {},
            integrity_version=1,
            integrity_scope=scope_key,
            integrity_sequence=sequence,
            previous_hash=previous_hash,
            entry_hash=entry_hash,
            created_at=created_at,
        )
        self._session.add(model)
        chain_head.last_sequence = sequence
        chain_head.last_hash = entry_hash
        chain_head.updated_at = created_at
        await self._session.flush()
        return model

    async def verify_chain(
        self,
        agency_id: uuid.UUID | None,
    ) -> AuditChainVerification:
        return await verify_audit_chain(self._session, agency_id, entry_hash=audit_entry_hash)

    async def list_by_agency(
        self,
        agency_id: uuid.UUID | None,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> list[AuditLogModel]:
        stmt = select(AuditLogModel)
        if agency_id is not None:
            stmt = stmt.where(AuditLogModel.agency_id == agency_id)
        stmt = (
            stmt.order_by(
                AuditLogModel.created_at.desc(),
                AuditLogModel.id.desc(),
            )
            .offset(skip)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_page(
        self,
        filters: AuditLogFilters,
        *,
        cursor: str | None,
        limit: int,
    ) -> AuditLogPage:
        decoded = _decode_cursor(cursor) if cursor else None
        expected_fingerprint = filters.fingerprint()
        if decoded is not None and decoded.filter_fingerprint != expected_fingerprint:
            raise InvalidAuditCursorError("Cursor does not match the current filters")

        statement = _apply_filters(select(AuditLogModel), filters)
        if decoded is not None:
            statement = statement.where(
                or_(
                    AuditLogModel.created_at < decoded.snapshot_created_at,
                    (
                        (AuditLogModel.created_at == decoded.snapshot_created_at)
                        & (AuditLogModel.id <= decoded.snapshot_id)
                    ),
                ),
                or_(
                    AuditLogModel.created_at < decoded.last_created_at,
                    (
                        (AuditLogModel.created_at == decoded.last_created_at)
                        & (AuditLogModel.id < decoded.last_id)
                    ),
                ),
            )
        rows = list(
            (
                await self._session.execute(
                    statement.order_by(
                        AuditLogModel.created_at.desc(),
                        AuditLogModel.id.desc(),
                    ).limit(limit + 1)
                )
            )
            .scalars()
            .all()
        )
        has_more = len(rows) > limit
        items = tuple(rows[:limit])
        next_cursor: str | None = None
        if has_more and items:
            first = items[0]
            last = items[-1]
            snapshot_created_at = decoded.snapshot_created_at if decoded else first.created_at
            snapshot_id = decoded.snapshot_id if decoded else first.id
            next_cursor = _encode_cursor(
                _AuditCursor(
                    last_created_at=last.created_at,
                    last_id=last.id,
                    snapshot_created_at=snapshot_created_at,
                    snapshot_id=snapshot_id,
                    filter_fingerprint=expected_fingerprint,
                )
            )
        return AuditLogPage(
            items=items,
            has_more=has_more,
            next_cursor=next_cursor,
        )

    async def list_for_export(
        self,
        filters: AuditLogFilters,
        *,
        limit: int,
    ) -> tuple[list[AuditLogModel], bool]:
        statement = _apply_filters(select(AuditLogModel), filters).order_by(
            AuditLogModel.created_at.desc(),
            AuditLogModel.id.desc(),
        )
        rows = list((await self._session.execute(statement.limit(limit + 1))).scalars().all())
        return rows[:limit], len(rows) > limit


__all__ = [
    "AuditChainVerification",
    "AuditResult",
    "AuditLogFilters",
    "AuditLogPage",
    "AuditLogRepository",
    "InvalidAuditCursorError",
    "audit_log_result",
    "audit_entry_hash",
    "audit_integrity_scope",
]
