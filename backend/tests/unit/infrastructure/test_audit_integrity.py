from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import AuditChainHeadModel, AuditLogModel
from app.infrastructure.repositories.audit_log_repository import (
    AuditLogRepository,
    audit_entry_hash,
    audit_integrity_scope,
)


class _Scalars:
    def __init__(self, values: list[AuditLogModel]) -> None:
        self._values = values

    def __iter__(self):
        return iter(self._values)


class _RowsResult:
    def __init__(self, values: list[AuditLogModel]) -> None:
        self._values = values

    def scalars(self) -> _Scalars:
        return _Scalars(self._values)


class _VerificationSession:
    def __init__(
        self,
        rows: list[AuditLogModel],
        head: AuditChainHeadModel | None,
    ) -> None:
        self._rows = rows
        self._head = head

    async def execute(self, _statement: object) -> _RowsResult:
        return _RowsResult(self._rows)

    async def scalar(self, _statement: object) -> AuditChainHeadModel | None:
        return self._head


def _entry(
    *,
    sequence: int,
    previous_hash: str,
    agency_id: uuid.UUID,
    created_at: datetime,
) -> AuditLogModel:
    record_id = uuid.UUID(int=sequence)
    metadata = {
        "attempt": sequence,
        "when": created_at,
        "local_date": date(2026, 8, 23),
        "amount": Decimal("1.25"),
    }
    entry_hash = audit_entry_hash(
        scope_key=audit_integrity_scope(agency_id),
        sequence=sequence,
        previous_hash=previous_hash,
        record_id=record_id,
        agency_id=agency_id,
        user_id=uuid.UUID(int=500),
        actor_email="auditor@example.test",
        action="audit.chain.tested",
        entity_type="audit_chain",
        entity_id=str(agency_id),
        ip_address=None,
        result="success",
        metadata=metadata,
        created_at=created_at,
    )
    return AuditLogModel(
        id=record_id,
        agency_id=agency_id,
        user_id=uuid.UUID(int=500),
        actor_email="auditor@example.test",
        action="audit.chain.tested",
        entity_type="audit_chain",
        entity_id=str(agency_id),
        ip_address=None,
        result="success",
        metadata_json=metadata,
        integrity_version=1,
        integrity_scope=audit_integrity_scope(agency_id),
        integrity_sequence=sequence,
        previous_hash=previous_hash,
        entry_hash=entry_hash,
        created_at=created_at,
    )


@pytest.mark.asyncio
async def test_verify_chain_accepts_a_complete_tenant_chain() -> None:
    agency_id = uuid.UUID(int=100)
    created_at = datetime(2026, 8, 23, 10, 0, tzinfo=UTC)
    first = _entry(
        sequence=1,
        previous_hash="0" * 64,
        agency_id=agency_id,
        created_at=created_at,
    )
    second = _entry(
        sequence=2,
        previous_hash=cast(str, first.entry_hash),
        agency_id=agency_id,
        created_at=created_at,
    )
    head = AuditChainHeadModel(
        scope_key=audit_integrity_scope(agency_id),
        agency_id=agency_id,
        integrity_version=1,
        last_sequence=2,
        last_hash=second.entry_hash,
        created_at=created_at,
        updated_at=created_at,
    )

    result = await AuditLogRepository(
        cast(AsyncSession, _VerificationSession([first, second], head))
    ).verify_chain(agency_id)

    assert result.valid is True
    assert result.verified_entries == 2
    assert result.reason is None


@pytest.mark.asyncio
async def test_verify_chain_detects_tampered_metadata_without_exposing_it() -> None:
    agency_id = uuid.UUID(int=100)
    created_at = datetime(2026, 8, 23, 10, 0, tzinfo=UTC)
    row = _entry(
        sequence=1,
        previous_hash="0" * 64,
        agency_id=agency_id,
        created_at=created_at,
    )
    row.metadata_json = {"attempt": 999}
    head = AuditChainHeadModel(
        scope_key=audit_integrity_scope(agency_id),
        agency_id=agency_id,
        integrity_version=1,
        last_sequence=1,
        last_hash=row.entry_hash,
        created_at=created_at,
        updated_at=created_at,
    )

    result = await AuditLogRepository(
        cast(AsyncSession, _VerificationSession([row], head))
    ).verify_chain(agency_id)

    assert result.valid is False
    assert result.first_invalid_sequence == 1
    assert result.reason == "entry_hash_mismatch"


def test_audit_hash_is_canonical_across_metadata_key_order() -> None:
    common = {
        "scope_key": "global",
        "sequence": 1,
        "previous_hash": "0" * 64,
        "record_id": uuid.UUID(int=1),
        "agency_id": None,
        "user_id": None,
        "actor_email": None,
        "action": "system.started",
        "entity_type": "system",
        "entity_id": None,
        "ip_address": None,
        "result": "success",
        "created_at": datetime(2026, 8, 23, 10, 0, tzinfo=UTC),
    }

    left = audit_entry_hash(metadata={"b": 2, "a": 1}, **common)
    right = audit_entry_hash(metadata={"a": 1, "b": 2}, **common)

    assert left == right


def test_audit_hash_rejects_nonfinite_metadata() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        audit_entry_hash(
            scope_key="global",
            sequence=1,
            previous_hash="0" * 64,
            record_id=uuid.UUID(int=1),
            agency_id=None,
            user_id=None,
            actor_email=None,
            action="system.started",
            entity_type="system",
            entity_id=None,
            ip_address=None,
            result="success",
            metadata={"invalid": float("nan")},
            created_at=datetime(2026, 8, 23, 10, 0, tzinfo=UTC),
        )
