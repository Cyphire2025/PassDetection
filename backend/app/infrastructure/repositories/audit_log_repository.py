"""
Audit Log Repository
====================
Durable audit trail for security and operational actions.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from math import isfinite
from typing import Any, Literal, cast

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.infrastructure.database.models import AuditChainHeadModel, AuditLogModel

AuditResult = Literal["success", "blocked", "denied", "failed"]


@dataclass(frozen=True, slots=True)
class AuditLogFilters:
    agency_id: uuid.UUID | None
    start_at: datetime | None = None
    end_at: datetime | None = None
    actor: str | None = None
    event_type: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    result: AuditResult | None = None

    def fingerprint(self) -> str:
        values = (
            self.agency_id,
            self.start_at,
            self.end_at,
            self.actor,
            self.event_type,
            self.entity_type,
            self.entity_id,
            self.result,
        )
        encoded = "|".join(_cursor_value(value) for value in values)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class AuditLogPage:
    items: tuple[AuditLogModel, ...]
    has_more: bool
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class AuditChainVerification:
    scope_key: str
    valid: bool
    verified_entries: int
    first_invalid_sequence: int | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class _AuditCursor:
    last_created_at: datetime
    last_id: uuid.UUID
    snapshot_created_at: datetime
    snapshot_id: uuid.UUID
    filter_fingerprint: str


class InvalidAuditCursorError(ValueError):
    """A cursor is malformed or belongs to a different filter scope."""


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
        scope_key = audit_integrity_scope(agency_id)
        rows = list(
            (
                await self._session.execute(
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
            calculated = audit_entry_hash(
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

        head = await self._session.scalar(
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
        if not rows and head is not None and (
            head.last_sequence != 0 or head.last_hash != "0" * 64
        ):
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


def audit_log_result(log: AuditLogModel) -> AuditResult:
    return cast(AuditResult, log.result)


def audit_integrity_scope(agency_id: uuid.UUID | None) -> str:
    return f"agency:{agency_id}" if agency_id is not None else "global"


def audit_entry_hash(
    *,
    scope_key: str,
    sequence: int,
    previous_hash: str,
    record_id: uuid.UUID,
    agency_id: uuid.UUID | None,
    user_id: uuid.UUID | None,
    actor_email: str | None,
    action: str,
    entity_type: str,
    entity_id: str | None,
    ip_address: str | None,
    result: AuditResult,
    metadata: dict[str, Any],
    created_at: datetime,
) -> str:
    canonical = {
        "action": action,
        "actor_email": actor_email,
        "agency_id": str(agency_id) if agency_id is not None else None,
        "created_at": _utc(created_at).isoformat(),
        "entity_id": entity_id,
        "entity_type": entity_type,
        "id": str(record_id),
        "integrity_scope": scope_key,
        "integrity_sequence": sequence,
        "integrity_version": 1,
        "ip_address": ip_address,
        "metadata": _canonical_audit_value(metadata),
        "previous_hash": previous_hash,
        "result": result,
        "user_id": str(user_id) if user_id is not None else None,
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_audit_value(value: object) -> object:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("Audit metadata cannot contain non-finite numbers")
        return value
    if isinstance(value, datetime):
        return _utc(value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (uuid.UUID, Decimal)):
        return str(value)
    if isinstance(value, Enum):
        return _canonical_audit_value(value.value)
    if isinstance(value, dict):
        return {
            str(key): _canonical_audit_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_audit_value(item) for item in value]
    raise TypeError(f"Unsupported audit metadata value: {type(value).__name__}")


def _apply_filters(
    statement: Select[tuple[AuditLogModel]],
    filters: AuditLogFilters,
) -> Select[tuple[AuditLogModel]]:
    if filters.agency_id is not None:
        statement = statement.where(AuditLogModel.agency_id == filters.agency_id)
    if filters.start_at is not None:
        statement = statement.where(AuditLogModel.created_at >= filters.start_at)
    if filters.end_at is not None:
        statement = statement.where(AuditLogModel.created_at <= filters.end_at)
    if filters.actor:
        try:
            actor_id = uuid.UUID(filters.actor)
        except ValueError:
            statement = statement.where(
                AuditLogModel.actor_email.ilike(
                    f"%{_escape_like(filters.actor)}%",
                    escape="\\",
                )
            )
        else:
            statement = statement.where(AuditLogModel.user_id == actor_id)
    if filters.event_type:
        statement = statement.where(AuditLogModel.action == filters.event_type)
    if filters.entity_type:
        statement = statement.where(AuditLogModel.entity_type == filters.entity_type)
    if filters.entity_id:
        statement = statement.where(AuditLogModel.entity_id == filters.entity_id)
    if filters.result:
        statement = statement.where(AuditLogModel.result == filters.result)
    return statement


def _encode_cursor(cursor: _AuditCursor) -> str:
    payload = {
        "v": 1,
        "last_created_at": _utc(cursor.last_created_at).isoformat(),
        "last_id": str(cursor.last_id),
        "snapshot_created_at": _utc(cursor.snapshot_created_at).isoformat(),
        "snapshot_id": str(cursor.snapshot_id),
        "filters": cursor.filter_fingerprint,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> _AuditCursor:
    try:
        padding = "=" * (-len(value) % 4)
        raw = base64.b64decode(
            f"{value}{padding}",
            altchars=b"-_",
            validate=True,
        )
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict) or payload.get("v") != 1:
            raise ValueError
        last_created_at = datetime.fromisoformat(str(payload["last_created_at"]))
        snapshot_created_at = datetime.fromisoformat(str(payload["snapshot_created_at"]))
        filter_fingerprint = str(payload["filters"])
        if len(filter_fingerprint) != 24:
            raise ValueError
        return _AuditCursor(
            last_created_at=_require_aware(last_created_at),
            last_id=uuid.UUID(str(payload["last_id"])),
            snapshot_created_at=_require_aware(snapshot_created_at),
            snapshot_id=uuid.UUID(str(payload["snapshot_id"])),
            filter_fingerprint=filter_fingerprint,
        )
    except (
        binascii.Error,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
    ) as exc:
        raise InvalidAuditCursorError("Audit cursor is invalid") from exc


def _cursor_value(value: object) -> str:
    if isinstance(value, datetime):
        return _utc(value).isoformat()
    if value is None:
        return "-"
    return str(value)


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Cursor timestamps must include a UTC offset")
    return value.astimezone(UTC)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


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
