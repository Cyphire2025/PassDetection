"""Deterministic hash projection of durable audit entries."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any, cast

from app.infrastructure.database.models import AuditLogModel
from app.infrastructure.repositories.audit_log_types import AuditResult
from app.infrastructure.repositories.audit_log_values import _canonical_audit_value, _utc


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
